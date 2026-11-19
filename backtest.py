"""Backtest sur une période figée : simulations depuis l'archive, puis mesures décidées à l'avance.

Ce programme applique le protocole de SPEC_SORTIES_RISQUE.md (section 15). Il ne cherche
aucun paramètre : il mesure la V1 telle qu'elle est écrite, dans chaque scénario de coûts
et d'exécution. Les périodes viennent de historique.PERIODES et ne se modifient pas.

Lancer :  python backtest.py --periode developpement
La période de validation ne se lit qu'une fois : elle exige l'option --ouvrir-la-validation.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from statistics import mean, stdev

from etape_01_tendance import DOSSIER_PROJET, SYMBOLES, ecrire_csv
from etape_03_entree_1h import construire_grille
from etape_04_sorties_risque import (
    CAPITAL_DEPART, CHAMPS_CONVERSION, CHAMPS_POSITION, SCENARIOS_DE_COUTS, SCENARIOS_EXECUTION,
    compter_positions, configurer, decrire_hypotheses, preparer_marche, simuler_portefeuille,
)
from historique import ARCHIVE_FIN, DOSSIER, PERIODES, preparer_historique
from source_bce import convertisseur, lire_csv_taux


UTC = timezone.utc
# Taux BCE figés : l'archive téléchargée le 15 novembre 2026, qui va jusqu'au 13 novembre.
TAUX_FIGES = DOSSIER_PROJET / "donnees" / "bce_eurusd_20261115_024314_370946.csv"
PERIODES_MESUREES = ("developpement", "validation")


def serie_de_pertes(resultats):
    """Plus longue suite de résultats négatifs consécutifs."""
    plus_longue = courante = 0
    for resultat in resultats:
        courante = courante + 1 if resultat < 0 else 0
        plus_longue = max(plus_longue, courante)
    return plus_longue


def drawdown_maximal(resultats, depart):
    """Plus forte baisse entre un sommet du capital et un creux qui le suit, en EUR et en %."""
    capital = sommet = depart
    pire_eur = pire_part = 0.0
    for resultat in resultats:
        capital += resultat
        sommet = max(sommet, capital)
        if sommet - capital > pire_eur:
            pire_eur, pire_part = sommet - capital, (sommet - capital) / sommet
    return pire_eur, pire_part


def mesurer(positions, capital=CAPITAL_DEPART):
    """Les mesures du protocole, pour un journal de positions. Aucun cas n'est retiré des comptes.

    Les résultats sont ceux des positions clôturées, dans l'ordre de leur sortie.
    L'intervalle d'incertitude est approximatif (moyenne ± 1,96 erreur type) : il suppose
    des positions indépendantes et n'a de sens qu'avec quelques dizaines de positions.
    """
    cloturees = sorted((position for position in positions if position["statut"] == "CLOTUREE"),
                       key=lambda position: position["sortie_instant"])
    resultats = [position["apres_couts_eur"] for position in cloturees]
    mesures = {
        "decompte": compter_positions(positions), "positions_cloturees": len(cloturees),
        "positions_ouvertes": sum(position["statut"] == "OUVERTE" for position in positions),
        "positions_reduites_faute_de_fonds": sum(
            position["quantite"] is not None and "LIQUIDITES" in (position["contrainte"] or "")
            for position in positions),
        "achats_avec_conversion": sum(bool(position["conversion_entree_usd"]) for position in positions),
        "esperance_eur": None, "intervalle_eur": None, "esperance_r": None, "part_gagnantes": None,
        "pire_resultat_eur": None, "serie_de_pertes": 0, "drawdown_eur": 0.0, "drawdown_part": 0.0,
        "couts_sur_risque": None, "detention_moyenne_seances": None,
        "somme_prix_eur": 0.0, "somme_change_eur": 0.0, "somme_couts_eur": 0.0, "somme_resultats_eur": 0.0,
    }
    if not cloturees:
        return mesures
    esperance = mean(resultats)
    if len(resultats) >= 2:
        marge = 1.96 * stdev(resultats) / len(resultats) ** 0.5
        mesures["intervalle_eur"] = (esperance - marge, esperance + marge)
    drawdown_eur, drawdown_part = drawdown_maximal(resultats, capital)
    risque = sum(position["risque_prix_eur"] for position in cloturees)
    mesures.update(
        esperance_eur=esperance,
        esperance_r=mean(position["multiple_r_apres_couts"] for position in cloturees),
        part_gagnantes=sum(resultat > 0 for resultat in resultats) / len(resultats),
        pire_resultat_eur=min(resultats), serie_de_pertes=serie_de_pertes(resultats),
        drawdown_eur=drawdown_eur, drawdown_part=drawdown_part,
        couts_sur_risque=sum(position["couts_eur"] for position in cloturees) / risque if risque else None,
        detention_moyenne_seances=mean(position["seance_detention"] for position in cloturees),
        somme_prix_eur=sum(position["brut_eur"] for position in cloturees),
        somme_change_eur=sum(position["effet_change_eur"] for position in cloturees),
        somme_couts_eur=sum(position["couts_eur"] for position in cloturees),
        somme_resultats_eur=sum(resultats),
    )
    return mesures


def garder_la_periode(positions, nom):
    """Une position appartient à la période de son entrée ; les autres ne sont pas mesurées."""
    debut, fin = PERIODES[nom]
    return [position for position in positions if debut <= position["seance_d1"] <= fin]


def instant_de_fin(nom):
    """Clôture d'une séance située un mois après la période : de quoi dénouer les dernières positions."""
    limite = min(PERIODES[nom][1] + timedelta(days=30), ARCHIVE_FIN)
    return construire_grille(limite - timedelta(days=10), limite)[-1]["fin"]


