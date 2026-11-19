"""Inventaire des données accessibles avant un backtest : couverture, trous, divisions, taux.

Ce programme ne calcule ni signal ni performance : il compte des bougies et les
compare au calendrier NASDAQ. Il sert à choisir des périodes d'après la
disponibilité des données, jamais d'après les cours.

Lancer :  python inventaire_donnees.py            (les trois titres, depuis 2015)
          python inventaire_donnees.py --symbole AAPL --debut 2024-01-01
"""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from etape_01_tendance import SYMBOLES
from etape_03_entree_1h import construire_grille
from source_alpaca import RETARD_TOTAL, assembler_horaire, jour_de_barre, telecharger_barres
from source_bce import telecharger_taux


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc
PREMIER_JOUR = date(2015, 1, 1)
# Identifiants publics des sociétés auprès de la SEC (registre EDGAR).
IDENTIFIANTS_SEC = {"AAPL": "0000320193", "NVDA": "0001045810", "AVGO": "0001730168"}


def minuit(jour):
    return datetime.combine(jour, time(0, 0), NEW_YORK)


def inventorier_daily(symbole, debut, fin, maintenant):
    """Séances attendues, bougies Daily reçues, séances manquantes et divisions d'actions."""
    ajustees = {jour_de_barre(barre): barre for barre in
                telecharger_barres("1Day", minuit(debut), minuit(fin), maintenant, symbole)}
    brutes = {jour_de_barre(barre): barre for barre in
              telecharger_barres("1Day", minuit(debut), minuit(fin), maintenant, symbole, ajustement="raw")}
    if not ajustees:
        return {"premiere": None, "derniere": None, "recues": 0, "manquantes": [], "divisions": []}
    premiere, derniere = min(ajustees), max(ajustees)
    attendues = sorted({creneau["session"] for creneau in construire_grille(premiere, derniere)})
    # Une division d'actions se voit quand le rapport « cours brut / cours ajusté » change.
    divisions, precedent = [], None
    for jour in sorted(set(ajustees) & set(brutes)):
        rapport = brutes[jour]["c"] / ajustees[jour]["c"]
        if precedent is not None and abs(rapport / precedent - 1) > 0.01:
            divisions.append({"date": jour, "facteur": round(precedent / rapport, 4)})
        precedent = rapport
    return {"premiere": premiere, "derniere": derniere, "recues": len(ajustees),
            "manquantes": [jour for jour in attendues if jour not in ajustees], "divisions": divisions}


def inventorier_horaire(symbole, debut, fin, maintenant):
    """Par année : séances attendues, séances dont toutes les bougies horaires sont complètes."""
    consultable = maintenant - RETARD_TOTAL
    bilans = []
    for annee in range(debut.year, fin.year + 1):
        depart = max(minuit(debut), minuit(date(annee, 1, 1)))
        arrivee = min(minuit(fin), minuit(date(annee + 1, 1, 1)), consultable)
        if arrivee <= depart:
            continue
        grille = [creneau for creneau in construire_grille(depart.date(), arrivee.date())
                  if depart <= creneau["debut"] and creneau["fin"] <= arrivee]
        barres = telecharger_barres("30Min", depart, arrivee, maintenant, symbole)
        bougies, incomplets, _ = assembler_horaire(barres, grille, depart, arrivee, arrivee, arrivee)
        attendues = {}
        for creneau in grille:
            attendues[creneau["session"]] = attendues.get(creneau["session"], 0) + 1
        completes = {}
        for bougie in bougies:
            if all(bougie[champ] is not None for champ in ("ouverture", "high", "low", "cloture")):
                completes[bougie["session"]] = completes.get(bougie["session"], 0) + 1
        entieres = [session for session, nombre in attendues.items() if completes.get(session, 0) == nombre]
        trouees = sorted(session for session in attendues if session not in entieres)
        bilans.append({
            "annee": annee, "seances": len(attendues), "seances_completes": len(entieres),
            "creneaux": len(grille), "creneaux_incomplets": len(incomplets),
            "premiere_complete": min(entieres) if entieres else None,
            "derniere_complete": max(entieres) if entieres else None, "seances_trouees": trouees,
        })
    return bilans


def inventorier_taux(debut, fin):
    """Taux BCE : première et dernière date, jours de semaine sans taux sur la période."""
    taux = telecharger_taux()
    jours = sorted(jour for jour in taux if debut <= jour <= fin)
    sans_taux, jour = [], jours[0]
    while jour <= jours[-1]:
        if jour.weekday() < 5 and jour not in taux:
            sans_taux.append(jour)
        jour += timedelta(days=1)
    return {"premiere": jours[0], "derniere": jours[-1], "nombre": len(jours), "sans_taux": sans_taux}


