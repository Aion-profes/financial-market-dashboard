"""État du jour : pour chaque titre, les conditions d'entrée sont-elles remplies ?

Ce module n'ajoute aucune règle. Il lance les étapes 1 à 3 sur les données les
plus récentes et résume leur résultat en quelques lignes lisibles.
« Conditions remplies » décrit les règles du playbook : ce n'est pas un conseil d'achat.
"""

import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from etape_01_tendance import (
    MINIMUM_CLOTURES, SYMBOLES, construire_tableau, verifier_seances_nasdaq,
)
from etape_02_pullback import (
    DERNIERE_SEANCE_ADMISSIBLE, FACTEUR_SEUIL_SMA20, PREMIERE_SEANCE_ADMISSIBLE,
    RETRACEMENT_MAXIMUM, scanner_pullbacks,
)
from etape_03_entree_1h import (
    construire_grille, instant_utc, normaliser_horaires, scanner_entrees,
)
from etape_04_sorties_risque import plan_en_attente, preparer_marche, prix_fr
from source_alpaca import (
    JOURS_HISTORIQUE, RETARD_TOTAL, barres_en_daily, jour_de_barre,
    telecharger_barres_daily, telecharger_horaire,
)


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc
# Profondeur des bougies 1 h. Une position entrée à J10 et tenue dix séances se termine
# dix-sept séances après la confirmation J2, soit près de quatre semaines : 45 jours laissent de la marge.
JOURS_HORAIRE = 45

# États possibles d'une condition.
REMPLIE = "REMPLIE"
NON_REMPLIE = "NON_REMPLIE"
EN_ATTENTE = "EN_ATTENTE"
INCONNUE = "INCONNUE"
SANS_OBJET = "SANS_OBJET"

# Verdicts possibles pour un titre, avec leur libellé affiché.
VERDICTS = {
    "CONDITIONS_REMPLIES": "Conditions remplies",
    "ENTREE_SIMULEE": "Entrée simulée",
    "EN_ATTENTE": "En attente",
    "NON_REMPLIES": "Conditions non remplies",
    "NON_EVALUABLE": "Non évaluable",
}

