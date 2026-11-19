"""Compare les archives Alpaca aux archives Yahoo, sans fixer de seuil de réussite.

Le programme mesure et affiche ; la décision de changer de source reste humaine.
"""

import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from etape_01_tendance import DOSSIER_PROJET, ecrire_csv
from etape_02_pullback import lire_csv_pullback
from etape_03_entree_1h import construire_grille, instant_utc, lire_csv_horaire
from source_alpaca import (
    afficher_rapport_horaire, archiver_daily, archiver_horaire,
    telecharger_daily, telecharger_horaire,
)


YAHOO_DAILY = DOSSIER_PROJET / "donnees" / "aapl_entree_daily_20261113_150143_329817.csv"
YAHOO_HORAIRE = DOSSIER_PROJET / "donnees" / "aapl_1h_20261113_150143_329817.csv"
SEUIL_COMPTAGE = 0.01     # sert à compter les écarts, pas à juger la source
CHAMPS_DAILY = ("high", "low", "cloture")
CHAMPS_HORAIRE = ("ouverture", "high", "low", "cloture")
DECISIONS = ("SIGNAL", "ENTREE_ACCEPTEE", "ENTREE_ANNULEE")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def bornes_csv(chemin, colonne, convertir):
    """Plus petite et plus grande valeur d'une colonne de dates ou d'instants."""
    with Path(chemin).open(encoding="utf-8-sig", newline="") as fichier:
        entete = fichier.readline()
        fichier.seek(0)
        lecteur = csv.DictReader(fichier, delimiter=";" if ";" in entete else ",")
        valeurs = [convertir(ligne[colonne].strip()) for ligne in lecteur]
    if not valeurs:
        raise ValueError(f"Archive vide : {chemin}")
    return min(valeurs), max(valeurs)


def comparer(yahoo, alpaca, cle, champs, type_donnees):
    """Une ligne par champ et par date (ou créneau), présente d'un côté ou des deux."""
    par_yahoo = {ligne[cle]: ligne for ligne in yahoo}
    par_alpaca = {ligne[cle]: ligne for ligne in alpaca}
    ecarts = []
    for repere in sorted(set(par_yahoo) | set(par_alpaca)):
        cote_yahoo, cote_alpaca = par_yahoo.get(repere), par_alpaca.get(repere)
        if cote_yahoo is None or cote_alpaca is None:
            ecarts.append({"type": type_donnees, "repere": repere.isoformat(), "champ": "",
                           "presence": "ALPACA_SEUL" if cote_yahoo is None else "YAHOO_SEUL",
                           "yahoo": None, "alpaca": None, "ecart_usd": None, "ecart_pct": None})
            continue
        for champ in champs:
            prix_yahoo, prix_alpaca = cote_yahoo[champ], cote_alpaca[champ]
            ligne = {"type": type_donnees, "repere": repere.isoformat(), "champ": champ,
                     "presence": "DEUX", "yahoo": prix_yahoo, "alpaca": prix_alpaca,
                     "ecart_usd": None, "ecart_pct": None}
            if prix_yahoo is None or prix_alpaca is None:
                # Exemple : bougie Yahoo encore en cours, dont seul l'Open était connu.
                ligne["presence"] = "CHAMP_ABSENT_YAHOO" if prix_yahoo is None else "CHAMP_ABSENT_ALPACA"
            else:
                ligne["ecart_usd"] = prix_alpaca - prix_yahoo
                ligne["ecart_pct"] = 100 * (prix_alpaca - prix_yahoo) / prix_yahoo
            ecarts.append(ligne)
    return ecarts


def comparer_daily_et_horaire(daily, horaires, grille):
    """High/Low de la barre Daily contre le plus haut/bas des bougies horaires du jour."""
    attendus = {}
    for creneau in grille:
        attendus[creneau["session"]] = attendus.get(creneau["session"], 0) + 1
    par_jour = {}
    for bougie in horaires:
        if bougie["high"] is not None and bougie["low"] is not None:
            par_jour.setdefault(bougie["session"], []).append(bougie)
    lignes = []
    for bougie in daily:
        jour = bougie["date"]
        du_jour = par_jour.get(jour, [])
        # Une journée horaire incomplète ne permet pas de conclure : on la saute.
        if jour not in attendus or len(du_jour) != attendus[jour]:
            continue
        haut = max(ligne["high"] for ligne in du_jour)
        bas = min(ligne["low"] for ligne in du_jour)
        lignes.append({"date": jour, "high_daily": bougie["high"], "high_horaire": haut,
                       "low_daily": bougie["low"], "low_horaire": bas,
                       "ecart_high": bougie["high"] - haut, "ecart_low": bougie["low"] - bas})
    return lignes


