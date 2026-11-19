"""Première étape du playbook : vérifier la tendance journalière."""

import argparse
import csv
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


MINIMUM_CLOTURES = 55
DOSSIER_PROJET = Path(__file__).resolve().parent
CONVENTION_PRIX = "Close en USD : ajustée des splits, non ajustée des dividendes"
SYMBOLES = ("AAPL", "NVDA", "AVGO")   # titres du NASDAQ suivis par le projet
NOMS_SOURCES = {
    "alpaca": "Alpaca Market Data (flux sip)",
    "yahoo": "Yahoo Finance via yfinance",
}


class HistoriqueInsuffisant(ValueError):
    """Impossible d'évaluer toutes les conditions avec cet historique."""


def tendance_admissible(cloture, sma20, sma50, sma20_avant_5, sma50_avant_5):
    """Renvoie True seulement si les quatre comparaisons strictes réussissent."""
    return (
        cloture > sma50
        and sma20 > sma50
        and sma20 > sma20_avant_5
        and sma50 > sma50_avant_5
    )


def valider_clotures(clotures):
    """Refuse les trous et les prix invalides au lieu de les remplacer."""
    valeurs = []
    for position, cloture in enumerate(clotures, start=1):
        try:
            prix = float(cloture)
        except (TypeError, ValueError):
            raise ValueError(f"Clôture invalide à la position {position} : {cloture!r}") from None
        if isinstance(cloture, bool) or not isfinite(prix) or prix <= 0:
            raise ValueError(f"Clôture invalide à la position {position} : {cloture!r}")
        valeurs.append(prix)
    return valeurs


def calculer_tendance(clotures):
    """Évalue la dernière séance d'une série chronologique, sans prix futur."""
    valeurs = valider_clotures(clotures)
    if len(valeurs) < MINIMUM_CLOTURES:
        raise HistoriqueInsuffisant(
            f"Historique insuffisant : {len(valeurs)} clôtures valides ; "
            f"au moins {MINIMUM_CLOTURES} sont nécessaires."
        )
    cloture = valeurs[-1]
    sma20 = mean(valeurs[-20:])
    sma50 = mean(valeurs[-50:])
    # Retirer les cinq dernières séances, puis prendre la fenêtre de 20 ou 50.
    sma20_avant_5 = mean(valeurs[-25:-5])
    sma50_avant_5 = mean(valeurs[-55:-5])
    return {
        "cloture": cloture,
        "sma20": sma20,
        "sma50": sma50,
        "sma20_avant_5": sma20_avant_5,
        "sma50_avant_5": sma50_avant_5,
        "c1": cloture > sma50,
        "c2": sma20 > sma50,
        "c3": sma20 > sma20_avant_5,
        "c4": sma50 > sma50_avant_5,
        "admissible": tendance_admissible(
            cloture, sma20, sma50, sma20_avant_5, sma50_avant_5
        ),
    }


def demonstration_serie():
    """Une liste de 55 prix inventés pour comprendre les fenêtres."""
    clotures = [100.0 + position for position in range(55)]
    print("\nSERIE FICTIVE : 55 clôtures, de 100 à 154")
    resultat = calculer_tendance(clotures)
    for nom, valeur in resultat.items():
        print(f"{nom} : {valeur}")
    try:
        calculer_tendance(clotures[:54])
    except HistoriqueInsuffisant as erreur:
        print(erreur)


def demonstration_cinq_valeurs():
    """Ces nombres sont fictifs : ils ne représentent pas le cours d'AAPL."""
    cloture = 110.0
    sma20 = 105.0
    sma50 = 100.0
    sma20_avant_5 = 102.0
    sma50_avant_5 = 98.0
    print("DEMONSTRATION FICTIVE — aucune donnée de marché")
    print(f"1. Clôture > SMA50 : {cloture} > {sma50} = {cloture > sma50}")
    print(f"2. SMA20 > SMA50 : {sma20} > {sma50} = {sma20 > sma50}")
    print(f"3. SMA20 monte : {sma20} > {sma20_avant_5} = {sma20 > sma20_avant_5}")
    print(f"4. SMA50 monte : {sma50} > {sma50_avant_5} = {sma50 > sma50_avant_5}")
    verdict = tendance_admissible(cloture, sma20, sma50, sma20_avant_5, sma50_avant_5)
    print(f"Tendance admissible : {verdict}. Ce n'est pas un signal d'achat.")