# Traduction des motifs techniques écrits par les étapes 2 et 3.
MOTIFS = {
    "NOUVEAU_HIGH": "un nouveau plus haut a dépassé le sommet",
    "RETRACEMENT_SUPERIEUR_50": "le repli a dépassé 50 % de la hausse",
    "LOW_SOUS_SMA20_PRECEDENTE": "un plus bas est passé à plus de 4 % sous la SMA20",
    "TENDANCE_INTERROMPUE": "la tendance Daily s'est interrompue",
    "OUVERTURE_APRES_J10": "la fenêtre J3–J10 est dépassée",
    "AUCUN_SOMMET_CONFIRME": "aucun sommet de référence n'est confirmé",
    "DAILY_REQUIS_INDISPONIBLE": "la bougie Daily nécessaire n'est pas encore disponible",
    "HISTORIQUE_HORAIRE_INCOMPLET_DEPUIS_J2": "l'historique horaire ne couvre pas toute la configuration",
    "OHLC_HORAIRE_INCOMPLET": "la dernière bougie horaire n'est pas encore complète",
    "BOUGIE_HORAIRE_PAS_ENCORE_DISPONIBLE": "la dernière bougie horaire n'est pas encore disponible",
    "BOUGIE_OU_REFERENCE_HORAIRE_MANQUANTE": "une bougie horaire nécessaire manque",
    "REFERENCE_FIN_J2_MANQUANTE": "la bougie horaire de référence de J2 manque",
    "REFERENCE_HORAIRE_PAS_ENCORE_DISPONIBLE": "la bougie horaire de référence n'est pas encore disponible",
    "OPEN_SUIVANT_INDISPONIBLE": "le prix d'ouverture attendu n'a pas été reçu",
    "SIGNAL_DISPONIBLE_APRES_OUVERTURE": "le signal a été connu après l'ouverture prévue",
    "CREUX_REFERENCE_ABSENT": "aucun creux de référence ne précède le sommet",
    "HAUSSE_NON_POSITIVE": "le sommet n'est pas au-dessus du creux de référence",
    "SMA20_INDISPONIBLE": "la SMA20 n'est pas encore calculable",
    "TENDANCE_INDISPONIBLE": "la tendance n'est pas encore calculable",
    "TENTATIVE_UNIQUE_DEJA_UTILISEE": "la tentative unique de cette configuration est déjà utilisée",
    # Motifs du journal des positions (étape 4).
    "STOP": "stop touché",
    "STOP_GAP": "ouverture sous le stop (gap)",
    "CIBLE": "objectif atteint",
    "CIBLE_GAP": "ouverture au-dessus de l'objectif",
    "DUREE_MAX_D10": "durée maximale atteinte, sortie à la clôture de D10",
    "POSITION_OUVERTE_FIN_DONNEES": "position toujours ouverte",
    "ENTREE_SOUS_STOP": "ouverture au niveau du stop ou en dessous",
    "POSITION_DEJA_OUVERTE": "une position était déjà ouverte sur ce titre",
    "PAS_DE_POSITION_TAILLE_INSUFFISANTE": "même la plus petite quantité dépasse une limite de risque",
    "FONDS_DISPONIBLES_INSUFFISANTS": "achat non finançable : les fonds disponibles ne suffisent pas",
    "PLUS_BAS_INDISPONIBLE": "le plus bas du pullback n'est pas connu",
    "ATR_INDISPONIBLE": "l'ATR14 n'est pas calculable",
    "STOP_NON_POSITIF": "le stop calculé n'est pas un prix positif",
    "TAUX_DE_CHANGE_INDISPONIBLE": "aucun taux de change EUR/USD récent",
    "BOUGIE_HORAIRE_MANQUANTE": "une bougie horaire manque pendant la détention",
    "CLOTURE_D10_MANQUANTE": "le cours de clôture de D10 manque",
    "PORTEFEUILLE_NON_EVALUABLE": "une position précédente n'est pas évaluable",
    "BUDGET_RISQUE": "budget de risque par position",
    "RISQUE_CUMULE": "risque cumulé de 1 %",
    "LIQUIDITES": "liquidités disponibles",
    "EXPOSITION": "exposition maximale",
}


def expliquer_motif(motif):
    """Remplace chaque code de motif par une phrase ; garde le code s'il est inconnu."""
    codes = [code for code in (motif or "").replace(";", ",").split(",") if code]
    return " ; ".join(MOTIFS.get(code, code) for code in codes)


def nombre_fr(valeur, decimales=2):
    """344.285 -> « 344,29 ». Sert uniquement à l'affichage ; pour un prix d'exécution, voir prix_fr."""
    return "ND" if valeur is None else f"{valeur:.{decimales}f}".replace(".", ",")


def date_fr(jour):
    return "ND" if jour is None else jour.strftime("%d/%m/%Y")


def heure_new_york(instant):
    return instant.astimezone(NEW_YORK).strftime("%d/%m/%Y %H:%M")


def charger_marche(symbole, instant=None, maintenant=None, jours_horaire=JOURS_HORAIRE):
    """Télécharge chez Alpaca le Daily (avec son Open) et l'horaire d'un titre.

    instant : moment à résumer ; par défaut maintenant. Un instant passé rejoue
    l'histoire : rien de postérieur n'est utilisé. « maintenant » ne sert qu'à
    respecter le retard imposé par Alpaca (et aux tests). jours_horaire : nombre
    de jours de bougies 1 h à charger avant l'instant.
    """
    maintenant = datetime.now(UTC) if maintenant is None else instant_utc(maintenant)
    limite = maintenant if instant is None else instant_utc(instant)
    if limite > maintenant:
        raise ValueError("L'instant demandé est dans le futur.")
    jour = limite.astimezone(NEW_YORK).date()
    debut = jour - timedelta(days=jours_horaire)
    grille = construire_grille(jour - timedelta(days=400), jour + timedelta(days=10))
    barres = telecharger_barres_daily(jour - timedelta(days=JOURS_HISTORIQUE), jour, maintenant, symbole)
    ouvertures = {jour_de_barre(barre): float(barre["o"]) for barre in barres}
    daily = [dict(bougie, ouverture=ouvertures[bougie["date"]]) for bougie in barres_en_daily(barres)]
    # Comme aux étapes 1 et 2 : une séance manquante est refusée, jamais comblée.
    verifier_seances_nasdaq([(bougie["date"], bougie["cloture"]) for bougie in daily])
    creneaux = [ligne for ligne in grille if ligne["session"] >= debut and ligne["debut"] <= limite]
    horaires, incomplets, _, _ = telecharger_horaire(
        creneaux[0]["debut"], creneaux[-1]["fin"], grille, maintenant, symbole, limite)
    return {"symbole": symbole, "instant": limite, "debut": debut,
            "daily": daily, "horaires": horaires, "creneaux_incomplets": incomplets,
            "donnees_jusqu_a": min(limite, maintenant - RETARD_TOTAL)}


