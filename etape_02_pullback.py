"""Pullback Daily AAPL : pivots confirmés, profondeur et suivi causal."""

import argparse
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from etape_01_tendance import (
    CONVENTION_PRIX, DOSSIER_PROJET, NOMS_SOURCES, SYMBOLES, construire_tableau,
    date_limite_evaluation, ecrire_csv, valider_clotures, verifier_seances_nasdaq,
)


SEANCES_RECORD = 20
RETRACEMENT_MAXIMUM = 0.50
FACTEUR_SEUIL_SMA20 = 0.96
PREMIERE_SEANCE_ADMISSIBLE = 3
DERNIERE_SEANCE_ADMISSIBLE = 10
PLUS_BAS_DEMO = 112.0



def est_pivot(bougies, position, type_pivot, indice_evaluation):
    """None = inconnu ; True/False = comparaison possible avec cinq séances."""
    if type_pivot not in ("sommet", "creux"):
        raise ValueError("Le type de pivot doit être 'sommet' ou 'creux'.")
    if not 0 <= position < len(bougies) or not 0 <= indice_evaluation < len(bougies):
        raise ValueError("Position de séance hors historique.")
    if position < 2 or position + 2 > indice_evaluation:
        return None
    champ = "high" if type_pivot == "sommet" else "low"
    prix = bougies[position][champ]
    voisins = (position - 2, position - 1, position + 1, position + 2)
    if type_pivot == "sommet":
        return all(prix > bougies[voisin][champ] for voisin in voisins)
    return all(prix < bougies[voisin][champ] for voisin in voisins)


def est_sommet_reference(bougies, position, indice_evaluation):
    """Le record porte sur les 20 séances AVANT l'apparition du sommet."""
    pivot = est_pivot(bougies, position, "sommet", indice_evaluation)
    if pivot is False:
        return False
    if pivot is None or position < SEANCES_RECORD:
        return None
    sommet = bougies[position]["high"]
    precedentes = bougies[position - SEANCES_RECORD:position]
    return all(sommet > bougie["high"] for bougie in precedentes)


def calculer_retracement(sommet, creux_reference, plus_bas):
    """Renvoie un ratio : 0.40 représente 40 %, sans arrondi."""
    sommet, creux_reference, plus_bas = valider_clotures(
        [sommet, creux_reference, plus_bas]
    )
    sommet, creux_reference, plus_bas = (
        Decimal(str(prix)) for prix in (sommet, creux_reference, plus_bas)
    )
    hausse = sommet - creux_reference
    if hausse <= 0:
        raise ValueError("La hausse de référence doit être strictement positive.")
    if plus_bas > sommet:
        raise ValueError("Le plus bas du repli ne peut pas dépasser le sommet.")
    return float((sommet - plus_bas) / hausse)


def normaliser_bougies(bougies, date_limite=None):
    """Trie et valide les vrais High/Low/Close, sans compléter les données."""
    retenues = []
    for bougie in bougies:
        if "date" not in bougie or not isinstance(bougie["date"], date):
            raise ValueError("Chaque bougie doit avoir une date valide.")
        if date_limite is not None and bougie["date"] > date_limite:
            continue
        if not {"high", "low", "cloture"}.issubset(bougie):
            raise ValueError("High, Low et Close sont obligatoires pour le pullback.")
        high, low, cloture = valider_clotures(
            [bougie["high"], bougie["low"], bougie["cloture"]]
        )
        if not low <= cloture <= high:
            raise ValueError(f"Bougie incohérente le {bougie['date']} : Low <= Close <= High requis.")
        retenues.append({"date": bougie["date"], "high": high, "low": low, "cloture": cloture})
    retenues.sort(key=lambda bougie: bougie["date"])
    dates = [bougie["date"] for bougie in retenues]
    if len(set(dates)) != len(dates):
        raise ValueError("Dates en double : une seule bougie par séance est autorisée.")
    return retenues


