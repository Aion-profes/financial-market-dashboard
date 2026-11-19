"""Sorties et risque : stop, objectif, taille de position et sortie simulée.

Règles : SPEC_SORTIES_RISQUE.md. Ce module ne modifie pas les étapes 1 à 3 : il
part des entrées acceptées par l'étape 3 et décide ce que devient chaque position.
Simulation uniquement : aucun ordre n'est transmis à un courtier.

Deux notions restent séparées dans tout le fichier :
- la VALORISATION en EUR, faite au taux de référence (BCE) ;
- les CONVERSIONS réellement simulées entre EUR et USD, avec leur coût.
Détenir des USD ne coûte rien ; seule une conversion a un coût.
"""

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from etape_01_tendance import DOSSIER_PROJET, SYMBOLES, ecrire_csv, valider_clotures
from etape_03_entree_1h import (
    _preparer_daily, construire_grille, instant_utc, normaliser_horaires,
    scanner_entrees, scenario_fictif,
)


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc

# Paramètres V1 : hypothèses de simulation, pas des valeurs optimales.
PERIODE_ATR = 14
COEFFICIENT_ATR = Decimal("0.25")     # stop = plus bas − 0,25 × ATR14
MULTIPLE_OBJECTIF = Decimal("2")      # objectif = entrée + 2 × (entrée − stop)
SEANCES_DETENTION = 10                # D1 = séance d'entrée ; sortie à la clôture de D10
RISQUE_PAR_POSITION = 0.005           # 0,5 % de l'equity
RISQUE_CUMULE = 0.01                  # 1 % de l'equity pour toutes les positions ouvertes
CAPITAL_DEPART = 1000.0               # EUR
PAS_ENTIER = "1"                      # actions entières : valeur par défaut
PAS_FRACTION = "0.0001"               # scénario « fractions », à confirmer chez le courtier
TOLERANCE_EUR = 1e-9                  # arrondi informatique : un milliardième d'euro

# Pas de prix : hypothèse écrite ici, à confirmer chez le courtier (voir la spécification).
INSTRUMENTS = {symbole: {"pas_prix": "0.01", "devise": "USD"} for symbole in SYMBOLES}
INSTRUMENT_FICTIF = {"pas_prix": "0.01", "devise": "USD"}

# Réglages indépendants. Les valeurs « ibkr_* » viennent des barèmes publics du courtier.
# plancher : commission minimale d'un ordre comportant une fraction d'action.
# externes : frais de place, de compensation et réglementaires facturés en plus (barème « Tiered »).
BAREMES_COMMISSIONS = {
    "aucun": {"libelle": "Sans commission (théorique)",
              "par_action": 0.0, "minimum": 0.0, "plafond": None, "plancher": 0.0,
              "externes_par_action": 0.0, "externes_vente_taux": 0.0},
    "ibkr_fixe": {"libelle": "Barème public IBKR « Fixed » : 0,005 USD par action, minimum 1 USD, plafond 1 %",
                  "par_action": 0.005, "minimum": 1.00, "plafond": 0.01, "plancher": 0.01,
                  "externes_par_action": 0.0, "externes_vente_taux": 0.0},
    "ibkr_tiered": {"libelle": "Barème public IBKR « Tiered » : 0,0035 USD par action, minimum 0,35 USD, "
                               "plafond 1 %, frais externes estimés en plus",
                    "par_action": 0.0035, "minimum": 0.35, "plafond": 0.01, "plancher": 0.01,
                    # Hypothèse : 0,0030 USD de frais de place + 0,0002 USD de compensation par action,
                    # et 20,60 USD par million vendu (frais de la SEC en vigueur depuis avril 2026).
                    "externes_par_action": 0.0032, "externes_vente_taux": 0.0000206},
    "synthetique": {"libelle": "SYNTHÉTIQUE : commissions inventées pour les tests",
                    "par_action": 0.01, "minimum": 0.50, "plafond": None, "plancher": 0.0,
                    "externes_par_action": 0.0, "externes_vente_taux": 0.0},
}
MODES_CONVERSION = {
    "sans_cout": {"libelle": "Conversion au taux de référence, sans coût (théorique)",
                  "taux": 0.0, "minimum_usd": 0.0},
    "ibkr_auto": {"libelle": "Conversion automatique IBKR : 0,03 % compris dans le taux",
                  "taux": 0.0003, "minimum_usd": 0.0},
    "ibkr_manuelle": {"libelle": "Conversion manuelle IBKR : 0,002 %, minimum 2 USD par conversion",
                      "taux": 0.00002, "minimum_usd": 2.00},
    "synthetique": {"libelle": "SYNTHÉTIQUE : 0,1 % inventé pour les tests",
                    "taux": 0.001, "minimum_usd": 0.0},
}
# Ce que deviennent les USD reçus d'une vente. Un achat ne convertit jamais que les USD qui manquent.
SCENARIOS_CHANGE = {
    "usd_conserves": "Les USD d'une vente restent en USD et paient les achats suivants",
    "retour_eur": "Chaque vente est reconvertie en EUR",
}
# Quand le produit d'une vente redevient-il disponible pour un achat ? Un compte au comptant
# n'achète qu'avec des liquidités réglées. « actions » et « change » sont des nombres de jours
# de règlement : séances NASDAQ qui ne sont pas des jours fériés bancaires américains.
# Délai de règlement des actions américaines selon la date de la vente :
# J+3 jusqu'au 04/09/2017, J+2 du 05/09/2017 au 27/05/2024, J+1 depuis le 28/05/2024.
CYCLES_DE_REGLEMENT = ((date(2024, 5, 28), 1), (date(2017, 9, 5), 2), (date.min, 3))
REGLEMENTS = {
    "immediat": {"libelle": "Produit d'une vente réutilisable tout de suite (théorique)",
                 "actions": 0, "change": 0},
    "historique": {"libelle": "Vente d'actions disponible au délai de règlement en vigueur à sa date "
                              "(J+1 depuis le 28/05/2024), à l'ouverture",
                   "supplement": 0},
    "historique_plus_un": {"libelle": "Délai de règlement en vigueur plus un jour ouvré, à l'ouverture",
                           "supplement": 1},
    "j1_prudent": {"libelle": "Vente d'actions disponible à l'ouverture du jour de règlement suivant (J+1) ; "
                              "conversion J+2",
                   "actions": 1, "change": 2},
    "j2_defavorable": {"libelle": "Vente d'actions disponible un jour de règlement plus tard (J+2) ; "
                                  "conversion J+3",
                       "actions": 2, "change": 3},
}
# Scénarios d'exécution validés le 16/11/2026 : des hypothèses de simulation, pas des mesures.
SCENARIOS_EXECUTION = {
    "principal": {"libelle": "Glissement de 2 points de base ; règlement au délai en vigueur",
                  "glissement_bps": 2.0, "reglement": "historique"},
    "defavorable": {"libelle": "Glissement de 10 points de base ; un jour de règlement de plus",
                    "glissement_bps": 10.0, "reglement": "historique_plus_un"},
}
# Configurations nommées. Le barème du compte étant inconnu, les deux scénarios IBKR sont
# toujours calculés côte à côte : aucun n'est choisi en silence. Leur glissement et leur
# règlement viennent du scénario d'exécution ; la configuration théorique n'en a pas.
CONFIGURATIONS = {
    "IBKR_CASH_AUTO_FRACTIONS_FIXED": {
        "libelle": "Compte au comptant, conversion automatique, fractions, barème « Fixed »",
        "pas_quantite": PAS_FRACTION, "commissions": "ibkr_fixe", "conversion": "ibkr_auto",
        "scenario_change": "usd_conserves",
    },
    "IBKR_CASH_AUTO_FRACTIONS_TIERED": {
        "libelle": "Compte au comptant, conversion automatique, fractions, barème « Tiered »",
        "pas_quantite": PAS_FRACTION, "commissions": "ibkr_tiered", "conversion": "ibkr_auto",
        "scenario_change": "usd_conserves",
    },
    "THEORIQUE_SANS_COUTS": {
        "libelle": "Résultat brut théorique : fractions, aucun coût, aucun délai de règlement",
        "pas_quantite": PAS_FRACTION, "commissions": "aucun", "conversion": "sans_cout",
        "scenario_change": "usd_conserves", "reglement": "immediat", "glissement_bps": 0.0,
    },
}
SCENARIOS_DE_COUTS = ("IBKR_CASH_AUTO_FRACTIONS_FIXED", "IBKR_CASH_AUTO_FRACTIONS_TIERED")
# Le barème (« Fixed » ou « Tiered ») reste inconnu : aucun résultat n'est celui du compte réel.
HYPOTHESES_CONFIRMEES = False