def _condition_tendance(tendances):
    """Étape 1 : les quatre comparaisons sur la dernière séance terminée."""
    ligne = tendances[-1]
    comparaisons = [
        ("Clôture > SMA50", "cloture", "sma50", "c1"),
        ("SMA20 > SMA50", "sma20", "sma50", "c2"),
        ("SMA20 en hausse sur 5 séances", "sma20", "sma20_avant_5", "c3"),
        ("SMA50 en hausse sur 5 séances", "sma50", "sma50_avant_5", "c4"),
    ]
    details = [{"nom": nom, "gauche": ligne[gauche], "droite": ligne[droite], "ok": ligne[resultat]}
               for nom, gauche, droite, resultat in comparaisons]
    if ligne["admissible"] is None:
        etat, texte = INCONNUE, "Historique insuffisant pour calculer les moyennes."
    else:
        vraies = sum(detail["ok"] is True for detail in details)
        etat = REMPLIE if ligne["admissible"] else NON_REMPLIE
        accord = "comparaison vraie" if vraies == 1 else "comparaisons vraies"
        texte = f"{vraies} {accord} sur 4 à la clôture du {date_fr(ligne['date'])}."
    return {"nom": "Tendance Daily", "etat": etat, "detail": texte, "comparaisons": details}


def _configuration(derniere, pullbacks, connus, horaires, sessions):
    """Niveaux de la dernière configuration suivie : sommet, creux, repli, fenêtre."""
    date_sommet = derniere["date_sommet"]
    bilans = [ligne for ligne in pullbacks if ligne["date_sommet"] == date_sommet]
    if date_sommet is None or not bilans:
        return None
    bilan = bilans[-1]
    sommet, creux, plus_bas = bilan["sommet"], bilan["creux_reference"], bilan["plus_bas_repli"]
    if bilan["date"] == connus[-1]["date"]:
        # Configuration encore suivie : on ajoute les prix déjà vus depuis la dernière clôture.
        recents = [bougie[champ] for bougie in horaires if bougie["session"] > bilan["date"]
                   for champ in ("ouverture", "low") if bougie[champ] is not None]
        plus_bas = min([plus_bas] + recents)
    limite_50 = retracement = None
    if creux is not None and sommet > creux:
        limite_50 = sommet - RETRACEMENT_MAXIMUM * (sommet - creux)
        retracement = (sommet - plus_bas) / (sommet - creux)
    rang = sessions.index(date_sommet)

    def seance(decalage):
        return sessions[rang + decalage] if rang + decalage < len(sessions) else None

    return {
        "date_sommet": date_sommet, "date_confirmation": bilan["date_confirmation_sommet"],
        "sommet": sommet, "date_creux": bilan["date_creux"], "creux_reference": creux,
        "plus_bas_repli": plus_bas, "retracement": retracement, "limite_50": limite_50,
        "age_seances": derniere["age_seances"],
        "fenetre_debut": seance(PREMIERE_SEANCE_ADMISSIBLE),
        "fenetre_fin": seance(DERNIERE_SEANCE_ADMISSIBLE),
        # Les séances J0 à J10, y compris celles qui n'ont pas encore eu lieu.
        "seances": sessions[rang:rang + DERNIERE_SEANCE_ADMISSIBLE + 1],
    }