def confirmer_pivots(bougies, indice_evaluation):
    """À chaque clôture, seul le pivot situé deux séances avant peut être confirmé."""
    position = indice_evaluation - 2
    if position < 2:
        return []
    pivots = []
    for type_pivot in ("creux", "sommet"):
        if est_pivot(bougies, position, type_pivot, indice_evaluation):
            champ = "low" if type_pivot == "creux" else "high"
            pivots.append({
                "type": type_pivot,
                "indice_apparition": position,
                "indice_confirmation": indice_evaluation,
                "date_apparition": bougies[position]["date"],
                "date_confirmation": bougies[indice_evaluation]["date"],
                "prix": bougies[position][champ],
                "sommet_reference": est_sommet_reference(bougies, position, indice_evaluation)
                if type_pivot == "sommet" else None,
            })
    return pivots


def _bilan_controles(controles):
    """Un échec certain prime ; des données manquantes restent inconnues."""
    if any(controle is False for controle in controles):
        return False
    if any(controle is None for controle in controles):
        return None
    return True


def _evaluer_configuration(configuration, bougies, tendances, indice):
    """Relit au maximum dix séances, toutes déjà terminées à cette date."""
    resultat = dict(configuration)
    debut = configuration["indice_sommet"]
    repli = bougies[debut + 1:indice + 1]
    sommet = configuration["sommet"]
    reference = configuration["creux_reference"]
    plus_bas = min(bougie["low"] for bougie in repli)
    age = indice - debut
    retracement = None
    profondeur = None
    inconnus = []
    if reference is None:
        inconnus.append("CREUX_REFERENCE_ABSENT")
    elif sommet <= reference:
        inconnus.append("HAUSSE_NON_POSITIVE")
    else:
        retracement = calculer_retracement(sommet, reference, plus_bas)
        # Comparer les montants avant division évite de perdre une égalité à 50 %.
        h, lref, lmin = (Decimal(str(prix)) for prix in (sommet, reference, plus_bas))
        profondeur = h - lmin <= Decimal(str(RETRACEMENT_MAXIMUM)) * (h - lref)

    controles_sma = []
    for seance in range(debut + 1, indice + 1):
        precedente = tendances[seance - 1]["sma20"]
        controle = None if precedente is None else (
            Decimal(str(bougies[seance]["low"]))
            >= Decimal(str(FACTEUR_SEUIL_SMA20)) * Decimal(str(precedente))
        )
        controles_sma.append(controle)
    sma_respectee = _bilan_controles(controles_sma)
    tendance_continue = _bilan_controles(
        [tendances[seance]["admissible"] for seance in range(debut + 1, indice + 1)]
    )
    invalidations = []
    if any(bougie["high"] > sommet for bougie in repli):
        invalidations.append("NOUVEAU_HIGH")
    if profondeur is False:
        invalidations.append("RETRACEMENT_SUPERIEUR_50")
    if sma_respectee is False:
        invalidations.append("LOW_SOUS_SMA20_PRECEDENTE")
    if tendance_continue is False:
        invalidations.append("TENDANCE_INTERROMPUE")
    if sma_respectee is None:
        inconnus.append("SMA20_INDISPONIBLE")
    if tendance_continue is None:
        inconnus.append("TENDANCE_INDISPONIBLE")

    admissible = False
    if invalidations:
        statut = "INVALIDE"
        motif = ";".join(invalidations)
    elif inconnus:
        statut = "NON_EVALUABLE"
        admissible = None
        motif = ";".join(inconnus)
    elif age < PREMIERE_SEANCE_ADMISSIBLE:
        statut = "ATTENTE_J3"
        motif = "FENETRE_NON_OUVERTE"
    else:
        statut = "ADMISSIBLE"
        admissible = True
        motif = "CRITERES_DAILY_RESPECTES"
    apres_cloture = statut
    if age == DERNIERE_SEANCE_ADMISSIBLE and statut != "INVALIDE":
        apres_cloture = "EXPIREE"
    resultat.update({
        "plus_bas_repli": plus_bas, "age_seances": age,
        "retracement": retracement, "profondeur_respectee": profondeur,
        "sma_respectee": sma_respectee, "tendance_continue": tendance_continue,
        "admissible": admissible, "statut": statut,
        "statut_apres_cloture": apres_cloture, "motif": motif,
    })
    return resultat