CHAMPS_POSITION = [
    "symbole", "date_sommet", "statut", "motif", "ambigu_intrabar", "cible_a_l_egalite",
    "facteur_division", "signal_instant", "plus_bas", "atr", "atr_seance", "atr_debut_historique",
    "stop_brut", "stop", "entree_instant", "entree_prix", "entree_prix_execute",
    "distance", "cible_brute", "cible", "ratio_effectif",
    "seance_d1", "seance_d10", "equity_eur", "budget_eur", "risque_reserve_eur",
    "taux_entree", "taux_entree_jour", "especes_eur_avant", "especes_usd_avant",
    "disponible_eur_avant", "disponible_usd_avant", "attente_eur_avant", "attente_usd_avant",
    "quantite", "montant_usd", "montant_eur", "conversion_entree_usd", "risque_prix_eur",
    "couts_stop_eur", "couts_change_stop_eur", "risque_prevu_eur", "contrainte", "risque_minimal_eur",
    "sortie_instant", "sortie_bougie", "sortie_prix", "sortie_prix_execute", "sortie_au_marche",
    "seance_detention",
    "dernier_prix", "dernier_instant", "non_evaluable_depuis",
    "taux_sortie", "taux_sortie_jour", "conversion_sortie_usd",
    "brut_usd", "brut_eur", "effet_change_eur", "commissions_eur", "glissement_eur",
    "couts_change_eur", "couts_eur", "apres_couts_eur", "multiple_r", "multiple_r_apres_couts",
    "equity_apres_eur", "commissions", "conversion", "scenario_change", "reglement",
    "glissement_par_action", "glissement_bps", "hypotheses_confirmees",
]
CHAMPS_CONVERSION = [
    "instant", "symbole", "operation", "sens", "montant_usd", "montant_eur",
    "taux_reference", "taux_reference_jour", "taux_execution", "cout_eur",
]


# ---------------------------------------------------------------- ATR, stop, objectif

def calculer_atr(bougies, periode=PERIODE_ATR):
    """ATR de Wilder, une valeur par séance ; None tant qu'il manque des séances.

    bougies : séances Daily consécutives avec high, low et cloture.
    Il faut periode + 1 séances pour la première valeur (14 écarts « vrais »).
    """
    atr = [None] * len(bougies)
    ecarts = []
    for indice in range(1, len(bougies)):
        haut, bas = bougies[indice]["high"], bougies[indice]["low"]
        precedente = bougies[indice - 1]["cloture"]
        # L'écart « vrai » tient compte d'un gap depuis la clôture précédente.
        ecart = max(haut - bas, abs(haut - precedente), abs(bas - precedente))
        ecarts.append(ecart)
        if len(ecarts) == periode:
            atr[indice] = mean(ecarts)
        elif len(ecarts) > periode:
            atr[indice] = (atr[indice - 1] * (periode - 1) + ecart) / periode
    return atr


def arrondir_au_pas(valeur, pas, vers_le_haut=False):
    """Arrondit à un multiple du pas, en décimal exact : 95,999 -> 95,99 vers le bas."""
    valeur = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
    pas = Decimal(str(pas))
    sens = ROUND_CEILING if vers_le_haut else ROUND_FLOOR
    return (valeur / pas).to_integral_value(rounding=sens) * pas


def distance_de_risque(entree, stop):
    """Entrée − stop, calculée en décimal exact : 344,285 − 339,93 = 4,355 et non 4,35500000000002."""
    return float(Decimal(str(entree)) - Decimal(str(stop)))


def calculer_stop(plus_bas, atr, pas_prix):
    """Renvoie (stop brut, stop) : plus bas − 0,25 × ATR, arrondi vers le bas au pas de prix."""
    plus_bas, atr = valider_clotures([plus_bas, atr])
    brut = Decimal(str(plus_bas)) - COEFFICIENT_ATR * Decimal(str(atr))
    stop = arrondir_au_pas(brut, pas_prix)
    if stop <= 0:
        raise ValueError("Stop non positif : volatilité trop grande pour ce prix.")
    return float(brut), float(stop)


def calculer_cible(entree, stop, pas_prix):
    """Renvoie (objectif brut, objectif, ratio effectif).

    La distance part du stop déjà arrondi ; l'objectif brut vaut entrée + 2 × distance,
    puis il est arrondi vers le haut au pas de prix.
    """
    entree, stop = (Decimal(str(prix)) for prix in valider_clotures([entree, stop]))
    if entree <= stop:
        raise ValueError("L'entrée doit être strictement au-dessus du stop.")
    brute = entree + MULTIPLE_OBJECTIF * (entree - stop)
    cible = arrondir_au_pas(brute, pas_prix, vers_le_haut=True)
    return float(brute), float(cible), float((cible - entree) / (entree - stop))


# ---------------------------------------------------------------- hypothèses de coûts et d'exécution

def creer_hypotheses(commissions="aucun", conversion="sans_cout", scenario_change="usd_conserves",
                     glissement_par_action=0.0, reglement="immediat", glissement_bps=0.0):
    """Rassemble les hypothèses de coûts et d'exécution d'une simulation.

    Par défaut : aucun coût ni délai, donc un résultat brut théorique. Aucune valeur
    n'est présentée comme celle d'un compte réel.
    glissement_par_action : en USD. glissement_bps : en points de base du prix
    (1 point de base = 0,01 %). Les deux s'appliquent aux ordres au marché.
    """
    if commissions not in BAREMES_COMMISSIONS:
        raise ValueError(f"Barème de commissions inconnu : {commissions}")
    if conversion not in MODES_CONVERSION:
        raise ValueError(f"Mode de conversion inconnu : {conversion}")
    if scenario_change not in SCENARIOS_CHANGE:
        raise ValueError(f"Scénario de change inconnu : {scenario_change}")
    if reglement not in REGLEMENTS:
        raise ValueError(f"Convention de règlement inconnue : {reglement}")
    if glissement_par_action < 0 or glissement_bps < 0:
        raise ValueError("Le glissement ne peut pas être négatif.")
    return {
        "nom_commissions": commissions, "commissions": BAREMES_COMMISSIONS[commissions],
        "nom_conversion": conversion, "conversion": MODES_CONVERSION[conversion],
        "scenario_change": scenario_change, "reglement": reglement,
        "glissement_par_action": glissement_par_action, "glissement_bps": glissement_bps,
    }


def configurer(nom, execution="principal"):
    """Renvoie (hypothèses, pas de quantité) d'une configuration nommée de CONFIGURATIONS.

    execution : « principal » ou « defavorable » (SCENARIOS_EXECUTION) ; il fixe le glissement
    et le délai de règlement des deux scénarios de coûts. La configuration théorique l'ignore.
    """
    if nom not in CONFIGURATIONS:
        raise ValueError(f"Configuration inconnue : {nom}")
    if execution not in SCENARIOS_EXECUTION:
        raise ValueError(f"Scénario d'exécution inconnu : {execution}")
    reglages = {**SCENARIOS_EXECUTION[execution], **CONFIGURATIONS[nom]}
    hypotheses = creer_hypotheses(reglages["commissions"], reglages["conversion"], reglages["scenario_change"],
                                  0.0, reglages["reglement"], reglages["glissement_bps"])
    return hypotheses, reglages["pas_quantite"]


def delai_de_reglement(jour):
    """Nombre de jours de règlement d'une vente d'actions américaines faite ce jour-là."""
    return next(delai for debut, delai in CYCLES_DE_REGLEMENT if jour >= debut)


def delais_de(reglement, jour):
    """Délais, en jours de règlement, d'une vente d'actions et d'une conversion pour cette convention."""
    regles = REGLEMENTS[reglement]
    if "supplement" not in regles:
        return {"actions": regles["actions"], "change": regles["change"]}
    actions = delai_de_reglement(jour) + regles["supplement"]
    # Une opération de change se règle d'ordinaire en deux jours, jamais avant la vente elle-même.
    return {"actions": actions, "change": max(2 + regles["supplement"], actions)}


def facteur_de_division(divisions, jour):
    """Par combien multiplier un cours continu pour retrouver le cours réel de ce jour.

    divisions : couples (date d'effet, rapport). Une division de 10 pour 1 postérieure à
    « jour » signifie que l'action valait alors dix fois son cours continu.
    """
    facteur = 1
    for date_division, rapport in divisions:
        if date_division > jour:
            facteur *= rapport
    return facteur


def _reel(prix, facteur):
    """Cours réel de l'époque à partir du cours continu ; l'arrondi efface le bruit du calcul."""
    return prix if facteur == 1 else round(prix * facteur, 6)


def sans_couts(hypotheses):
    """Vrai si aucune commission, aucun coût de conversion et aucun glissement ne sont simulés."""
    commissions, conversion = hypotheses["commissions"], hypotheses["conversion"]
    return (commissions["par_action"] == 0 and commissions["minimum"] == 0
            and commissions["plancher"] == 0 and commissions["externes_par_action"] == 0
            and commissions["externes_vente_taux"] == 0
            and conversion["taux"] == 0 and conversion["minimum_usd"] == 0
            and hypotheses["glissement_par_action"] == 0 and hypotheses["glissement_bps"] == 0)


def decrire_hypotheses(hypotheses):
    """Une phrase qui nomme chaque hypothèse : elle accompagne tout résultat affiché."""
    par_action, points = hypotheses["glissement_par_action"], hypotheses["glissement_bps"]
    if par_action == 0 and points == 0:
        texte_glissement = "hypothèse de glissement nul"
    else:
        parts = ([f"{_nombre(par_action, 4)} USD par action"] if par_action else []) + (
            [f"{_nombre(points, 1)} point(s) de base du prix"] if points else [])
        texte_glissement = f"glissement de {' + '.join(parts)} sur les ordres au marché"
    scenario = SCENARIOS_CHANGE[hypotheses["scenario_change"]]
    reglement = REGLEMENTS[hypotheses["reglement"]]["libelle"]
    return (f"{hypotheses['commissions']['libelle']} ; {hypotheses['conversion']['libelle']} ; "
            f"{scenario[0].lower()}{scenario[1:]} ; {reglement[0].lower()}{reglement[1:]} ; {texte_glissement}")