def _signal_et_entree(journal, date_sommet):
    """Retrouve dans le journal le signal, l'entrée et l'annulation de cette configuration."""
    signal = entree = annulation = None
    for ligne in journal:
        if date_sommet is None or ligne["date_sommet"] != date_sommet:
            continue
        if ligne["signal_horaire"] is True:
            signal = {"debut": ligne["signal_debut"], "fin": ligne["signal_fin"],
                      "cloture": ligne["cloture_signal"], "high_precedent": ligne["high_precedent"],
                      "ouverture_attendue": ligne["ouverture_attendue"]}
        if ligne["statut"] == "ENTREE_ACCEPTEE":
            entree = {"instant": ligne["instant"], "prix": ligne["prix_entree"],
                      "session": ligne["session"]}
        if ligne["statut"] == "ENTREE_ANNULEE":
            annulation = ligne["motif"]
    return signal, entree, annulation


def _condition_pullback(statut, motif, configuration, entree):
    """Étape 2, vue depuis le dernier événement du journal horaire."""
    nom = "Pullback Daily"
    if configuration is None:
        if statut == "NON_EVALUABLE":
            return {"nom": nom, "etat": INCONNUE, "detail": expliquer_motif(motif).capitalize() + "."}
        return {"nom": nom, "etat": NON_REMPLIE, "detail": "Aucun sommet de référence confirmé."}
    sommet = f"Sommet du {date_fr(configuration['date_sommet'])}"
    age = configuration["age_seances"]
    repli = ""
    if configuration["retracement"] is not None:
        repli = f" ; repli de {nombre_fr(100 * configuration['retracement'], 1)} % (limite 50 %)"
    if entree is not None:
        return {"nom": nom, "etat": REMPLIE,
                "detail": f"{sommet} : critères respectés au moment de l'entrée."}
    if statut == "INVALIDE":
        return {"nom": nom, "etat": NON_REMPLIE,
                "detail": f"{sommet} invalidé : {expliquer_motif(motif)}."}
    if statut == "EXPIREE":
        return {"nom": nom, "etat": NON_REMPLIE,
                "detail": f"{sommet} : J{age}, la fenêtre J3–J10 est dépassée."}
    if statut == "NON_EVALUABLE":
        return {"nom": nom, "etat": INCONNUE, "detail": f"{sommet} : {expliquer_motif(motif)}."}
    if statut == "ATTENTE_J3":
        return {"nom": nom, "etat": EN_ATTENTE,
                "detail": f"{sommet} confirmé, J{age} : entrée possible à partir de J3{repli}."}
    if statut in ("ENTREE_ANNULEE", "SANS_REARMEMENT"):
        return {"nom": nom, "etat": NON_REMPLIE,
                "detail": f"{sommet} : tentative d'entrée déjà utilisée ({expliquer_motif(motif)})."}
    if age is not None and age < PREMIERE_SEANCE_ADMISSIBLE:
        # Clôture de J2 : les critères sont vérifiés, l'entrée reste réservée à J3.
        return {"nom": nom, "etat": REMPLIE,
                "detail": f"{sommet} confirmé, J{age} : critères respectés, entrée possible dès l'ouverture de J3{repli}."}
    return {"nom": nom, "etat": REMPLIE, "detail": f"{sommet} : J{age} dans la fenêtre J3–J10{repli}."}


def _condition_declencheur(signal, pullback):
    """Étape 3 : une clôture horaire strictement au-dessus du plus haut précédent."""
    nom = "Déclencheur 1 h"
    if signal is not None:
        return {"nom": nom, "etat": REMPLIE, "detail": (
            f"Bougie du {heure_new_york(signal['debut'])} (New York) : clôture "
            f"{nombre_fr(signal['cloture'])} > plus haut précédent {nombre_fr(signal['high_precedent'])}.")}
    if pullback["etat"] == REMPLIE:
        return {"nom": nom, "etat": EN_ATTENTE,
                "detail": "Aucune clôture horaire au-dessus du plus haut précédent pour l'instant."}
    return {"nom": nom, "etat": SANS_OBJET,
            "detail": "Sans objet tant que le pullback n'est pas rempli."}