def scanner_pullbacks(bougies):
    """Un passage chronologique : aucune configuration avant sa confirmation."""
    bougies = normaliser_bougies(bougies)
    tendances = construire_tableau([(bougie["date"], bougie["cloture"]) for bougie in bougies])
    creux_confirmes = []
    configuration = None
    tableau = []
    for indice, bougie in enumerate(bougies):
        pivots = confirmer_pivots(bougies, indice)
        for pivot in pivots:
            if pivot["type"] == "creux":
                creux_confirmes.append(pivot)
        nouveau_sommet = next(
            (pivot for pivot in pivots if pivot["sommet_reference"] is True), None
        )
        # Un record supérieur a déjà invalidé l'ancienne configuration à son J0.
        if nouveau_sommet is not None:
            precedents = [creux for creux in creux_confirmes
                          if creux["indice_apparition"] < nouveau_sommet["indice_apparition"]]
            creux = precedents[-1] if precedents else None
            configuration = {
                "indice_sommet": nouveau_sommet["indice_apparition"],
                "date_sommet": nouveau_sommet["date_apparition"],
                "date_confirmation_sommet": nouveau_sommet["date_confirmation"],
                "sommet": nouveau_sommet["prix"],
                "date_creux": creux["date_apparition"] if creux else None,
                "date_confirmation_creux": creux["date_confirmation"] if creux else None,
                "creux_reference": creux["prix"] if creux else None,
            }
        ligne = dict(bougie, sma20=tendances[indice]["sma20"],
                     tendance_daily=tendances[indice]["admissible"],
                     pivot_confirme=";".join(pivot["type"] for pivot in pivots),
                     date_pivot=pivots[0]["date_apparition"] if pivots else None)
        ligne.update({
            "date_sommet": None, "date_confirmation_sommet": None,
            "date_creux": None, "date_confirmation_creux": None,
            "sommet": None, "creux_reference": None, "plus_bas_repli": None,
            "age_seances": None, "retracement": None, "profondeur_respectee": None,
            "sma_respectee": None, "tendance_continue": None, "admissible": False,
            "statut": "AUCUNE_CONFIGURATION", "statut_apres_cloture": "AUCUNE_CONFIGURATION",
            "motif": "AUCUN_SOMMET_REFERENCE_ACTIF",
        })
        if configuration is not None:
            bilan = _evaluer_configuration(configuration, bougies, tendances, indice)
            bilan.pop("indice_sommet")
            ligne.update(bilan)
            if bilan["statut_apres_cloture"] in ("INVALIDE", "EXPIREE"):
                configuration = None
        tableau.append(ligne)
    return tableau


def bougies_fictives():
    """Une hausse inventée, un creux à 100, un sommet à 120 et un repli à 112."""
    bougies = []
    jour = date(2025, 1, 6)
    while len(bougies) < 72:
        if jour.weekday() < 5:
            position = len(bougies)
            cloture = 80.0 + 0.5 * position
            high, low = cloture + 0.5, cloture - 0.5
            if position == 58:
                low = 100.0
            if position == 60:
                high = 120.0
            if position > 60:
                cloture = 114.0 + 0.1 * (position - 61)
                high = 117.0 if position == 61 else (116.0 if position == 62 else 118.0)
                low = PLUS_BAS_DEMO
            bougies.append({"date": jour, "high": high, "low": low, "cloture": cloture})
        jour += timedelta(days=1)
    return bougies


def lire_csv_pullback(chemin, date_limite, symbole="AAPL"):
    """Exige les High et Low fournis : une archive Date/Close ne suffit pas."""
    bougies = []
    with Path(chemin).open(encoding="utf-8-sig", newline="") as fichier:
        entete = fichier.readline()
        fichier.seek(0)
        separateur = ";" if ";" in entete else ","
        lecteur = csv.DictReader(fichier, delimiter=separateur)
        colonnes = lecteur.fieldnames or []
        if not {"Date", "High", "Low", "Close"}.issubset(colonnes):
            raise ValueError(
                "CSV pullback : Date, High, Low et Close sont obligatoires. "
                "Une archive Date/Close reste utilisable pour la tendance uniquement."
            )
        if len(set(colonnes)) != len(colonnes):
            raise ValueError("CSV : noms de colonnes en double.")
        for numero, ligne in enumerate(lecteur, start=2):
            try:
                jour = date.fromisoformat(ligne["Date"].strip())
                if jour > date_limite:
                    continue
                if "Symbol" in ligne and ligne["Symbol"].strip() != symbole:
                    raise ValueError(f"le CSV doit contenir uniquement {symbole}")
                bougies.append({
                    "date": jour,
                    "high": float(ligne["High"].replace(",", ".")),
                    "low": float(ligne["Low"].replace(",", ".")),
                    "cloture": float(ligne["Close"].replace(",", ".")),
                })
            except (ValueError, TypeError, AttributeError) as erreur:
                raise ValueError(f"CSV invalide à la ligne {numero} : {erreur}") from erreur
    return normaliser_bougies(bougies, date_limite)