def cotation_fixe(eur_par_usd=1.0):
    """Taux de change inventé et constant, pour les démonstrations et les tests."""
    cotation = {"jour": None, "usd_par_eur": 1 / eur_par_usd, "eur_par_usd": eur_par_usd}
    return lambda _instant: dict(cotation)


# ---------------------------------------------------------------- coûts et règlements

def commission_usd(bareme, quantite, prix, vente=False):
    """Frais d'un ordre : commission du courtier, plus les frais externes du barème s'il en a.

    Commission : par action, avec un minimum, puis un plafond en % du montant, et enfin
    un plancher (0,01 USD chez IBKR pour un ordre comportant une fraction d'action).
    Frais externes : par action, plus un pourcentage du montant sur les ventes seulement.
    """
    if quantite <= 0:
        return 0.0
    commission = max(bareme["par_action"] * quantite, bareme["minimum"])
    if bareme["plafond"] is not None:
        commission = min(commission, bareme["plafond"] * quantite * prix)
    commission = max(commission, bareme["plancher"])
    externes = bareme["externes_par_action"] * quantite
    if vente:
        externes += bareme["externes_vente_taux"] * quantite * prix
    return commission + externes


def glissement_usd(hypotheses, quantite, prix):
    """Glissement d'un ordre au marché : un montant par action, plus une part du prix."""
    return quantite * (hypotheses["glissement_par_action"] + prix * hypotheses["glissement_bps"] / 10000)


def cout_conversion_eur(mode, montant_usd, taux):
    """Coût, en EUR, d'une conversion de montant_usd dollars (dans un sens ou dans l'autre).

    taux : EUR pour 1 USD, au taux de référence. Le minimum des barèmes est exprimé en USD.
    Sans conversion (montant nul), il n'y a aucun coût : détenir des USD est gratuit.
    """
    if montant_usd <= 0:
        return 0.0
    return max(montant_usd * taux * mode["taux"], mode["minimum_usd"] * taux)


def regler_achat(especes, quantite, prix, taux, hypotheses):
    """Paie un achat et renvoie les nouveaux soldes, les coûts et la conversion éventuelle.

    especes : {"EUR": …, "USD": …}. taux : EUR pour 1 USD (référence).
    Les USD disponibles paient d'abord. Seul le manque est acheté avec des EUR,
    au taux de référence plus le coût de conversion : c'est le taux d'exécution simulé.
    """
    commission = commission_usd(hypotheses["commissions"], quantite, prix)
    glissement = glissement_usd(hypotheses, quantite, prix)        # un achat est un ordre au marché
    a_payer = quantite * prix + commission + glissement            # en USD
    manque = max(0.0, a_payer - especes["USD"])
    cout_change = cout_conversion_eur(hypotheses["conversion"], manque, taux)
    return {
        "EUR": especes["EUR"] - manque * taux - cout_change,
        "USD": max(0.0, especes["USD"] - a_payer),
        "commission_usd": commission, "glissement_usd": glissement,
        "usd_achetes": manque, "usd_vendus": 0.0, "cout_change_eur": cout_change,
        # Commission et glissement sont payés en USD ; on les valorise en EUR au taux de référence.
        "couts_eur": (commission + glissement) * taux + cout_change,
    }


def regler_vente(especes, quantite, prix, taux, hypotheses, au_marche=True):
    """Encaisse une vente. Les USD reçus restent en USD, sauf dans le scénario « retour_eur ».

    au_marche : faux pour un objectif (ordre à cours limité), qui ne subit pas de glissement.
    """
    commission = commission_usd(hypotheses["commissions"], quantite, prix, vente=True)
    glissement = glissement_usd(hypotheses, quantite, prix) if au_marche else 0.0
    produit = quantite * prix - commission - glissement           # en USD
    usd = especes["USD"] + produit
    usd_vendus = usd_achetes = 0.0
    if hypotheses["scenario_change"] == "retour_eur" and produit > 0:
        usd_vendus = produit
    elif usd < 0:
        # Frais supérieurs au produit de la vente : un solde négatif est interdit, le manque est acheté.
        usd_achetes = -usd
    cout_change = cout_conversion_eur(hypotheses["conversion"], usd_vendus + usd_achetes, taux)
    return {
        "EUR": especes["EUR"] + (usd_vendus - usd_achetes) * taux - cout_change,
        "USD": max(0.0, usd + usd_achetes - usd_vendus),
        "commission_usd": commission, "glissement_usd": glissement,
        "usd_achetes": usd_achetes, "usd_vendus": usd_vendus, "cout_change_eur": cout_change,
        "couts_eur": (commission + glissement) * taux + cout_change,
    }


# ---------------------------------------------------------------- taille de position

def calculer_quantite(equity, especes, entree, stop, taux, hypotheses, pas_quantite=PAS_ENTIER,
                      risque_reserve=0.0, exposition=0.0):
    """Plus grande quantité qui respecte le budget, le risque cumulé, les liquidités et l'exposition.

    equity, risque_reserve, exposition : en EUR. especes : {"EUR": …, "USD": …}.
    entree, stop : en USD par action. taux : EUR pour 1 USD (référence).
    Les coûts estimés sont ceux d'un aller-retour jusqu'au stop, calculés avec les mêmes
    fonctions de règlement que le résultat final : aucun coût n'est compté deux fois.
    Renvoie un dictionnaire ; quantite vaut 0 si rien ne convient.
    """
    if entree <= stop:
        raise ValueError("L'entrée doit être strictement au-dessus du stop.")
    distance = distance_de_risque(entree, stop)
    pas = Decimal(str(pas_quantite))
    budget = RISQUE_PAR_POSITION * equity
    marge_cumulee = RISQUE_CUMULE * equity - risque_reserve

    def mesurer(nombre_de_pas):
        quantite = float(nombre_de_pas * pas)
        achat = regler_achat(especes, quantite, entree, taux, hypotheses)
        vente_au_stop = regler_vente(achat, quantite, stop, taux, hypotheses)
        risque_prix = quantite * distance * taux
        couts_stop = achat["couts_eur"] + vente_au_stop["couts_eur"]
        return {
            "quantite": quantite, "montant_eur": quantite * entree * taux,
            "risque_prix_eur": risque_prix, "couts_stop_eur": couts_stop,
            "couts_change_stop_eur": achat["cout_change_eur"] + vente_au_stop["cout_change_eur"],
            "risque_prevu_eur": risque_prix + couts_stop,
            "conversion_entree_usd": achat["usd_achetes"], "eur_apres_achat": achat["EUR"],
        }

    def contraintes_depassees(mesure):
        depassees = []
        if mesure["risque_prevu_eur"] > budget + TOLERANCE_EUR:
            depassees.append("BUDGET_RISQUE")
        if mesure["risque_prevu_eur"] > marge_cumulee + TOLERANCE_EUR:
            depassees.append("RISQUE_CUMULE")
        if mesure["eur_apres_achat"] < -TOLERANCE_EUR:
            depassees.append("LIQUIDITES")     # ni solde négatif, ni emprunt
        if exposition + mesure["montant_eur"] > equity + TOLERANCE_EUR:
            depassees.append("EXPOSITION")
        return depassees

    # Sans frais, la quantité ne peut pas dépasser ces bornes ; les frais ne font que la réduire.
    pouvoir_d_achat_usd = especes["USD"] + max(0.0, especes["EUR"]) / taux
    borne = min(min(budget, marge_cumulee) / (distance * taux),
                pouvoir_d_achat_usd / entree, (equity - exposition) / (entree * taux))
    bas, haut = 0, max(0, int(Decimal(str(max(0.0, borne))) / pas) + 1)
    # Les contraintes augmentent avec la quantité : on cherche par dichotomie.
    # La quantité renvoyée est toujours vérifiée ; elle ne dépasse donc jamais une limite.
    while bas < haut:
        milieu = (bas + haut + 1) // 2
        if contraintes_depassees(mesurer(milieu)):
            haut = milieu - 1
        else:
            bas = milieu
    resultat = mesurer(bas)
    suivante = mesurer(bas + 1)
    resultat.update(
        budget_eur=budget, marge_cumulee_eur=marge_cumulee,
        # La contrainte qui empêche d'acheter un pas de plus.
        contrainte=";".join(contraintes_depassees(suivante)),
        risque_minimal_eur=mesurer(1)["risque_prevu_eur"],
    )
    return resultat


# ---------------------------------------------------------------- préparation des données