def marches_de_la_periode(nom, dossier=DOSSIER):
    """Les trois titres, lus dans l'archive figée ; l'analyse horaire commence au début de la période."""
    instant = instant_de_fin(nom)
    marches, corrections = [], {}
    for symbole in SYMBOLES:
        historique = preparer_historique(symbole, instant, dossier)
        corrections[symbole] = historique["corrections"]
        marches.append(preparer_marche(symbole, historique["daily"], historique["horaires"], instant,
                                       PERIODES[nom][0], divisions=historique["divisions"]))
    return marches, corrections


def simulations_du_protocole():
    """Deux scénarios de coûts × deux scénarios d'exécution, plus le résultat brut théorique."""
    simulations = {f"{nom}__{execution}": configurer(nom, execution)
                   for nom in SCENARIOS_DE_COUTS for execution in SCENARIOS_EXECUTION}
    simulations["THEORIQUE_SANS_COUTS"] = configurer("THEORIQUE_SANS_COUTS")
    return simulations


def executer(nom, taux, capital=CAPITAL_DEPART, dossier=DOSSIER):
    """Lance toutes les simulations du protocole sur une période. Renvoie {simulation: résultat}."""
    marches, corrections = marches_de_la_periode(nom, dossier)
    resultats = {}
    for simulation, (hypotheses, pas) in simulations_du_protocole().items():
        portefeuille = simuler_portefeuille(marches, convertisseur(taux), capital, hypotheses, pas)
        positions = garder_la_periode(portefeuille["positions"], nom)
        resultats[simulation] = {"positions": positions, "mesures": mesurer(positions, capital),
                                 "hypotheses": decrire_hypotheses(hypotheses),
                                 "conversions": [conversion for conversion in portefeuille["conversions"]
                                                 if conversion["instant"] <= instant_de_fin(nom)]}
    return resultats, corrections


def _nombre(valeur, decimales=2):
    return "ND" if valeur is None else f"{valeur:.{decimales}f}".replace(".", ",")