def date_limite_evaluation(date_demandee=None, maintenant=None):
    """La journée courante à New York est toujours exclue, même après clôture."""
    if maintenant is None:
        maintenant = datetime.now(ZoneInfo("America/New_York"))
    aujourd_hui = maintenant.astimezone(ZoneInfo("America/New_York")).date()
    if date_demandee is not None and date_demandee >= aujourd_hui:
        raise ValueError(
            "La date évaluée doit précéder la date courante à New York "
            f"({aujourd_hui}) : sa bougie Daily est exclue."
        )
    return date_demandee or aujourd_hui - timedelta(days=1)


def normaliser_cotations(cotations, date_limite):
    """Trie les séances, exclut les dates futures et refuse les doublons."""
    retenues = sorted(
        (jour, cloture) for jour, cloture in cotations if jour <= date_limite
    )
    dates = [jour for jour, _ in retenues]
    if len(set(dates)) != len(dates):
        raise ValueError("Dates en double : une seule clôture par séance est autorisée.")
    valeurs = valider_clotures([cloture for _, cloture in retenues])
    return list(zip(dates, valeurs))


def lire_csv(chemin, date_limite, symbole="AAPL"):
    """Lit un fichier Daily du titre avec colonnes Date,Close ; aucun réseau."""
    cotations = []
    with Path(chemin).open(encoding="utf-8-sig", newline="") as fichier:
        entete = fichier.readline()
        fichier.seek(0)
        separateur = ";" if ";" in entete else ","
        lecteur = csv.DictReader(fichier, delimiter=separateur)
        if not {"Date", "Close"}.issubset(lecteur.fieldnames or []):
            raise ValueError("CSV : les colonnes Date et Close sont obligatoires.")
        for numero, ligne in enumerate(lecteur, start=2):
            try:
                jour = date.fromisoformat(ligne["Date"].strip())
                # Les lignes postérieures ne doivent pas influencer l'évaluation.
                if jour > date_limite:
                    continue
                if "Symbol" in ligne and ligne["Symbol"].strip() != symbole:
                    raise ValueError(f"le CSV doit contenir uniquement {symbole}")
                cloture = float(ligne["Close"].replace(",", "."))
            except (ValueError, AttributeError, TypeError) as erreur:
                raise ValueError(f"CSV invalide à la ligne {numero} : {erreur}") from erreur
            cotations.append((jour, cloture))
    return normaliser_cotations(cotations, date_limite)


def verifier_seances_nasdaq(cotations):
    """Refuse une séance manquante : cinq lignes doivent être cinq séances."""
    if not cotations:
        return
    try:
        import pandas_market_calendars as calendriers
    except ImportError:
        raise ValueError("Installe les dépendances de requirements.txt pour vérifier les séances.") from None
    calendrier = calendriers.get_calendar("NASDAQ")
    attendues = {
        instant.date()
        for instant in calendrier.valid_days(
            start_date=cotations[0][0], end_date=cotations[-1][0]
        )
    }
    presentes = {jour for jour, _ in cotations}
    manquantes = sorted(attendues - presentes)
    hors_seance = sorted(presentes - attendues)
    if manquantes:
        raise ValueError(
            f"Séance NASDAQ manquante : {manquantes[0]}. "
            "Complète l'historique ; aucune clôture n'est inventée."
        )
    if hors_seance:
        raise ValueError(f"Date hors séance NASDAQ : {hors_seance[0]}.")