def preparer_marche(symbole, daily, horaires, instant, debut=None, journal=None, grille=None, divisions=()):
    """Rassemble, pour un titre, tout ce que les positions utilisent, connu à cet instant.

    journal et grille : à fournir s'ils sont déjà calculés, pour ne pas les refaire.
    divisions : couples (date d'effet, rapport) des divisions d'actions. Les cours reçus sont
    alors des cours continus (les signaux n'y voient aucun saut) ; chaque position est ensuite
    calculée en cours réels de sa date d'entrée : pas de prix, quantité et commissions d'époque.
    """
    limite = instant_utc(instant)
    jour = limite.astimezone(NEW_YORK).date()
    if grille is None:
        # Trois semaines d'avance : de quoi dater D10 pour une entrée du jour.
        grille = construire_grille(min(bougie["date"] for bougie in daily), jour + timedelta(days=21))
    fins = {ligne["session"]: ligne["fin"] for ligne in grille}
    sessions = sorted(fins)
    # Mêmes séances Daily et mêmes instants de réception que le moteur de l'étape 3.
    bilans, receptions = _preparer_daily(daily, grille, limite)
    seances = sorted(bilans)
    atr = calculer_atr([bilans[seance] for seance in seances])
    if journal is None:
        journal = scanner_entrees(daily, horaires, limite, debut)
    bougies = normaliser_horaires(horaires, limite, grille)
    return {
        "symbole": symbole, "limite": limite, "grille": grille, "fins": fins,
        "sessions": sessions, "rangs": {session: rang for rang, session in enumerate(sessions)},
        "horaires": {bougie["debut"]: bougie for bougie in bougies}, "journal": journal,
        "daily": bilans, "receptions": receptions, "atr": dict(zip(seances, atr)),
        "premiere_seance": seances[0] if seances else None,
        "instrument": INSTRUMENTS.get(symbole, INSTRUMENT_FICTIF), "divisions": tuple(divisions),
    }


def _bougie_complete(bougie):
    return bougie is not None and all(
        bougie[champ] is not None for champ in ("ouverture", "high", "low", "cloture"))


def dernier_prix_connu(marche, instant):
    """Prix le plus récent déjà observé à cet instant : une ouverture ou une clôture horaire."""
    candidats = []
    for bougie in marche["horaires"].values():
        if bougie["cloture"] is not None and bougie["fin"] <= instant:
            candidats.append((bougie["fin"], 0, bougie["cloture"]))
        if bougie["ouverture"] is not None and bougie["debut"] <= instant:
            candidats.append((bougie["debut"], 1, bougie["ouverture"]))
    return max(candidats)[2] if candidats else None


# ---------------------------------------------------------------- plan et sortie d'une position

def stop_du_signal(marche, signal, facteur=1):
    """Stop figé à la clôture du signal : plus bas du moteur horaire et dernier ATR connu.

    facteur : facteur de division de la séance d'entrée ; le plus bas et l'ATR sont alors
    exprimés en cours réels de cette séance, avant l'arrondi au pas de prix.
    """
    plan = {"signal_instant": None, "plus_bas": None, "atr": None, "atr_seance": None,
            "atr_debut_historique": marche["premiere_seance"], "stop_brut": None, "stop": None,
            "motif": None}
    if signal is None or signal["plus_bas_repli"] is None:
        plan["motif"] = "PLUS_BAS_INDISPONIBLE"
        return plan
    plan.update(signal_instant=signal["instant"], plus_bas=_reel(signal["plus_bas_repli"], facteur))
    # Dernière séance Daily reçue à l'instant du signal : jamais la séance encore en cours.
    connues = [seance for seance in marche["atr"] if marche["receptions"][seance] <= signal["instant"]]
    if not connues or marche["atr"][connues[-1]] is None:
        plan["motif"] = "ATR_INDISPONIBLE"
        return plan
    plan.update(atr=_reel(marche["atr"][connues[-1]], facteur), atr_seance=connues[-1])
    try:
        plan["stop_brut"], plan["stop"] = calculer_stop(
            plan["plus_bas"], plan["atr"], marche["instrument"]["pas_prix"])
    except ValueError:
        plan["motif"] = "STOP_NON_POSITIF"
    return plan


def simuler_sortie(marche, entree_instant, stop, cible, facteur=1):
    """Suit une position bougie par bougie, sans rien lire au-delà de l'instant évalué.

    Résultat THÉORIQUE : chaque sortie est supposée exécutée exactement au prix de la règle.
    Rien ne prouve qu'un ordre réel aurait obtenu ce prix (voir la spécification, section 9).
    facteur : les bougies continues sont lues en cours réels de la séance d'entrée. Une
    division pendant la détention ne crée donc ni gain ni perte : la série reste continue.
    """
    grille, fins, rangs, horaires = marche["grille"], marche["fins"], marche["rangs"], marche["horaires"]
    depart = next(indice for indice, creneau in enumerate(grille) if creneau["debut"] == entree_instant)
    d1 = grille[depart]["session"]
    rang_d10 = rangs[d1] + SEANCES_DETENTION - 1
    d10 = marche["sessions"][rang_d10] if rang_d10 < len(marche["sessions"]) else None
    completes = [debut for debut, bougie in horaires.items() if _bougie_complete(bougie)]
    derniere_complete = max(completes) if completes else None
    issue = {"statut": "OUVERTE", "motif": "POSITION_OUVERTE_FIN_DONNEES", "ambigu_intrabar": False,
             "cible_a_l_egalite": False, "sortie_instant": None, "sortie_bougie": None,
             "sortie_prix": None, "sortie_au_marche": None, "seance_detention": 1,
             "dernier_prix": None, "dernier_instant": None, "non_evaluable_depuis": None}

    def sortir(motif, prix, instant, creneau, au_marche=True, ambigu=False, a_l_egalite=False):
        issue.update(statut="CLOTUREE", motif=motif, sortie_prix=prix, sortie_instant=instant,
                     sortie_bougie=creneau["debut"], sortie_au_marche=au_marche, ambigu_intrabar=ambigu,
                     cible_a_l_egalite=a_l_egalite)
        return issue

    for creneau in grille[depart:]:
        if d10 is None or creneau["session"] > d10:
            break
        bougie = horaires.get(creneau["debut"])
        if not _bougie_complete(bougie):
            if derniere_complete is not None and creneau["debut"] < derniere_complete:
                # Un trou suivi de données : on ignore si le stop a été touché.
                issue.update(statut="NON_EVALUABLE", motif="BOUGIE_HORAIRE_MANQUANTE",
                             non_evaluable_depuis=creneau["debut"])
            return issue   # sinon : les données s'arrêtent ici, la position reste ouverte
        # Numéro de la séance de détention : D1 pour la séance d'entrée.
        issue["seance_detention"] = rangs[creneau["session"]] - rangs[d1] + 1
        ouverture, haut, bas, cloture = (_reel(bougie[champ], facteur)
                                         for champ in ("ouverture", "high", "low", "cloture"))
        if creneau["debut"] != entree_instant:
            # 1. À l'ouverture, seul l'Open est connu : un gap ne s'exécute jamais au stop.
            if ouverture <= stop:
                return sortir("STOP_GAP", ouverture, creneau["debut"], creneau)
            if ouverture >= cible:
                return sortir("CIBLE_GAP", cible, creneau["debut"], creneau, au_marche=False,
                              a_l_egalite=ouverture == cible)
        # 2. Pendant la bougie. Si les deux niveaux sont touchés, l'ordre est inconnu : stop d'abord.
        touche_stop, touche_cible = bas <= stop, haut >= cible
        if touche_stop:
            return sortir("STOP", stop, creneau["fin"], creneau, ambigu=touche_cible)
        if touche_cible:
            # Un plus haut exactement égal à l'objectif ne garantit pas qu'un ordre limite soit servi.
            return sortir("CIBLE", cible, creneau["fin"], creneau, au_marche=False,
                          a_l_egalite=haut == cible)
        issue.update(dernier_prix=cloture, dernier_instant=creneau["fin"])
        if creneau["session"] == d10 and creneau["fin"] == fins[d10]:
            # 3. Fin de D10 : liquidation programmée à la clôture officielle (Close Daily).
            if d10 in marche["daily"]:
                return sortir("DUREE_MAX_D10", _reel(marche["daily"][d10]["cloture"], facteur),
                              creneau["fin"], creneau)
            if any(seance > d10 for seance in marche["daily"]):
                issue.update(statut="NON_EVALUABLE", motif="CLOTURE_D10_MANQUANTE",
                             non_evaluable_depuis=creneau["fin"])
            return issue
    return issue


def _position_vide(symbole):
    position = dict.fromkeys(CHAMPS_POSITION)
    position.update(symbole=symbole, ambigu_intrabar=False, cible_a_l_egalite=False)
    return position


def planifier(marche, signal, entree):
    """Stop, objectif et issue d'une entrée acceptée ; la taille vient ensuite, avec le portefeuille."""
    position = _position_vide(marche["symbole"])
    rang_d10 = marche["rangs"][entree["session"]] + SEANCES_DETENTION - 1
    # Tout ce qui suit est en cours réels de la séance d'entrée (facteur 1 sans division à venir).
    facteur = facteur_de_division(marche.get("divisions", ()), entree["session"])
    position.update(
        date_sommet=entree["date_sommet"], entree_instant=entree["instant"], facteur_division=facteur,
        entree_prix=_reel(entree["prix_entree"], facteur), seance_d1=entree["session"],
        seance_d10=marche["sessions"][rang_d10] if rang_d10 < len(marche["sessions"]) else None,
    )
    plan = stop_du_signal(marche, signal, facteur)
    motif = plan.pop("motif")
    position.update(plan)
    if motif is not None:
        position.update(statut="NON_EVALUABLE", motif=motif)
    elif position["entree_prix"] <= position["stop"]:
        # Le stop est figé : on ne le déplace pas pour accepter une ouverture trop basse.
        position.update(statut="REFUSEE", motif="ENTREE_SOUS_STOP")
    else:
        # Ordre des calculs : stop arrondi -> distance -> objectif brut -> objectif arrondi.
        # Ces mêmes niveaux servent ensuite à la taille, à la sortie et à l'affichage.
        position["distance"] = distance_de_risque(position["entree_prix"], position["stop"])
        position["cible_brute"], position["cible"], position["ratio_effectif"] = calculer_cible(
            position["entree_prix"], position["stop"], marche["instrument"]["pas_prix"])
        position["_issue"] = simuler_sortie(
            marche, position["entree_instant"], position["stop"], position["cible"], facteur)
    return position