def tester_registre_sec(symbole):
    """Le registre officiel EDGAR répond-il à un client anonyme ? Une seule requête par titre.

    Aucune adresse de contact n'est envoyée : si la SEC en exige une, le programme le dit
    et s'arrête là. Les dates lues sont celles des publications PASSÉES (formulaire 8-K,
    rubrique 2.02) : connues après coup, elles ne disent pas quand la date était annoncée.
    """
    adresse = f"https://data.sec.gov/submissions/CIK{IDENTIFIANTS_SEC[symbole]}.json"
    requete = urllib.request.Request(adresse, headers={"User-Agent": "python-urllib"})
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            recents = json.loads(reponse.read().decode("utf-8"))["filings"]["recent"]
    except urllib.error.HTTPError as erreur:
        return f"refusé (HTTP {erreur.code}) : la SEC demande d'identifier le client par une adresse de contact"
    except (urllib.error.URLError, OSError, KeyError, ValueError) as erreur:
        return f"inaccessible : {erreur}"
    dates = sorted(jour for jour, formulaire, rubriques in
                   zip(recents["filingDate"], recents["form"], recents["items"])
                   if formulaire == "8-K" and "2.02" in rubriques)
    if not dates:
        return "accessible, mais aucune publication de résultats listée"
    return f"accessible : {len(dates)} publications de résultats du {dates[0]} au {dates[-1]}"


def afficher_titre(symbole, daily, horaires):
    print(f"\n=== {symbole} ===")
    if daily["premiere"] is None:
        print("Aucune bougie Daily reçue.")
        return
    print(f"Daily : {daily['recues']} bougies du {daily['premiere']} au {daily['derniere']} ; "
          f"séances NASDAQ manquantes : {len(daily['manquantes'])}"
          + (f" ({', '.join(str(jour) for jour in daily['manquantes'][:8])})" if daily["manquantes"] else ""))
    divisions = ", ".join(f"{division['date']} (1 pour {division['facteur']:g})" for division in daily["divisions"])
    print(f"Divisions d'actions repérées : {divisions or 'aucune'}")
    print("Horaire (bougies 1 h assemblées depuis des barres de 30 minutes) :")
    print("  année | séances | complètes | créneaux incomplets | première complète | séances trouées")
    for bilan in horaires:
        trouees = ", ".join(str(jour) for jour in bilan["seances_trouees"][:6])
        if len(bilan["seances_trouees"]) > 6:
            trouees += f", … ({len(bilan['seances_trouees'])} au total)"
        print(f"  {bilan['annee']}  | {bilan['seances']:7d} | {bilan['seances_completes']:9d} | "
              f"{bilan['creneaux_incomplets']:19d} | {bilan['premiere_complete']}        | {trouees or '-'}")


def main():
    analyseur = argparse.ArgumentParser(description="Inventaire des données accessibles (aucune performance calculée).")
    analyseur.add_argument("--symbole", choices=SYMBOLES, action="append", help="Défaut : les trois titres.")
    analyseur.add_argument("--debut", type=date.fromisoformat, default=PREMIER_JOUR, help="Premier jour demandé.")
    analyseur.add_argument("--sans-horaire", action="store_true", help="Ne télécharge pas les barres de 30 minutes.")
    options = analyseur.parse_args()
    maintenant = datetime.now(UTC)
    fin = maintenant.astimezone(NEW_YORK).date()
    print(f"INVENTAIRE DES DONNÉES — demandé du {options.debut} au {fin}. Aucun signal, aucune performance.")
    print("Convention des cours : ajustés des divisions d'actions, non ajustés des dividendes (Alpaca, flux SIP).")
    try:
        for symbole in options.symbole or SYMBOLES:
            daily = inventorier_daily(symbole, options.debut, fin, maintenant)
            horaires = []
            if not options.sans_horaire and daily["premiere"] is not None:
                horaires = inventorier_horaire(symbole, max(options.debut, daily["premiere"]), fin, maintenant)
            afficher_titre(symbole, daily, horaires)
        taux = inventorier_taux(options.debut, fin)
        print(f"\n=== Taux BCE EUR/USD ===\n{taux['nombre']} taux du {taux['premiere']} au {taux['derniere']} ; "
              f"jours de semaine sans taux : {len(taux['sans_taux'])} (jours fériés TARGET)")
        print("\n=== Publications de résultats (registre officiel de la SEC) ===")
        for symbole in options.symbole or SYMBOLES:
            print(f"{symbole} : {tester_registre_sec(symbole)}")
        print("Rappel : ces dates sont connues après coup. Elles servent à mesurer, pas à filtrer.")
        return 0
    except (ValueError, OSError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