def _verdict(statut, motif, signal, entree, annulation):
    """Une étiquette et une phrase pour le titre, d'après le dernier événement du journal."""
    if entree is not None:
        return "ENTREE_SIMULEE", (
            f"Entrée simulée le {heure_new_york(entree['instant'])} (New York) à "
            f"{prix_fr(entree['prix'])} $. Stop, objectif et taille : voir la position simulée.")
    if statut in ("SIGNAL", "ATTENTE_OUVERTURE") and signal is not None:
        return "CONDITIONS_REMPLIES", (
            "Tendance, pullback et déclencheur sont remplis : entrée simulée prévue à l'ouverture "
            f"du {heure_new_york(signal['ouverture_attendue'])} (New York).")
    if statut in ("ENTREE_ANNULEE", "SANS_REARMEMENT"):
        cause = expliquer_motif(annulation or motif)
        return "NON_REMPLIES", f"La tentative d'entrée de cette configuration est déjà utilisée : {cause}."
    if statut in ("ATTENTE_SIGNAL", "PAS_DE_SIGNAL"):
        return "EN_ATTENTE", "Tendance et pullback sont remplis ; il manque le déclencheur 1 h."
    if statut == "ATTENTE_J3":
        return "EN_ATTENTE", "Un sommet de référence est confirmé ; l'entrée n'est possible qu'à partir de J3."
    if statut == "AUCUNE_CONFIGURATION":
        return "NON_REMPLIES", "Aucune configuration de pullback n'est en cours."
    if statut == "INVALIDE":
        return "NON_REMPLIES", f"La configuration est invalidée : {expliquer_motif(motif)}."
    if statut == "EXPIREE":
        return "NON_REMPLIES", "La dernière configuration est terminée : la fenêtre J3–J10 est dépassée."
    return "NON_EVALUABLE", f"Décision impossible pour l'instant : {expliquer_motif(motif) or statut}."


def _dernier_prix(horaires, connus):
    """Prix le plus récent déjà connu, comparé à la clôture de la séance précédente."""
    candidats = []
    for bougie in horaires:
        if bougie["cloture"] is not None:
            candidats.append((bougie["fin"], bougie["cloture"]))
        elif bougie["ouverture"] is not None:
            candidats.append((bougie["debut"], bougie["ouverture"]))
    if not candidats:
        return None
    instant, valeur = max(candidats)
    # À 16:00 pile, le prix appartient encore à la séance qui se termine.
    session = (instant - timedelta(seconds=1)).astimezone(NEW_YORK).date()
    precedentes = [bougie["cloture"] for bougie in connus if bougie["date"] < session]
    reference = precedentes[-1] if precedentes else None
    variation = None if reference is None else valeur / reference - 1
    return {"valeur": valeur, "instant": instant, "reference": reference, "variation": variation}


def resumer(symbole, daily, horaires, instant, debut=None):
    """Résume un titre à un instant donné, sans rien lire de postérieur à cet instant."""
    limite = instant_utc(instant)
    etat = {
        "symbole": symbole, "instant": limite, "verdict": "NON_EVALUABLE", "phrase": "",
        "conditions": [], "configuration": None, "signal": None, "entree": None,
        "prix": None, "seuil_sma20": None, "marche": None, "plan_en_attente": None,
        "daily": [], "tendances": [], "pullbacks": [], "horaires": [], "journal": [],
    }
    if not daily:
        etat["phrase"] = "Aucune bougie Daily reçue."
        return etat
    jour = limite.astimezone(NEW_YORK).date()
    # Trois semaines d'avance : de quoi dater J10 même pour un sommet tout juste confirmé.
    grille = construire_grille(min(bougie["date"] for bougie in daily), jour + timedelta(days=21))
    fins = {ligne["session"]: ligne["fin"] for ligne in grille}
    sessions = sorted(fins)
    # Seules les séances terminées à cet instant comptent : pas de bougie Daily partielle.
    connus = sorted((bougie for bougie in daily
                     if bougie["date"] in fins and fins[bougie["date"]] <= limite),
                    key=lambda bougie: bougie["date"])
    etat["daily"] = connus
    etat["horaires"] = normaliser_horaires(horaires, limite, grille)
    etat["prix"] = _dernier_prix(etat["horaires"], connus)
    if len(connus) < MINIMUM_CLOTURES:
        etat["phrase"] = (f"Historique Daily insuffisant : {len(connus)} séances terminées, "
                          f"{MINIMUM_CLOTURES} nécessaires.")
        return etat
    etat["tendances"] = construire_tableau([(bougie["date"], bougie["cloture"]) for bougie in connus])
    etat["pullbacks"] = scanner_pullbacks(connus)
    etat["seuil_sma20"] = FACTEUR_SEUIL_SMA20 * etat["tendances"][-1]["sma20"]
    etat["journal"] = scanner_entrees(daily, horaires, limite, debut)
    # Étape 4 : de quoi calculer stops, objectifs et sorties à partir de ce même journal.
    etat["marche"] = preparer_marche(symbole, daily, horaires, limite, debut,
                                     journal=etat["journal"], grille=grille)
    etat["plan_en_attente"] = plan_en_attente(etat["marche"])
    tendance = _condition_tendance(etat["tendances"])
    if not etat["journal"]:
        etat["conditions"] = [tendance]
        etat["phrase"] = "Aucun événement horaire dans la période analysée."
        return etat
    derniere = etat["journal"][-1]
    statut, motif = derniere["statut"], derniere["motif"]
    configuration = _configuration(derniere, etat["pullbacks"], connus, etat["horaires"], sessions)
    signal, entree, annulation = _signal_et_entree(etat["journal"], derniere["date_sommet"])
    pullback = _condition_pullback(statut, motif, configuration, entree)
    etat["conditions"] = [tendance, pullback, _condition_declencheur(signal, pullback)]
    etat["configuration"], etat["signal"], etat["entree"] = configuration, signal, entree
    etat["verdict"], etat["phrase"] = _verdict(statut, motif, signal, entree, annulation)
    return etat