def chercher_candidats(marche):
    """Une position candidate par entrée acceptée à l'étape 3, dans l'ordre du journal."""
    signaux, candidats = {}, []
    for ligne in marche["journal"]:
        if ligne["signal_horaire"] is True:
            signaux[ligne["date_sommet"]] = ligne
        if ligne["statut"] == "ENTREE_ACCEPTEE":
            candidats.append(planifier(marche, signaux.get(ligne["date_sommet"]), ligne))
    return candidats


def plan_en_attente(marche):
    """Stop déjà figé d'un signal dont l'ouverture d'entrée n'a pas encore eu lieu."""
    if not marche["journal"] or marche["journal"][-1]["statut"] not in ("SIGNAL", "ATTENTE_OUVERTURE"):
        return None
    derniere = marche["journal"][-1]
    signaux = [ligne for ligne in marche["journal"]
               if ligne["signal_horaire"] is True and ligne["date_sommet"] == derniere["date_sommet"]]
    if not signaux:
        return None
    seance_prevue = derniere["ouverture_attendue"].astimezone(NEW_YORK).date()
    plan = stop_du_signal(marche, signaux[-1], facteur_de_division(marche.get("divisions", ()), seance_prevue))
    plan.update(symbole=marche["symbole"], date_sommet=derniere["date_sommet"],
                ouverture_attendue=derniere["ouverture_attendue"])
    return plan


# ---------------------------------------------------------------- portefeuille

def _renseigner_resultats(position, vente, cotation):
    """Résultat d'une position clôturée : prix, change et coûts séparés, puis leur somme en EUR."""
    quantite, entree, sortie = position["quantite"], position["entree_prix"], position["sortie_prix"]
    taux_entree, taux_sortie = position["taux_entree"], cotation["eur_par_usd"]
    brut_usd = quantite * (sortie - entree)
    brut_eur = brut_usd * taux_entree
    # Valorisation : la position en USD a changé de valeur en EUR avec le taux de référence.
    effet_change = quantite * sortie * (taux_sortie - taux_entree)
    # Les coûts d'entrée sont déjà dans la position ; ceux de la sortie s'y ajoutent une seule fois.
    couts = position["couts_eur"] + vente["couts_eur"]
    apres_couts = brut_eur + effet_change - couts
    position.update(
        taux_sortie=taux_sortie, taux_sortie_jour=cotation["jour"],
        conversion_sortie_usd=vente["usd_vendus"], brut_usd=brut_usd, brut_eur=brut_eur,
        effet_change_eur=effet_change,
        commissions_eur=position["commissions_eur"] + vente["commission_usd"] * taux_sortie,
        glissement_eur=position["glissement_eur"] + vente["glissement_usd"] * taux_sortie,
        couts_change_eur=position["couts_change_eur"] + vente["cout_change_eur"],
        couts_eur=couts, apres_couts_eur=apres_couts,
        multiple_r=(sortie - entree) / position["distance"],
        multiple_r_apres_couts=apres_couts / position["risque_prix_eur"],
    )


def compter_positions(positions):
    """Nombre d'entrées par statut et par motif : aucun cas n'est retiré des comptes."""
    decompte = {"entrees": len(positions), "par_statut": {}, "par_motif": {},
                "ambigus": sum(bool(position["ambigu_intrabar"]) for position in positions),
                "cibles_a_l_egalite": sum(bool(position["cible_a_l_egalite"]) for position in positions)}
    for position in positions:
        for cle, valeur in (("par_statut", position["statut"]), ("par_motif", position["motif"])):
            decompte[cle][valeur] = decompte[cle].get(valeur, 0) + 1
    return decompte


def jours_feries_bancaires(annee):
    """Jours où la Bourse américaine ouvre alors que les banques sont fermées.

    Columbus Day (deuxième lundi d'octobre) et Veterans Day (11 novembre, reporté au lundi
    s'il tombe un dimanche). Par prudence, ces jours ne comptent pas comme jours de règlement.
    """
    octobre = date(annee, 10, 1)
    columbus = octobre + timedelta(days=(7 - octobre.weekday()) % 7 + 7)
    veterans = date(annee, 11, 11)
    if veterans.weekday() == 6:
        veterans += timedelta(days=1)
    return {columbus, veterans}


def calendrier_de_reglement(marches):
    """Renvoie (jours de règlement, heure d'ouverture de chaque séance), d'après les grilles."""
    ouvertures = {}
    for marche in marches:
        for creneau in marche["grille"]:
            connue = ouvertures.get(creneau["session"], creneau["debut"])
            ouvertures[creneau["session"]] = min(connue, creneau["debut"])
    feries = set()
    for annee in {session.year for session in ouvertures}:
        feries |= jours_feries_bancaires(annee)
    return sorted(session for session in ouvertures if session not in feries), ouvertures


def instant_de_reglement(calendrier, instant, delai):
    """Ouverture du « delai »-ième jour de règlement après la séance de cet instant.

    delai = 0 : tout de suite. None si le calendrier ne va pas assez loin.
    Un week-end ou un jour férié repousse donc la disponibilité d'autant.
    """
    if delai == 0:
        return instant
    jours, ouvertures = calendrier
    seance = instant.astimezone(NEW_YORK).date()
    suivants = [jour for jour in jours if jour > seance]
    return ouvertures[suivants[delai - 1]] if len(suivants) >= delai else None