def afficher(simulation, resultat):
    mesures, decompte = resultat["mesures"], resultat["mesures"]["decompte"]
    print(f"\n=== {simulation} ===\n{resultat['hypotheses']}")
    print(f"Entrées : {decompte['entrees']} ; par statut : {decompte['par_statut']} ; par motif : {decompte['par_motif']}")
    print(f"Cas ambigus : {decompte['ambigus']} ; objectifs touchés sans dépassement : {decompte['cibles_a_l_egalite']} ; "
          f"positions réduites faute de fonds : {mesures['positions_reduites_faute_de_fonds']} ; "
          f"encore ouvertes : {mesures['positions_ouvertes']}")
    if not mesures["positions_cloturees"]:
        print("Aucune position clôturée : aucune mesure de résultat.")
        return
    intervalle = mesures["intervalle_eur"]
    print(f"Positions clôturées : {mesures['positions_cloturees']} ; espérance par position "
          f"{_nombre(mesures['esperance_eur'])} EUR ({_nombre(mesures['esperance_r'])} R)"
          + (f", intervalle approximatif {_nombre(intervalle[0])} à {_nombre(intervalle[1])} EUR" if intervalle else ""))
    print(f"Part de positions gagnantes : {_nombre(100 * mesures['part_gagnantes'], 1)} % ; pire résultat "
          f"{_nombre(mesures['pire_resultat_eur'])} EUR ; plus longue série de pertes {mesures['serie_de_pertes']} ; "
          f"drawdown maximal {_nombre(mesures['drawdown_eur'])} EUR ({_nombre(100 * mesures['drawdown_part'], 1)} %)")
    print(f"Sommes : prix {_nombre(mesures['somme_prix_eur'])} EUR ; change {_nombre(mesures['somme_change_eur'])} EUR ; "
          f"coûts simulés {_nombre(mesures['somme_couts_eur'])} EUR ; résultat {_nombre(mesures['somme_resultats_eur'])} EUR ; "
          f"coûts rapportés au risque {_nombre(mesures['couts_sur_risque'])} ; détention moyenne "
          f"{_nombre(mesures['detention_moyenne_seances'], 1)} séances")


def main():
    analyseur = argparse.ArgumentParser(description="Backtest du protocole sur une période figée (aucune optimisation).")
    analyseur.add_argument("--periode", choices=PERIODES_MESUREES, required=True)
    analyseur.add_argument("--ouvrir-la-validation", action="store_true",
                           help="Obligatoire pour la période de validation, qui ne se lit qu'une fois.")
    options = analyseur.parse_args()
    if options.periode == "validation" and not options.ouvrir_la_validation:
        analyseur.error("La validation ne se lit qu'une fois : ajoute --ouvrir-la-validation en connaissance de cause.")
    try:
        identifiant = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        debut, fin = PERIODES[options.periode]
        print(f"BACKTEST — période « {options.periode} », du {debut} au {fin}. Scénarios de coûts simulés : "
              "le barème du compte est inconnu, aucun résultat n'est celui du compte.")
        resultats, corrections = executer(options.periode, lire_csv_taux(TAUX_FIGES))
        for symbole, liste in corrections.items():
            print(f"Bougies Daily nettoyées pour {symbole} : {len(liste)}")
        dossier = DOSSIER_PROJET / "resultats" / f"backtest_{options.periode}_{identifiant}"
        for simulation, resultat in resultats.items():
            afficher(simulation, resultat)
            if resultat["positions"]:
                ecrire_csv(dossier / f"{simulation.lower()}_positions.csv",
                           [{champ: position[champ] for champ in CHAMPS_POSITION}
                            for position in deepcopy(resultat["positions"])], CHAMPS_POSITION)
            if resultat["conversions"]:
                ecrire_csv(dossier / f"{simulation.lower()}_conversions.csv", resultat["conversions"], CHAMPS_CONVERSION)
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / "mesures.json", "w", encoding="utf-8") as fichier:
            json.dump({simulation: resultat["mesures"] for simulation, resultat in resultats.items()},
                      fichier, ensure_ascii=False, indent=2, default=str)
        print(f"\nJournaux et mesures : {dossier}")
        return 0
    except (ValueError, OSError, KeyError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