def telecharger_aapl_pullback(date_limite, symbole="AAPL"):
    """Source Yahoo, gardée pour contrôle ; conserve les vrais High/Low de Yahoo."""
    try:
        import yfinance as yf
    except ImportError:
        raise ValueError("yfinance est absent : installe requirements.txt ou utilise --csv.") from None
    try:
        donnees = yf.download(
            symbole, start=(date_limite - timedelta(days=370)).isoformat(),
            end=(date_limite + timedelta(days=1)).isoformat(), interval="1d",
            auto_adjust=False, back_adjust=False, repair=False, rounding=False,
            keepna=True, prepost=False, ignore_tz=True, multi_level_index=False,
            threads=False, progress=False, timeout=20,
        )
        if donnees is None or donnees.empty:
            raise ValueError("Yahoo n'a renvoyé aucune bougie.")
        if not {"High", "Low", "Close"}.issubset(donnees.columns):
            raise ValueError("Les colonnes High, Low et Close sont absentes de la réponse.")
        bougies = [{"date": instant.date(), "high": ligne["High"],
                    "low": ligne["Low"], "cloture": ligne["Close"]}
                   for instant, ligne in donnees.iterrows()]
    except Exception as erreur:
        raise ValueError(
            f"Téléchargement {symbole} indisponible : {erreur}\n"
            "Solution de secours : --csv chemin\\aapl_daily_hlc.csv "
            "avec Date,High,Low,Close et la même convention de prix."
        ) from erreur
    return normaliser_bougies(bougies, date_limite)


def telecharger_bougies(date_limite, symbole="AAPL", source="alpaca"):
    """Alpaca par défaut ; Yahoo reste disponible pour contrôler une valeur."""
    if source == "yahoo":
        return telecharger_aapl_pullback(date_limite, symbole)
    # Import tardif : source_alpaca utilise lui-même les fonctions de ce fichier.
    from source_alpaca import telecharger_daily_recent
    try:
        bougies = telecharger_daily_recent(date_limite, symbole)
    except ValueError as erreur:
        raise ValueError(
            f"{erreur}\nSolutions de secours : --source yahoo, ou --csv avec une archive."
        ) from None
    return normaliser_bougies(bougies, date_limite)


def afficher_tableau_pullback(tableau, derniers=15):
    """Affiche les chiffres arrondis et les deux états de fin de J10."""
    def prix(valeur):
        return "ND" if valeur is None else f"{valeur:.2f}"

    def booleen(valeur):
        return "ND" if valeur is None else ("OUI" if valeur else "NON")

    print("\nJ est compté depuis l'apparition du sommet ; confirmation à J2, fenêtre J3–J10.")
    print("ND = non disponible. Admis décrit les critères Daily, sans signal d'achat.\n")
    print(f"{'Date':10} {'Sommet J0':10} {'Confirm. J2':11} {'J':>2} "
          f"{'High J0':>8} {'Lref':>8} {'Lmin':>8} {'Repli %':>8} {'Admis':>5} "
          f"{'Bilan Daily':20} Après clôture")
    lignes = tableau if derniers == 0 else tableau[-derniers:]
    for ligne in lignes:
        sommet_date = str(ligne["date_sommet"]) if ligne["date_sommet"] else "ND"
        confirmation = str(ligne["date_confirmation_sommet"]) if ligne["date_confirmation_sommet"] else "ND"
        age = str(ligne["age_seances"]) if ligne["age_seances"] is not None else "ND"
        repli = "ND" if ligne["retracement"] is None else f"{100 * ligne['retracement']:.2f}"
        print(f"{ligne['date']} {sommet_date:10} {confirmation:11} {age:>2} "
              f"{prix(ligne['sommet']):>8} {prix(ligne['creux_reference']):>8} "
              f"{prix(ligne['plus_bas_repli']):>8} {repli:>8} "
              f"{booleen(ligne['admissible']):>5} {ligne['statut']:20} {ligne['statut_apres_cloture']}")
    print(f"\nMotif de la dernière séance : {tableau[-1]['motif']}")
    print("Confirmation et critères Daily sont disponibles après clôture ; aucun déclencheur 1 h n'est simulé.")