def simuler_portefeuille(marches, taux_change, capital=CAPITAL_DEPART, hypotheses=None,
                         pas_quantite=PAS_ENTIER, usd_depart=0.0):
    """Enchaîne les positions dans l'ordre du temps : taille, liquidités, conversions, résultats.

    marches : liste produite par preparer_marche.
    taux_change : fonction « instant -> taux de référence » ; elle renvoie None ou un
    dictionnaire {"jour", "usd_par_eur", "eur_par_usd"} (voir source_bce.taux_de_reference).
    capital : liquidités de départ en EUR. usd_depart : USD déjà détenus au départ.

    Quatre notions restent distinctes :
    - le solde comptable : ce que le compte contient, fonds non réglés compris ;
    - les fonds en attente de règlement : produit d'une vente pas encore réglé ;
    - les fonds disponibles pour un achat : solde comptable moins fonds en attente ;
    - les fonds réservés par un ordre d'achat en cours : toujours 0 ici, car un achat
      simulé est payé à l'instant même où il est décidé.
    """
    hypotheses = creer_hypotheses() if hypotheses is None else hypotheses
    calendrier = calendrier_de_reglement(marches)
    par_symbole = {marche["symbole"]: marche for marche in marches}
    candidats = sorted((candidat for marche in marches for candidat in chercher_candidats(marche)),
                       key=lambda position: (position["entree_instant"], position["symbole"]))
    # Deux soldes comptables. « taux » est le dernier taux de référence utilisé pour valoriser les USD.
    etat = {"EUR": capital, "USD": usd_depart, "taux": None, "effet_change": 0.0, "equity_depart": None}
    ouvertes = {}       # une position au plus par titre
    conversions = []    # uniquement les conversions réellement simulées
    attentes = []       # produits de ventes pas encore réglés

    def especes():
        return {"EUR": etat["EUR"], "USD": etat["USD"]}

    def en_attente(instant):
        """Montants pas encore réglés à cet instant, par devise."""
        montants = {"EUR": 0.0, "USD": 0.0}
        for attente in attentes:
            if attente["disponible_a"] is None or attente["disponible_a"] > instant:
                montants[attente["devise"]] += attente["montant"]
        return montants

    def disponibles(instant):
        """Fonds utilisables pour un achat : le solde comptable moins ce qui attend son règlement."""
        attendus = en_attente(instant)
        return {devise: etat[devise] - attendus[devise] for devise in ("EUR", "USD")}

    def reevaluer(taux):
        """Les USD détenus changent de valeur en EUR avec le taux : effet de change, pas un coût."""
        if etat["taux"] is None:
            etat["equity_depart"] = capital + usd_depart * taux
        else:
            etat["effet_change"] += etat["USD"] * (taux - etat["taux"])
        etat["taux"] = taux

    def enregistrer(mouvement, avant, cotation, instant, position, operation):
        """Applique un règlement aux soldes comptables et note la conversion, s'il y en a une.

        avant : les soldes donnés à la fonction de règlement. Seules les variations comptent.
        Le produit d'une vente entre dans le solde comptable tout de suite, mais il attend
        son règlement avant de pouvoir payer un nouvel achat.
        """
        # Le délai dépend de la date de la vente : J+3, J+2 ou J+1 selon l'époque.
        delais = delais_de(hypotheses["reglement"], instant.astimezone(NEW_YORK).date())
        for devise, delai in (("EUR", delais["change"]), ("USD", delais["actions"])):
            variation = mouvement[devise] - avant[devise]
            if avant[devise] == etat[devise]:
                etat[devise] = mouvement[devise]   # même point de départ : aucune erreur d'arrondi
            else:
                etat[devise] += variation
            if operation == "VENTE" and variation > 0 and delai > 0:
                attentes.append({"devise": devise, "montant": variation, "symbole": position["symbole"],
                                 "vente_instant": instant,
                                 "disponible_a": instant_de_reglement(calendrier, instant, delai)})
        taux = cotation["eur_par_usd"]
        for sens, montant, signe in (("EUR_VERS_USD", mouvement["usd_achetes"], 1),
                                     ("USD_VERS_EUR", mouvement["usd_vendus"], -1)):
            if montant > 0:
                # EUR payés (achat de USD) ou reçus (vente de USD), coût de conversion compris.
                montant_eur = montant * taux + signe * mouvement["cout_change_eur"]
                conversions.append({
                    "instant": instant, "symbole": position["symbole"], "operation": operation,
                    "sens": sens, "montant_usd": montant, "montant_eur": montant_eur,
                    "taux_reference": taux, "taux_reference_jour": cotation["jour"],
                    "taux_execution": montant_eur / montant, "cout_eur": mouvement["cout_change_eur"],
                })

    def valeur(position, instant, taux):
        """Valeur en EUR d'une position ouverte, au dernier prix connu, en cours réels de son entrée."""
        prix = dernier_prix_connu(par_symbole[position["symbole"]], instant)
        prix = position["entree_prix"] if prix is None else _reel(prix, position["facteur_division"])
        return position["quantite"] * prix * taux

    def bloquee(instant):
        return any(position["statut"] == "NON_EVALUABLE"
                   and (instant is None or position["non_evaluable_depuis"] <= instant)
                   for position in ouvertes.values())

    def encaisser_jusqu_a(instant):
        """Règle, dans l'ordre du temps, les positions sorties au plus tard à cet instant."""
        while True:
            sorties = [position for position in ouvertes.values() if position["statut"] == "CLOTUREE"
                       and (instant is None or position["sortie_instant"] <= instant)]
            if not sorties:
                return
            position = min(sorties, key=lambda sortie: sortie["sortie_instant"])
            del ouvertes[position["symbole"]]
            cotation = position.pop("_cotation_sortie")
            taux = cotation["eur_par_usd"]
            reevaluer(taux)
            avant = especes()
            # Division pendant la détention : on vend davantage d'actions, chacune valant moins.
            # La valeur vendue est la même ; seules les commissions par action en dépendent.
            divisions = par_symbole[position["symbole"]].get("divisions", ())
            jour_sortie = position["sortie_instant"].astimezone(NEW_YORK).date()
            rapport = position["facteur_division"] / facteur_de_division(divisions, jour_sortie)
            vente = regler_vente(avant, position["quantite"] * rapport, position["sortie_prix"] / rapport,
                                 taux, hypotheses, position["sortie_au_marche"])
            # Prix réellement obtenu : plus bas que le prix de la règle pour un ordre au marché,
            # jamais sous la limite pour un objectif.
            position["sortie_prix_execute"] = position["sortie_prix"] - vente["glissement_usd"] / position["quantite"]
            enregistrer(vente, avant, cotation, position["sortie_instant"], position, "VENTE")
            _renseigner_resultats(position, vente, cotation)
            if not bloquee(position["sortie_instant"]):
                position["equity_apres_eur"] = etat["EUR"] + etat["USD"] * taux + sum(
                    valeur(autre, position["sortie_instant"], taux) for autre in ouvertes.values())

    positions = []
    for position in candidats:
        issue = position.pop("_issue", None)
        position.update(
            commissions=hypotheses["nom_commissions"], conversion=hypotheses["nom_conversion"],
            scenario_change=hypotheses["scenario_change"], reglement=hypotheses["reglement"],
            glissement_par_action=hypotheses["glissement_par_action"],
            glissement_bps=hypotheses["glissement_bps"], hypotheses_confirmees=HYPOTHESES_CONFIRMEES)
        positions.append(position)
        if position["statut"] is not None:
            continue   # déjà tranché : stop non évaluable ou ouverture sous le stop
        instant = position["entree_instant"]
        encaisser_jusqu_a(instant)
        if bloquee(instant):
            position.update(statut="NON_EVALUABLE", motif="PORTEFEUILLE_NON_EVALUABLE")
            continue
        if position["symbole"] in ouvertes:
            position.update(statut="REFUSEE", motif="POSITION_DEJA_OUVERTE")
            continue
        # Taux de référence : le dernier disponible à l'instant de la décision, jamais un taux postérieur.
        cotation = taux_change(instant)
        if cotation is None:
            position.update(statut="NON_EVALUABLE", motif="TAUX_DE_CHANGE_INDISPONIBLE")
            continue
        taux = cotation["eur_par_usd"]
        reevaluer(taux)
        exposition = sum(valeur(ouverte, instant, taux) for ouverte in ouvertes.values())
        # Valorisation comptable en EUR : les deux soldes et les positions, au taux de référence.
        equity = etat["EUR"] + etat["USD"] * taux + exposition
        reserve = sum(ouverte["risque_prevu_eur"] for ouverte in ouvertes.values())
        # Un achat ne peut être payé qu'avec des fonds disponibles : ni fonds non réglés, ni emprunt.
        utilisables, attendus = disponibles(instant), en_attente(instant)
        taille = calculer_quantite(equity, utilisables, position["entree_prix"], position["stop"],
                                   taux, hypotheses, pas_quantite, reserve, exposition)
        position.update(equity_eur=equity, budget_eur=taille["budget_eur"], risque_reserve_eur=reserve,
                        taux_entree=taux, taux_entree_jour=cotation["jour"],
                        especes_eur_avant=etat["EUR"], especes_usd_avant=etat["USD"],
                        disponible_eur_avant=utilisables["EUR"], disponible_usd_avant=utilisables["USD"],
                        attente_eur_avant=attendus["EUR"], attente_usd_avant=attendus["USD"],
                        contrainte=taille["contrainte"], risque_minimal_eur=taille["risque_minimal_eur"])
        if taille["quantite"] <= 0:
            # Jamais de risque relevé pour rendre l'achat possible. Deux refus distincts :
            # la plus petite quantité dépasse une limite de risque, ou elle ne peut pas être payée.
            limites = taille["contrainte"].split(";")
            risque_en_cause = "BUDGET_RISQUE" in limites or "RISQUE_CUMULE" in limites
            non_financable = "LIQUIDITES" in limites and not risque_en_cause
            position.update(statut="REFUSEE", motif="FONDS_DISPONIBLES_INSUFFISANTS" if non_financable
                            else "PAS_DE_POSITION_TAILLE_INSUFFISANTE")
            continue
        achat = regler_achat(utilisables, taille["quantite"], position["entree_prix"], taux, hypotheses)
        enregistrer(achat, utilisables, cotation, instant, position, "ACHAT")
        position.update(
            quantite=taille["quantite"], montant_usd=taille["quantite"] * position["entree_prix"],
            montant_eur=taille["montant_eur"], conversion_entree_usd=achat["usd_achetes"],
            # Prix réellement payé : plus haut que le prix de la règle, du montant du glissement.
            entree_prix_execute=position["entree_prix"] + achat["glissement_usd"] / taille["quantite"],
            risque_prix_eur=taille["risque_prix_eur"], couts_stop_eur=taille["couts_stop_eur"],
            couts_change_stop_eur=taille["couts_change_stop_eur"],
            risque_prevu_eur=taille["risque_prevu_eur"],
            # Coûts de l'entrée seulement ; ceux de la sortie s'ajoutent à la clôture.
            commissions_eur=achat["commission_usd"] * taux, glissement_eur=achat["glissement_usd"] * taux,
            couts_change_eur=achat["cout_change_eur"], couts_eur=achat["couts_eur"],
        )
        position.update(issue)
        if position["statut"] == "CLOTUREE":
            cotation_sortie = taux_change(position["sortie_instant"])
            if cotation_sortie is None:
                position.update(statut="NON_EVALUABLE", motif="TAUX_DE_CHANGE_INDISPONIBLE",
                                non_evaluable_depuis=position["sortie_instant"])
            else:
                position["_cotation_sortie"] = cotation_sortie
        ouvertes[position["symbole"]] = position
    encaisser_jusqu_a(None)

    limite = max(marche["limite"] for marche in marches)
    cotation_finale = taux_change(limite)
    equity_finale = None
    if not bloquee(None):
        if cotation_finale is not None:
            taux_final = cotation_finale["eur_par_usd"]
            reevaluer(taux_final)
            equity_finale = etat["EUR"] + etat["USD"] * taux_final + sum(
                valeur(position, limite, taux_final) for position in ouvertes.values())
        elif not ouvertes and etat["USD"] == 0:
            equity_finale = etat["EUR"]   # tout est en EUR : aucun taux n'est nécessaire
    utilisables = disponibles(limite)
    return {
        "positions": positions, "conversions": conversions, "capital_depart": capital,
        "usd_depart": usd_depart, "equity_depart_eur": etat["equity_depart"],
        # Solde comptable, puis ce qui est disponible pour un achat et ce qui attend son règlement.
        "especes_eur": etat["EUR"], "especes_usd": etat["USD"],
        "disponible_eur": utilisables["EUR"], "disponible_usd": utilisables["USD"],
        "en_attente": [attente for attente in attentes
                       if attente["disponible_a"] is None or attente["disponible_a"] > limite],
        "taux_final": None if cotation_finale is None else cotation_finale["eur_par_usd"],
        "taux_final_jour": None if cotation_finale is None else cotation_finale["jour"],
        "equity_eur": equity_finale, "effet_change_liquidites_eur": etat["effet_change"],
        "hypotheses": hypotheses, "hypotheses_confirmees": HYPOTHESES_CONFIRMEES,
        "decompte": compter_positions(positions), "pas_quantite": str(pas_quantite), "instant": limite,
    }