def afficher_resume(ecarts, type_donnees, champs):
    lignes = [ligne for ligne in ecarts if ligne["type"] == type_donnees]
    print(f"\n--- {type_donnees} ---")
    for presence in ("YAHOO_SEUL", "ALPACA_SEUL", "CHAMP_ABSENT_YAHOO", "CHAMP_ABSENT_ALPACA"):
        concernees = [ligne for ligne in lignes if ligne["presence"] == presence]
        print(f"{presence} : {len(concernees)}")
        for ligne in concernees[:10]:
            print(f"  {ligne['repere']} {ligne['champ']}")
    print(f"{'Champ':10} {'Comparées':>9} {'Écart max USD':>14} {'Écart max %':>12} {'> 0,01 USD':>11}")
    for champ in champs:
        mesures = [ligne for ligne in lignes if ligne["champ"] == champ and ligne["ecart_usd"] is not None]
        if not mesures:
            print(f"{champ:10} {0:>9} {'ND':>14} {'ND':>12} {'ND':>11}")
            continue
        maximum_usd = max(abs(ligne["ecart_usd"]) for ligne in mesures)
        maximum_pct = max(abs(ligne["ecart_pct"]) for ligne in mesures)
        depassements = sum(abs(ligne["ecart_usd"]) > SEUIL_COMPTAGE for ligne in mesures)
        print(f"{champ:10} {len(mesures):>9} {maximum_usd:>14.4f} {maximum_pct:>12.4f} {depassements:>11}")
    # Une bougie compte une fois, même si plusieurs de ses champs dépassent.
    bougies = {ligne["repere"] for ligne in lignes
               if ligne["ecart_usd"] is not None and abs(ligne["ecart_usd"]) > SEUIL_COMPTAGE}
    print(f"Bougies avec au moins un écart > 0,01 USD : {len(bougies)}")


def afficher_plus_gros(ecarts, nombre=10):
    mesures = [ligne for ligne in ecarts if ligne["ecart_usd"] is not None]
    mesures.sort(key=lambda ligne: abs(ligne["ecart_usd"]), reverse=True)
    print(f"\nLes {nombre} plus gros écarts (Alpaca moins Yahoo) :")
    for ligne in mesures[:nombre]:
        print(f"  {ligne['type']:7} {ligne['repere']:25} {ligne['champ']:9} "
              f"Yahoo {ligne['yahoo']:.4f} Alpaca {ligne['alpaca']:.4f} "
              f"écart {ligne['ecart_usd']:+.4f} USD ({ligne['ecart_pct']:+.4f} %)")


def afficher_daily_contre_horaire(lignes):
    print("\n--- Barre 1Day Alpaca contre bougies horaires Alpaca du même jour ---")
    if not lignes:
        print("Aucun jour comparable (journées horaires incomplètes ou périodes disjointes).")
        return
    for nom in ("ecart_high", "ecart_low"):
        maximum = max(abs(ligne[nom]) for ligne in lignes)
        differents = [ligne for ligne in lignes if abs(ligne[nom]) > SEUIL_COMPTAGE]
        print(f"{nom} : {len(lignes)} jours comparés, écart maximal {maximum:.4f} USD, "
              f"{len(differents)} jour(s) au-delà de 0,01 USD")
        for ligne in differents[:10]:
            print(f"  {ligne['date']} Daily moins horaire = {ligne[nom]:+.4f} USD")


def comparer_journaux(chemin_yahoo, chemin_alpaca):
    """Compare deux journaux de l'étape 3 : mêmes décisions, ou première divergence."""
    def lire(chemin):
        with Path(chemin).open(encoding="utf-8-sig", newline="") as fichier:
            return list(csv.DictReader(fichier))

    def repere(ligne):
        return (ligne["instant"], ligne["evenement"], ligne["debut"])

    journaux = {"Yahoo": lire(chemin_yahoo), "Alpaca": lire(chemin_alpaca)}
    for nom, journal in journaux.items():
        print(f"\nDécisions {nom} ({len(journal)} lignes) :")
        for ligne in journal:
            if ligne["statut"] in DECISIONS:
                print(f"  {ligne['instant']} {ligne['statut']} sommet {ligne['date_sommet']} "
                      f"Close {ligne['cloture_signal']} High précédent {ligne['high_precedent']} "
                      f"prix d'entrée {ligne['prix_entree'] or 'ND'} — {ligne['motif']}")
    par_yahoo = {repere(ligne): ligne for ligne in journaux["Yahoo"]}
    par_alpaca = {repere(ligne): ligne for ligne in journaux["Alpaca"]}
    divergences = []
    for cle in sorted(set(par_yahoo) | set(par_alpaca)):
        cote_yahoo, cote_alpaca = par_yahoo.get(cle), par_alpaca.get(cle)
        if cote_yahoo is None or cote_alpaca is None:
            divergences.append((cle, "ligne présente d'un seul côté : "
                                + ("Alpaca" if cote_yahoo is None else "Yahoo")))
        elif (cote_yahoo["statut"], cote_yahoo["motif"]) != (cote_alpaca["statut"], cote_alpaca["motif"]):
            divergences.append((cle, f"Yahoo {cote_yahoo['statut']} ({cote_yahoo['motif']}) / "
                                     f"Alpaca {cote_alpaca['statut']} ({cote_alpaca['motif']})"))
    print(f"\nLignes dont le statut ou le motif diffère : {len(divergences)}")
    for cle, texte in divergences[:10]:
        print(f"  {cle[0]} {cle[1]} bougie {cle[2]} : {texte}")
    if divergences:
        print("La première ligne ci-dessus est la première divergence dans l'ordre chronologique.")
    else:
        print("Les deux journaux donnent les mêmes statuts et motifs, ligne par ligne.")
    return divergences