def telecharger_aapl(date_limite, symbole="AAPL"):
    """Source Yahoo, gardée pour contrôle : un an de Daily ; end est exclusive."""
    try:
        import yfinance as yf
    except ImportError:
        raise ValueError("yfinance est absent : installe requirements.txt ou utilise --csv.") from None
    try:
        donnees = yf.download(
            symbole,
            start=(date_limite - timedelta(days=370)).isoformat(),
            end=(date_limite + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            back_adjust=False,
            repair=False,
            rounding=False,
            keepna=True,
            prepost=False,
            ignore_tz=True,
            multi_level_index=False,
            threads=False,
            progress=False,
            timeout=20,
        )
        if donnees is None or donnees.empty:
            raise ValueError("Yahoo n'a renvoyé aucune clôture.")
        cotations = [(instant.date(), cloture) for instant, cloture in donnees["Close"].items()]
    except Exception as erreur:
        raise ValueError(
            f"Téléchargement {symbole} indisponible : {erreur}\n"
            "Solution de secours : relance avec --csv chemin\\aapl_daily.csv "
            "(colonnes Date,Close, même convention de prix)."
        ) from erreur
    return normaliser_cotations(cotations, date_limite)


def telecharger_clotures(date_limite, symbole="AAPL", source="alpaca"):
    """Alpaca par défaut ; Yahoo reste disponible pour contrôler une valeur."""
    if source == "yahoo":
        return telecharger_aapl(date_limite, symbole)
    # Import tardif : source_alpaca utilise lui-même les fonctions de ce fichier.
    from source_alpaca import telecharger_daily_recent
    try:
        bougies = telecharger_daily_recent(date_limite, symbole)
    except ValueError as erreur:
        raise ValueError(
            f"{erreur}\nSolutions de secours : --source yahoo, ou --csv avec une archive."
        ) from None
    cotations = [(bougie["date"], bougie["cloture"]) for bougie in bougies]
    return normaliser_cotations(cotations, date_limite)


def ecrire_csv(chemin, lignes, colonnes):
    """Crée un nouveau fichier ; refuse d'écraser un fichier existant."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("x", encoding="utf-8-sig", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=colonnes)
        redacteur.writeheader()
        redacteur.writerows(lignes)


def construire_tableau(cotations):
    """Chaque ligne utilise seulement sa clôture et les séances précédentes."""
    valeurs = valider_clotures([cloture for _, cloture in cotations])
    if len(valeurs) < MINIMUM_CLOTURES:
        raise HistoriqueInsuffisant(
            f"Historique insuffisant : {len(valeurs)} clôtures valides ; "
            f"au moins {MINIMUM_CLOTURES} sont nécessaires."
        )
    dates = [jour for jour, _ in cotations]
    if any(actuelle <= precedente for precedente, actuelle in zip(dates, dates[1:])):
        raise ValueError("Les dates doivent être uniques et classées chronologiquement.")
    tableau = []
    for position, (jour, cloture) in enumerate(zip(dates, valeurs)):
        # La fin d'une tranche Python est exclue : +1 inclut la séance évaluée.
        sma20 = mean(valeurs[position - 19:position + 1]) if position >= 19 else None
        sma50 = mean(valeurs[position - 49:position + 1]) if position >= 49 else None
        sma20_avant_5 = tableau[position - 5]["sma20"] if position >= 5 else None
        sma50_avant_5 = tableau[position - 5]["sma50"] if position >= 5 else None
        c1 = cloture > sma50 if sma50 is not None else None
        c2 = sma20 > sma50 if sma50 is not None else None
        c3 = sma20 > sma20_avant_5 if sma20_avant_5 is not None else None
        c4 = sma50 > sma50_avant_5 if sma50_avant_5 is not None else None
        admissible = None
        if position >= MINIMUM_CLOTURES - 1:
            admissible = tendance_admissible(
                cloture, sma20, sma50, sma20_avant_5, sma50_avant_5
            )
        tableau.append({
            "date": jour,
            "cloture": cloture,
            "sma20": sma20,
            "sma50": sma50,
            "sma20_avant_5": sma20_avant_5,
            "sma50_avant_5": sma50_avant_5,
            "c1": c1, "c2": c2, "c3": c3, "c4": c4,
            "admissible": admissible,
        })
    return tableau


def afficher_tableau(tableau, derniers=10):
    """Les arrondis concernent uniquement l'affichage, jamais les comparaisons."""
    print("\nC1 : Clôture > SMA50 | C2 : SMA20 > SMA50")
    print("C3 : SMA20 > SMA20(-5 séances) | C4 : SMA50 > SMA50(-5 séances)")
    print("ND : valeur indisponible ; historique insuffisant avant 55 clôtures.\n")
    print(f"{'Date':10} {'Clôture':>9} {'SMA20':>9} {'SMA50':>9} "
          f"{'SMA20(-5)':>10} {'SMA50(-5)':>10} {'C1':>4} {'C2':>4} {'C3':>4} {'C4':>4} Verdict")
    lignes = tableau if derniers == 0 else tableau[-derniers:]
    for ligne in lignes:
        prix = ["ND" if ligne[nom] is None else f"{ligne[nom]:.2f}" for nom in
                ("cloture", "sma20", "sma50", "sma20_avant_5", "sma50_avant_5")]
        conditions = ["ND" if ligne[nom] is None else ("VRAI" if ligne[nom] else "FAUX")
                      for nom in ("c1", "c2", "c3", "c4")]
        verdict = "INSUFFISANT" if ligne["admissible"] is None else (
            "ADMISSIBLE" if ligne["admissible"] else "REFUSÉE"
        )
        print(f"{ligne['date']} {prix[0]:>9} {prix[1]:>9} {prix[2]:>9} "
              f"{prix[3]:>10} {prix[4]:>10} " + " ".join(f"{valeur:>4}" for valeur in conditions) + f" {verdict}")
    print("\nCe filtre de tendance ne constitue pas un signal d'achat.")


def cotations_fictives():
    """Dates illustratives en semaine, sans prétendre reproduire le NASDAQ."""
    cotations = []
    jour = date(2025, 1, 6)
    while len(cotations) < 60:
        if jour.weekday() < 5:
            cotations.append((jour, 100.0 + len(cotations)))
        jour += timedelta(days=1)
    return cotations


def main():
    analyseur = argparse.ArgumentParser(description="Filtre de tendance Daily, AAPL par défaut.")
    sources = analyseur.add_mutually_exclusive_group()
    sources.add_argument("--demo", action="store_true", help="Démonstrations fictives, sans réseau.")
    sources.add_argument("--csv", type=Path, help="CSV Daily du titre, colonnes Date,Close.")
    analyseur.add_argument("--symbole", choices=SYMBOLES, default="AAPL", help="Titre analysé.")
    analyseur.add_argument("--source", choices=sorted(NOMS_SOURCES), default="alpaca",
                           help="Téléchargement : alpaca par défaut, yahoo pour contrôler.")
    analyseur.add_argument("--date", type=date.fromisoformat, help="Date évaluée incluse, AAAA-MM-JJ.")
    analyseur.add_argument("--derniers", type=int, default=10, help="Nombre de lignes affichées ; 0 = toutes.")
    analyseur.add_argument("--sortie", type=Path, help="Nouveau CSV de résultats ; aucun fichier n'est écrasé.")
    options = analyseur.parse_args()
    if options.derniers < 0:
        analyseur.error("--derniers doit être positif ou nul.")
    if options.demo and options.date:
        analyseur.error("--date concerne les données réelles ; retire --demo pour l'utiliser.")
    try:
        identifiant = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        symbole = options.symbole
        if options.demo:
            demonstration_cinq_valeurs()
            demonstration_serie()
            cotations = cotations_fictives()
            source = "FICTIF : prix inventés, dates illustratives ; aucune donnée AAPL"
            convention = "FICTIF : aucune donnée de marché"
            prefixe = "fictif"
        else:
            limite = date_limite_evaluation(options.date)
            cotations = (lire_csv(options.csv, limite, symbole) if options.csv
                         else telecharger_clotures(limite, symbole, options.source))
            verifier_seances_nasdaq(cotations)
            source = (f"CSV fourni ({options.csv}, origine non vérifiée)" if options.csv else
                      f"Données réelles {symbole}, {NOMS_SOURCES[options.source]}")
            convention = CONVENTION_PRIX
            prefixe = symbole.lower()
            print(f"Titre : {symbole}. Date limite : {limite} ; journée courante à New York exclue.")
        tableau = construire_tableau(cotations)
        print(f"\nSource : {source}")
        print(f"Convention : {convention}")
        print(f"{len(cotations)} clôtures ; dernière séance disponible : {cotations[-1][0]}")
        afficher_tableau(tableau, options.derniers)
        if not options.csv and not options.demo:
            archive = DOSSIER_PROJET / "donnees" / f"{prefixe}_{options.source}_daily_{identifiant}.csv"
            ecrire_csv(archive, [{"Date": jour, "Close": prix} for jour, prix in cotations], ["Date", "Close"])
            print(f"Archive CSV pour fonctionner hors ligne : {archive}")
        sortie = options.sortie or DOSSIER_PROJET / "resultats" / f"{prefixe}_tendance_{identifiant}.csv"
        colonnes = list(tableau[0]) + ["source", "convention_prix"]
        lignes_export = [dict(ligne, source=source, convention_prix=convention) for ligne in tableau]
        ecrire_csv(sortie, lignes_export, colonnes)
        print(f"Tableau complet ({len(tableau)} lignes) : {sortie}")
        return 0
    except (ValueError, OSError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