# ---------------------------------------------------------------- affichage

def _nombre(valeur, decimales=2, unite=""):
    return "ND" if valeur is None else f"{valeur:.{decimales}f}".replace(".", ",") + unite


def prix_fr(valeur):
    """Écrit un prix sans arrondi trompeur : 344.285 -> « 344,285 » ; 344.29 -> « 344,29 »."""
    if valeur is None:
        return "ND"
    texte = f"{Decimal(str(valeur)).quantize(Decimal('0.0001')).normalize():f}"
    entier, _, decimales = texte.partition(".")
    return f"{entier},{decimales.ljust(2, '0')}"


def _heure(instant):
    return "ND" if instant is None else instant.astimezone(NEW_YORK).strftime("%d/%m/%Y %H:%M")


def reference_fr(jour):
    """Nomme le taux utilisé : « taux de référence BCE du 15/10/2026 », ou « taux fictif »."""
    return "taux fictif" if jour is None else f"taux de référence BCE du {jour.strftime('%d/%m/%Y')}"


def libelle_resultat(hypotheses):
    """Nom du résultat final selon les hypothèses : jamais « net » tant que rien n'est confirmé."""
    return "Résultat brut théorique" if sans_couts(hypotheses) else "Résultat après coûts simulés"


def decrire_position(position, hypotheses=None):
    """Quelques lignes lisibles pour une position, quelle que soit son issue."""
    hypotheses = creer_hypotheses() if hypotheses is None else hypotheses
    lignes = [f"{position['symbole']} — entrée du {_heure(position['entree_instant'])} (New York) à "
              f"{prix_fr(position['entree_prix'])} $ : {position['statut']} ({position['motif']})"]
    if position["stop"] is not None:
        lignes.append(f"  Stop {prix_fr(position['stop'])} $ = plus bas {prix_fr(position['plus_bas'])} "
                      f"− 0,25 × ATR14 {_nombre(position['atr'])} (séance du {position['atr_seance']}), "
                      f"soit {_nombre(position['stop_brut'], 4)} avant arrondi vers le bas")
    if position["cible"] is not None:
        lignes.append(f"  Risque par action {prix_fr(position['distance'])} $ ; objectif "
                      f"{prix_fr(position['cible'])} $ ({prix_fr(position['cible_brute'])} avant arrondi "
                      f"vers le haut, ratio {_nombre(position['ratio_effectif'], 3)}) ; "
                      f"D1 {position['seance_d1']}, D10 {position['seance_d10']}")
    if position["budget_eur"] is not None:
        lignes.append(f"  Equity {_nombre(position['equity_eur'])} EUR ; budget de risque "
                      f"{_nombre(position['budget_eur'])} EUR ; {reference_fr(position['taux_entree_jour'])} : "
                      f"1 EUR = {_nombre(1 / position['taux_entree'], 4)} USD")
    if position["attente_usd_avant"] or position["attente_eur_avant"]:
        lignes.append(f"  Fonds en attente de règlement, non utilisables : "
                      f"{_nombre(position['attente_usd_avant'])} USD et {_nombre(position['attente_eur_avant'])} EUR ; "
                      f"disponibles : {_nombre(position['disponible_usd_avant'])} USD et "
                      f"{_nombre(position['disponible_eur_avant'])} EUR")
    if position["motif"] == "PAS_DE_POSITION_TAILLE_INSUFFISANTE":
        lignes.append(f"  La plus petite quantité risquerait déjà {_nombre(position['risque_minimal_eur'])} EUR "
                      f"(contrainte : {position['contrainte']}).")
    if position["motif"] == "FONDS_DISPONIBLES_INSUFFISANTS":
        lignes.append("  Achat non finançable : les fonds disponibles ne paient pas même la plus petite quantité.")
    if position["quantite"] is not None:
        conversion = ("aucune conversion : payé avec les USD disponibles"
                      if position["conversion_entree_usd"] == 0
                      else f"conversion de {_nombre(position['conversion_entree_usd'])} USD")
        lignes.append(f"  Quantité {_nombre(position['quantite'], 4)} ; investi {_nombre(position['montant_usd'])} USD "
                      f"({_nombre(position['montant_eur'])} EUR) ; {conversion}")
        lignes.append(f"  Risque de prix {_nombre(position['risque_prix_eur'])} EUR + coûts estimés au stop "
                      f"{_nombre(position['couts_stop_eur'])} EUR (dont change "
                      f"{_nombre(position['couts_change_stop_eur'])}) = {_nombre(position['risque_prevu_eur'])} EUR")
    if position["statut"] == "CLOTUREE":
        ambigu = " — AMBIGU_INTRABAR, stop retenu par prudence" if position["ambigu_intrabar"] else ""
        egalite = " — objectif touché sans être dépassé" if position["cible_a_l_egalite"] else ""
        lignes.append(f"  Sortie théorique {position['motif']} à {prix_fr(position['sortie_prix'])} $ le "
                      f"{_heure(position['sortie_instant'])}, séance D{position['seance_detention']}{ambigu}{egalite}")
        lignes.append(f"  Résultat de prix {_nombre(position['brut_eur'])} EUR ({_nombre(position['multiple_r'])} R) ; "
                      f"effet de change {_nombre(position['effet_change_eur'])} EUR ; coûts simulés "
                      f"{_nombre(position['couts_eur'])} EUR (commissions {_nombre(position['commissions_eur'])}, "
                      f"change {_nombre(position['couts_change_eur'])}, glissement {_nombre(position['glissement_eur'])})")
        lignes.append(f"  {libelle_resultat(hypotheses)} : {_nombre(position['apres_couts_eur'])} EUR")
    elif position["statut"] == "OUVERTE":
        lignes.append(f"  Position ouverte, séance D{position['seance_detention']} ; dernier prix "
                      f"{prix_fr(position['dernier_prix'])} $ le {_heure(position['dernier_instant'])}")
    return lignes


def decrire_decompte(decompte):
    """« 3 entrées : 1 CLOTUREE (STOP_GAP), 2 REFUSEE (…) » — tous les cas restent comptés."""
    if not decompte["entrees"]:
        return "Aucune entrée acceptée par l'étape 3 sur la période."
    statuts = ", ".join(f"{nombre} {statut}" for statut, nombre in sorted(decompte["par_statut"].items()))
    motifs = ", ".join(f"{motif} × {nombre}" for motif, nombre in sorted(decompte["par_motif"].items()))
    return (f"{decompte['entrees']} entrée(s) acceptée(s) par l'étape 3 : {statuts}. Motifs : {motifs}. "
            f"Cas AMBIGU_INTRABAR : {decompte['ambigus']} ; objectifs touchés sans dépassement : "
            f"{decompte['cibles_a_l_egalite']}.")


def afficher_portefeuille(resultat):
    hypotheses = resultat["hypotheses"]
    print(f"\nLiquidités de départ : {_nombre(resultat['capital_depart'])} EUR + "
          f"{_nombre(resultat['usd_depart'])} USD ; quantités par pas de {resultat['pas_quantite']}")
    print(f"Hypothèses : {decrire_hypotheses(hypotheses)}.")
    if not resultat["hypotheses_confirmees"]:
        print("ATTENTION : le barème du compte (« Fixed » ou « Tiered ») est inconnu. Ceci est un scénario "
              "de coûts simulés, pas le résultat net du compte.")
    for position in resultat["positions"]:
        print()
        for ligne in decrire_position(position, hypotheses):
            print(ligne)
    print(f"\n{decrire_decompte(resultat['decompte'])}")
    if resultat["conversions"]:
        print("Conversions simulées (taux d'exécution = taux de référence, coût compris) :")
    else:
        print("Conversions simulées : aucune.")
    for conversion in resultat["conversions"]:
        sens = "EUR -> USD" if conversion["sens"] == "EUR_VERS_USD" else "USD -> EUR"
        print(f"  {_heure(conversion['instant'])} {conversion['symbole']} {conversion['operation']} : {sens}, "
              f"{_nombre(conversion['montant_usd'])} USD contre {_nombre(conversion['montant_eur'])} EUR ; "
              f"{reference_fr(conversion['taux_reference_jour'])} : "
              f"{_nombre(conversion['taux_reference'], 5)} EUR par USD, exécution simulée "
              f"{_nombre(conversion['taux_execution'], 5)} ; coût {_nombre(conversion['cout_eur'])} EUR")
    print(f"Solde comptable : {_nombre(resultat['especes_eur'])} EUR + {_nombre(resultat['especes_usd'])} USD ; "
          f"disponible pour un achat : {_nombre(resultat['disponible_eur'])} EUR + "
          f"{_nombre(resultat['disponible_usd'])} USD")
    for attente in resultat["en_attente"]:
        print(f"  En attente de règlement : {_nombre(attente['montant'])} {attente['devise']} "
              f"(vente {attente['symbole']} du {_heure(attente['vente_instant'])}), disponible le "
              f"{_heure(attente['disponible_a'])}")
    print(f"Equity valorisée en EUR : {_nombre(resultat['equity_eur'])} ; effet de change sur les USD "
          f"détenus : {_nombre(resultat['effet_change_liquidites_eur'])} EUR")
    print("Simulation d'un playbook : ni conseil d'achat, ni preuve de rentabilité.")