def etat_du_titre(symbole, instant=None, maintenant=None):
    """Télécharge puis résume un titre : la fonction qu'utilise le tableau de bord."""
    marche = charger_marche(symbole, instant, maintenant)
    etat = resumer(symbole, marche["daily"], marche["horaires"], marche["instant"], marche["debut"])
    etat["creneaux_incomplets"] = marche["creneaux_incomplets"]
    etat["donnees_jusqu_a"] = marche["donnees_jusqu_a"]
    return etat


SYMBOLES_ETATS = {REMPLIE: "[OUI]", NON_REMPLIE: "[NON]", EN_ATTENTE: "[...]",
                  INCONNUE: "[ ? ]", SANS_OBJET: "[ - ]"}


def afficher_etat(etat):
    """Version terminal : le verdict, la phrase, puis une ligne par condition."""
    prix = etat["prix"]
    cours = "prix ND"
    if prix is not None:
        variation = "" if prix["variation"] is None else f" ({100 * prix['variation']:+.2f} %)".replace(".", ",")
        cours = f"{nombre_fr(prix['valeur'])} ${variation} au {heure_new_york(prix['instant'])} New York"
    print(f"\n{etat['symbole']} — {VERDICTS[etat['verdict']].upper()} — {cours}")
    print(f"  {etat['phrase']}")
    for condition in etat["conditions"]:
        print(f"  {SYMBOLES_ETATS[condition['etat']]} {condition['nom']} : {condition['detail']}")
    configuration = etat["configuration"]
    if configuration is not None and configuration["limite_50"] is not None:
        print(f"        Sommet {nombre_fr(configuration['sommet'])} | creux {nombre_fr(configuration['creux_reference'])}"
              f" | plus bas du repli {nombre_fr(configuration['plus_bas_repli'])}"
              f" | limite 50 % {nombre_fr(configuration['limite_50'])}")


def main():
    analyseur = argparse.ArgumentParser(description="État du jour des titres suivis (données Alpaca).")
    analyseur.add_argument("--symbole", choices=SYMBOLES, action="append",
                           help="Titre à résumer ; répéter l'option pour plusieurs. Par défaut : tous.")
    options = analyseur.parse_args()
    print("ETAT DU JOUR — simulation d'un playbook, pas un conseil d'achat.")
    print("Alpaca gratuit : les 16 dernières minutes ne sont pas encore visibles.")
    code = 0
    for symbole in options.symbole or SYMBOLES:
        try:
            afficher_etat(etat_du_titre(symbole))
        except (ValueError, OSError) as erreur:
            print(f"\n{symbole} — ERREUR : {erreur}")
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