def main():
    analyseur = argparse.ArgumentParser(description="Pullback Daily selon SPEC_PULLBACK.md, AAPL par défaut.")
    sources = analyseur.add_mutually_exclusive_group()
    sources.add_argument("--demo", action="store_true", help="Prix fictifs, sans téléchargement.")
    sources.add_argument("--csv", type=Path, help="CSV Daily du titre : Date,High,Low,Close.")
    analyseur.add_argument("--symbole", choices=SYMBOLES, default="AAPL", help="Titre analysé.")
    analyseur.add_argument("--source", choices=sorted(NOMS_SOURCES), default="alpaca",
                           help="Téléchargement : alpaca par défaut, yahoo pour contrôler.")
    analyseur.add_argument("--date", type=date.fromisoformat, help="Date évaluée incluse, AAAA-MM-JJ.")
    analyseur.add_argument("--derniers", type=int, default=15, help="Lignes affichées ; 0 = toutes.")
    analyseur.add_argument("--sortie", type=Path, help="Nouveau CSV complet ; aucun écrasement.")
    options = analyseur.parse_args()
    if options.derniers < 0:
        analyseur.error("--derniers doit être positif ou nul.")
    if options.demo and options.date:
        analyseur.error("--date concerne les données réelles ; retire --demo pour l'utiliser.")
    try:
        identifiant = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        symbole = options.symbole
        if options.demo:
            bougies = bougies_fictives()
            source = "FICTIF : prix inventés, dates illustratives ; aucun cours AAPL"
            convention = "FICTIF : aucune donnée de marché"
            prefixe = "fictif"
        else:
            limite = date_limite_evaluation(options.date)
            bougies = (lire_csv_pullback(options.csv, limite, symbole) if options.csv
                       else telecharger_bougies(limite, symbole, options.source))
            verifier_seances_nasdaq([(bougie["date"], bougie["cloture"]) for bougie in bougies])
            source = (f"CSV fourni ({options.csv}, origine non vérifiée)" if options.csv else
                      f"Données réelles {symbole}, {NOMS_SOURCES[options.source]}")
            convention = CONVENTION_PRIX + " ; même ajustement pour High et Low"
            prefixe = symbole.lower()
            print(f"Titre : {symbole}. Date limite : {limite} ; journée courante à New York exclue.")
        tableau = scanner_pullbacks(bougies)
        print(f"\nSource : {source}\nConvention : {convention}")
        print(f"{len(bougies)} bougies ; dernière séance disponible : {bougies[-1]['date']}")
        afficher_tableau_pullback(tableau, options.derniers)
        if not options.csv and not options.demo:
            archive = DOSSIER_PROJET / "donnees" / f"{prefixe}_{options.source}_daily_hlc_{identifiant}.csv"
            ecrire_csv(archive, [{"Date": bougie["date"], "High": bougie["high"],
                                 "Low": bougie["low"], "Close": bougie["cloture"]}
                                for bougie in bougies], ["Date", "High", "Low", "Close"])
            print(f"Archive High/Low/Close pour fonctionner hors ligne : {archive}")
        sortie = options.sortie or DOSSIER_PROJET / "resultats" / f"{prefixe}_pullback_{identifiant}.csv"
        lignes_export = [dict(ligne, source=source, convention_prix=convention) for ligne in tableau]
        ecrire_csv(sortie, lignes_export, list(lignes_export[0]))
        print(f"Tableau complet ({len(tableau)} lignes) : {sortie}")
        return 0
    except (ValueError, OSError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