# ---------------------------------------------------------------- démonstration et programme

def scenario_fictif_sortie():
    """Le scénario fictif de l'étape 3, prolongé jusqu'à un objectif atteint à D3."""
    daily, horaires, ouverture_j3 = scenario_fictif()
    jour_d3 = daily[65]["date"]
    bougies_d3 = [bougie for bougie in horaires if bougie["session"] == jour_d3]
    bougies_d3[3]["high"] = 121.0      # la quatrième bougie de D3 dépasse l'objectif
    daily[65]["high"] = 121.0
    return daily, horaires, bougies_d3[-1]["fin"]


def demonstration():
    print("EXEMPLE FICTIF — aucune donnée de marché, sans coûts, 1 USD = 1 EUR")
    _, stop = calculer_stop(97, 4, "0.01")
    _, cible, ratio = calculer_cible(100, stop, "0.01")
    print(f"Plus bas 97, ATR14 4 -> stop {_nombre(stop)} ; entrée 100 -> risque "
          f"{_nombre(100 - stop)} par action ; objectif {_nombre(cible)} (ratio {_nombre(ratio)})")
    hypotheses = creer_hypotheses()
    for libelle, pas in (("actions entières", PAS_ENTIER), ("fractions", PAS_FRACTION)):
        taille = calculer_quantite(1000, {"EUR": 1000.0, "USD": 0.0}, 100, stop, 1.0, hypotheses, pas)
        print(f"  Capital 1 000 EUR, budget {_nombre(taille['budget_eur'])} EUR, {libelle} : quantité "
              f"{_nombre(taille['quantite'], 4)}, investi {_nombre(taille['montant_eur'])} EUR, "
              f"risque {_nombre(taille['risque_prevu_eur'])} EUR")
    print("\nCHANGE — entrée 100, stop 96, 1 action, conversion manuelle (minimum 2 USD), 1 USD = 1 EUR")
    manuel = creer_hypotheses(conversion="ibkr_manuelle")
    for libelle, especes in (("1 000 EUR, aucun USD", {"EUR": 1000.0, "USD": 0.0}),
                             ("500 USD déjà disponibles", {"EUR": 500.0, "USD": 500.0})):
        achat = regler_achat(especes, 1.0, 100.0, 1.0, manuel)
        print(f"  {libelle} : conversion de {_nombre(achat['usd_achetes'])} USD, coût de change "
              f"{_nombre(achat['cout_change_eur'])} EUR")
    daily, horaires, instant = scenario_fictif_sortie()
    marche = preparer_marche("FICTIF", daily, horaires, instant)
    print("\nSCENARIO FICTIF — sommet 120, creux 100, repli à 112, entrée à l'ouverture de J3")
    return simuler_portefeuille([marche], cotation_fixe(1.0), pas_quantite=PAS_FRACTION)


def main():
    analyseur = argparse.ArgumentParser(description="Sorties et risque selon SPEC_SORTIES_RISQUE.md (simulation).")
    analyseur.add_argument("--demo", action="store_true", help="Exemples fictifs, sans réseau.")
    analyseur.add_argument("--symbole", choices=SYMBOLES, action="append",
                           help="Titre simulé ; répéter l'option pour un portefeuille commun. Défaut : AAPL.")
    analyseur.add_argument("--configuration", choices=sorted(CONFIGURATIONS), action="append",
                           help="Configuration nommée ; répéter l'option pour en comparer plusieurs. "
                                "Défaut : les scénarios du fichier de configuration.")
    analyseur.add_argument("--capital", type=float, help="Liquidités de départ en EUR. Défaut : fichier de configuration.")
    analyseur.add_argument("--usd-depart", type=float, help="USD déjà détenus au départ. Défaut : fichier de configuration.")
    analyseur.add_argument("--commissions", choices=sorted(BAREMES_COMMISSIONS),
                           help="Simulation personnalisée : barème de commissions.")
    analyseur.add_argument("--conversion", choices=sorted(MODES_CONVERSION),
                           help="Simulation personnalisée : coût d'une conversion EUR/USD.")
    analyseur.add_argument("--change", choices=sorted(SCENARIOS_CHANGE),
                           help="Simulation personnalisée : devenir des USD après une vente.")
    analyseur.add_argument("--reglement", choices=sorted(REGLEMENTS),
                           help="Simulation personnalisée : disponibilité du produit d'une vente.")
    analyseur.add_argument("--fractions", action="store_true",
                           help="Simulation personnalisée : autorise les fractions d'action.")
    analyseur.add_argument("--execution", choices=sorted(SCENARIOS_EXECUTION), default="principal",
                           help="Scénario d'exécution des configurations nommées : glissement de 2 points de base "
                                "(principal) ou de 10, avec un jour de règlement de plus (defavorable).")
    analyseur.add_argument("--glissement", type=float, default=0.0,
                           help="Simulation personnalisée : glissement en USD par action (défaut 0).")
    analyseur.add_argument("--glissement-bps", type=float, default=0.0,
                           help="Simulation personnalisée : glissement en points de base du prix (défaut 0).")
    analyseur.add_argument("--jours", type=int, default=45, help="Jours de bougies horaires à rejouer.")
    analyseur.add_argument("--instant", type=instant_utc, help="Instant évalué, ISO avec fuseau ; défaut : maintenant.")
    analyseur.add_argument("--csv-taux", type=Path, help="Archive bce_eurusd_*.csv, pour travailler hors ligne.")
    analyseur.add_argument("--sortie", type=Path, help="Dossier où écrire les journaux. Défaut : resultats/.")
    options = analyseur.parse_args()
    personnalisee = options.fractions or any(valeur is not None for valeur in (
        options.commissions, options.conversion, options.change, options.reglement))
    if personnalisee and options.configuration:
        analyseur.error("Choisis soit --configuration, soit une simulation personnalisée, pas les deux.")
    if options.jours <= 0 or options.glissement < 0 or options.glissement_bps < 0:
        analyseur.error("--jours doit être strictement positif et les glissements positifs ou nuls.")
    try:
        identifiant = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        dossier = options.sortie or DOSSIER_PROJET / "resultats"
        if options.demo:
            resultats, prefixe = {"FICTIF": demonstration()}, "fictif"
        else:
            # Imports tardifs : ces modules utilisent eux-mêmes les fonctions de ce fichier.
            from configuration import lire_configuration
            from etat_du_jour import charger_marche
            from source_bce import archiver_taux, convertisseur, lire_csv_taux, telecharger_taux
            configuration = lire_configuration()
            capital = configuration["capital_eur"] if options.capital is None else options.capital
            usd_depart = configuration["usd_depart"] if options.usd_depart is None else options.usd_depart
            if capital < 0 or usd_depart < 0 or capital + usd_depart <= 0:
                raise ValueError("Liquidités de départ : montants positifs, et somme non nulle.")
            if personnalisee:
                simulations = {"PERSONNALISEE": (creer_hypotheses(
                    options.commissions or "aucun", options.conversion or "sans_cout",
                    options.change or "usd_conserves", options.glissement,
                    options.reglement or "immediat", options.glissement_bps),
                    PAS_FRACTION if options.fractions else PAS_ENTIER)}
            else:
                # Barème inconnu : tous les scénarios du fichier sont calculés, aucun n'est choisi en silence.
                simulations = {nom: configurer(nom, options.execution)
                               for nom in options.configuration or configuration["scenarios"]}
            if options.csv_taux:
                taux = lire_csv_taux(options.csv_taux)
            else:
                taux = telecharger_taux()
                print(f"Archive des taux BCE : {archiver_taux(taux, identifiant)}")
            marches = []
            for symbole in options.symbole or ["AAPL"]:
                donnees = charger_marche(symbole, options.instant, jours_horaire=options.jours)
                marches.append(preparer_marche(symbole, donnees["daily"], donnees["horaires"],
                                               donnees["instant"], donnees["debut"]))
            # Mêmes règles et mêmes données pour chaque scénario : seuls les coûts changent.
            resultats = {nom: simuler_portefeuille(marches, convertisseur(taux), capital, hypotheses, pas, usd_depart)
                         for nom, (hypotheses, pas) in simulations.items()}
            prefixe = "_".join(marche["symbole"].lower() for marche in marches)
            print(f"Instant évalué : {_heure(marches[0]['limite'])} (New York) ; {options.jours} jours de "
                  f"bougies horaires ; configuration lue dans {configuration['fichier']} ; "
                  "valorisation au taux de référence BCE (pas un taux d'exécution).")
        for nom, resultat in resultats.items():
            print(f"\n{'=' * 20} SCÉNARIO DE COÛTS SIMULÉS : {nom} {'=' * 20}")
            afficher_portefeuille(resultat)
            base = f"{prefixe}_{nom.lower()}"
            if resultat["positions"]:
                sortie = dossier / f"{base}_positions_{identifiant}.csv"
                ecrire_csv(sortie, [{champ: position[champ] for champ in CHAMPS_POSITION}
                                    for position in deepcopy(resultat["positions"])], CHAMPS_POSITION)
                print(f"Journal des positions : {sortie}")
            if resultat["conversions"]:
                conversions = dossier / f"{base}_conversions_{identifiant}.csv"
                ecrire_csv(conversions, resultat["conversions"], CHAMPS_CONVERSION)
                print(f"Journal des conversions : {conversions}")
        return 0
    except (ValueError, OSError, KeyError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