def main():
    analyseur = argparse.ArgumentParser(description="Compare Alpaca et Yahoo sur AAPL.")
    analyseur.add_argument("--yahoo-daily", type=Path, default=YAHOO_DAILY)
    analyseur.add_argument("--yahoo-horaire", type=Path, default=YAHOO_HORAIRE)
    analyseur.add_argument("--alpaca-daily", type=Path, help="Archive Alpaca déjà téléchargée (sinon téléchargement).")
    analyseur.add_argument("--alpaca-horaire", type=Path, help="Archive Alpaca déjà téléchargée (sinon téléchargement).")
    analyseur.add_argument("--journaux", type=Path, nargs=2, metavar=("YAHOO", "ALPACA"),
                           help="Compare seulement deux journaux de l'étape 3.")
    options = analyseur.parse_args()
    if bool(options.alpaca_daily) != bool(options.alpaca_horaire):
        analyseur.error("Fournir ensemble --alpaca-daily et --alpaca-horaire.")
    try:
        if options.journaux:
            comparer_journaux(*options.journaux)
            return 0
        maintenant = datetime.now(UTC)
        identifiant = maintenant.strftime("%Y%m%d_%H%M%S_%f")
        # Les périodes viennent des archives Yahoo : première et dernière ligne.
        premier_jour, dernier_jour = bornes_csv(options.yahoo_daily, "Date", date.fromisoformat)
        premier_instant, dernier_instant = bornes_csv(options.yahoo_horaire, "Datetime", instant_utc)
        grille = construire_grille(premier_instant.astimezone(NEW_YORK).date(),
                                   dernier_instant.astimezone(NEW_YORK).date())
        yahoo_daily = lire_csv_pullback(options.yahoo_daily, dernier_jour)
        yahoo_horaire = lire_csv_horaire(options.yahoo_horaire, maintenant, grille)
        debut_horaire, fin_horaire = yahoo_horaire[0]["debut"], yahoo_horaire[-1]["fin"]
        if options.alpaca_daily:
            alpaca_daily = lire_csv_pullback(options.alpaca_daily, dernier_jour)
            alpaca_horaire = lire_csv_horaire(options.alpaca_horaire, maintenant, grille)
            print("Archives Alpaca relues, sans téléchargement.")
        else:
            alpaca_daily = telecharger_daily(premier_jour, dernier_jour, maintenant)
            alpaca_horaire, incomplets, hors_seance, barres = telecharger_horaire(
                debut_horaire, fin_horaire, grille, maintenant)
            print("Téléchargement Alpaca réussi : flux sip accepté, ajustement split.")
            afficher_rapport_horaire(barres, incomplets, hors_seance)
            print(f"Archive Daily : {archiver_daily(alpaca_daily, identifiant)}")
            print(f"Archive horaire : {archiver_horaire(alpaca_horaire, identifiant)}")
        print(f"Daily comparé du {premier_jour} au {dernier_jour} ; "
              f"horaire du {debut_horaire.isoformat()} au {fin_horaire.isoformat()}")
        ecarts = (comparer(yahoo_daily, alpaca_daily, "date", CHAMPS_DAILY, "daily")
                  + comparer(yahoo_horaire, alpaca_horaire, "debut", CHAMPS_HORAIRE, "horaire"))
        afficher_resume(ecarts, "daily", CHAMPS_DAILY)
        afficher_resume(ecarts, "horaire", CHAMPS_HORAIRE)
        afficher_plus_gros(ecarts)
        afficher_daily_contre_horaire(comparer_daily_et_horaire(alpaca_daily, alpaca_horaire, grille))
        sortie = DOSSIER_PROJET / "resultats" / f"comparaison_alpaca_yahoo_{identifiant}.csv"
        ecrire_csv(sortie, ecarts, list(ecarts[0]))
        print(f"\nDétail des écarts ({len(ecarts)} lignes) : {sortie}")
        print("Aucun seuil de réussite n'est appliqué : ces mesures servent à décider.")
        return 0
    except (ValueError, OSError, KeyError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
