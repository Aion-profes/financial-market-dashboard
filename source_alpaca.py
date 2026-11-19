"""Source de données Alpaca : Daily et horaire, source par défaut des étapes 1 à 3.

Ce module télécharge, assemble et archive. Il n'utilise que la bibliothèque
standard pour parler à l'API (urllib, json).
Référence : https://docs.alpaca.markets/reference/stockbars
"""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from etape_01_tendance import DOSSIER_PROJET, SYMBOLES, ecrire_csv
from etape_02_pullback import normaliser_bougies
from etape_03_entree_1h import construire_grille, instant_utc, normaliser_horaires


ADRESSE = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLE = "AAPL"
AJUSTEMENT = "split"      # convention du projet : splits oui, dividendes non
FLUX = "sip"              # jamais remplacé en silence par un autre flux
VARIABLE_ID = "APCA_API_KEY_ID"
VARIABLE_SECRET = "APCA_API_SECRET_KEY"
RETARD_IMPOSE = timedelta(minutes=15)   # offre gratuite : 15 dernières minutes interdites
# Si l'horloge du PC avance de quelques secondes, « maintenant moins 15 minutes »
# tombe encore dans la zone interdite et Alpaca répond 403 : on garde une marge.
MARGE_HORLOGE = timedelta(minutes=1)
RETARD_TOTAL = RETARD_IMPOSE + MARGE_HORLOGE
DEMI_HEURE = timedelta(minutes=30)
JOURS_HISTORIQUE = 370    # environ un an de Daily, comme le téléchargement Yahoo
LIMITE_PAR_PAGE = 10000   # maximum accepté par l'API
PAGES_MAXIMUM = 1000      # garde-fou : une pagination sans fin est une anomalie
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def lire_cles():
    """Lit les deux clés dans l'environnement ; elles ne sont jamais affichées."""
    identifiant = os.environ.get(VARIABLE_ID, "").strip()
    secret = os.environ.get(VARIABLE_SECRET, "").strip()
    absentes = [nom for nom, valeur in ((VARIABLE_ID, identifiant), (VARIABLE_SECRET, secret))
                if not valeur]
    if absentes:
        raise ValueError(
            "Clés Alpaca absentes : définis " + " et ".join(absentes)
            + " dans les variables d'environnement Windows, puis rouvre PowerShell."
        )
    return identifiant, secret


def masquer_cles(texte, cles):
    """Retire les clés d'un texte avant de l'afficher, par précaution."""
    for cle in cles:
        if cle:
            texte = texte.replace(cle, "***")
    return texte


def borner_fin(fin, maintenant=None):
    """La fin demandée ne dépasse jamais « maintenant moins 16 minutes » (15 + marge)."""
    if maintenant is None:
        maintenant = datetime.now(UTC)
    return min(instant_utc(fin), instant_utc(maintenant) - RETARD_TOTAL)


def telecharger_barres(intervalle, debut, fin, maintenant=None, symbole=SYMBOLE, ajustement=AJUSTEMENT):
    """Renvoie toutes les barres du titre sur la période, en suivant chaque page.

    intervalle : « 1Day » ou « 30Min ». debut et fin : instants avec fuseau.
    Chaque barre est le dictionnaire brut d'Alpaca : t, o, h, l, c, etc.
    ajustement : « split » partout dans le projet ; « raw » sert seulement à
    l'inventaire, pour repérer les divisions d'actions.
    """
    cles = lire_cles()
    debut = instant_utc(debut)
    fin = borner_fin(fin, maintenant)
    if fin <= debut:
        raise ValueError("Période Alpaca vide : la fin (bornée à 16 minutes avant maintenant) précède le début.")
    parametres = {
        "symbols": symbole, "timeframe": intervalle,
        "start": debut.isoformat(), "end": fin.isoformat(),
        "limit": LIMITE_PAR_PAGE, "adjustment": ajustement, "feed": FLUX, "sort": "asc",
    }
    barres = []
    jeton = None
    for _ in range(PAGES_MAXIMUM):
        if jeton:
            parametres["page_token"] = jeton
        requete = urllib.request.Request(
            ADRESSE + "?" + urllib.parse.urlencode(parametres),
            headers={"APCA-API-KEY-ID": cles[0], "APCA-API-SECRET-KEY": cles[1],
                     "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(requete, timeout=20) as reponse:
                contenu = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as erreur:
            # Le message exact d'Alpaca est conservé : il dit par exemple si « sip » est refusé.
            corps = erreur.read().decode("utf-8", errors="replace")
            message = masquer_cles(f"Alpaca a répondu HTTP {erreur.code} : {corps}", cles)
            raise ValueError(message) from None
        except (urllib.error.URLError, OSError, ValueError) as erreur:
            message = masquer_cles(f"Téléchargement Alpaca impossible : {erreur}", cles)
            raise ValueError(message) from None
        if not isinstance(contenu, dict) or "bars" not in contenu:
            raise ValueError("Réponse Alpaca inattendue : champ « bars » absent.")
        # Une page peut être vide pour notre symbole et annoncer quand même une suite.
        barres.extend((contenu["bars"] or {}).get(symbole) or [])
        jeton = contenu.get("next_page_token")
        if not jeton:
            return barres
    raise ValueError(f"Pagination Alpaca interrompue après {PAGES_MAXIMUM} pages : archive incomplète refusée.")


def barres_en_daily(barres):
    """Convertit des barres 1Day au format de l'étape 2 : date, high, low, cloture."""
    bougies = []
    for barre in barres:
        # L'horodatage Daily est minuit à New York : on lit donc la date dans ce fuseau.
        bougies.append({"date": jour_de_barre(barre), "high": barre["h"],
                        "low": barre["l"], "cloture": barre["c"]})
    return normaliser_bougies(bougies)


def assembler_horaire(barres, grille, debut, fin, instant_evaluation=None, fin_consultable=None):
    """Assemble des barres de 30 minutes sur la grille horaire du projet.

    Renvoie trois listes : les bougies, les créneaux incomplets (aucune bougie
    fabriquée) et les débuts des barres hors séance ignorées.

    fin_consultable : dernier instant dont Alpaca a pu fournir les prix. Une
    moitié qui se termine après est encore partielle : son créneau ne garde
    alors que son Open, déjà définitif, et jamais ses High, Low et Close.
    """
    debut, fin = instant_utc(debut), instant_utc(fin)
    if fin_consultable is not None:
        fin_consultable = instant_utc(fin_consultable)
    par_debut = {}
    for barre in barres:
        instant = instant_utc(barre["t"])
        if instant in par_debut:
            raise ValueError(f"Barre Alpaca en double à {instant.isoformat()}.")
        par_debut[instant] = barre
    bougies, incomplets, utilisees = [], [], set()
    for creneau in grille:
        if creneau["debut"] < debut or creneau["debut"] >= fin:
            continue
        # Un créneau de 60 minutes attend deux moitiés ; la dernière tranche, une seule.
        attendues = []
        moitie = creneau["debut"]
        while moitie < creneau["fin"]:
            attendues.append(moitie)
            moitie += DEMI_HEURE
        presentes = [par_debut[instant] for instant in attendues if instant in par_debut
                     and (fin_consultable is None or instant + DEMI_HEURE <= fin_consultable)]
        utilisees.update(instant for instant in attendues if instant in par_debut)
        if len(presentes) < len(attendues):
            if fin_consultable is not None and creneau["fin"] > fin_consultable:
                # Créneau encore en cours pour Alpaca : ce n'est pas une anomalie.
                if attendues[0] in par_debut:
                    bougies.append({"debut": creneau["debut"],
                                    "ouverture": par_debut[attendues[0]]["o"],
                                    "high": None, "low": None, "cloture": None})
                continue
            incomplets.append({
                "debut": creneau["debut"], "fin": creneau["fin"],
                "manquantes": [instant for instant in attendues if instant not in par_debut],
            })
            continue
        bougies.append({
            "debut": creneau["debut"],
            "ouverture": presentes[0]["o"],
            "high": max(barre["h"] for barre in presentes),
            "low": min(barre["l"] for barre in presentes),
            "cloture": presentes[-1]["c"],
        })
    hors_seance = sorted(instant for instant in par_debut if instant not in utilisees)
    if instant_evaluation is None:
        instant_evaluation = datetime.now(UTC)
    return normaliser_horaires(bougies, instant_evaluation, grille), incomplets, hors_seance


def minutes_des_barres(barres):
    """Compte les barres par minute de début : on attend seulement 0 et 30."""
    comptes = {}
    for barre in barres:
        minute = instant_utc(barre["t"]).minute
        comptes[minute] = comptes.get(minute, 0) + 1
    return dict(sorted(comptes.items()))


def jour_de_barre(barre):
    """Date de séance d'une barre 1Day, lue à New York."""
    return instant_utc(barre["t"]).astimezone(NEW_YORK).date()


def telecharger_barres_daily(premier_jour, dernier_jour, maintenant=None, symbole=SYMBOLE):
    """Barres 1Day brutes (avec leur Open), sans la journée encore partielle."""
    debut = datetime.combine(premier_jour, time(0, 0), NEW_YORK)
    fin = datetime.combine(dernier_jour, time(23, 59, 59), NEW_YORK)
    barres = telecharger_barres("1Day", debut, fin, maintenant, symbole)
    # La barre du jour n'est gardée que si sa séance est terminée et consultable :
    # avant cela, Alpaca renverrait une journée encore partielle.
    consultable = borner_fin(fin, maintenant)
    jour = consultable.astimezone(NEW_YORK).date()
    seance = construire_grille(jour, jour)
    if seance and seance[-1]["fin"] <= consultable:
        return barres
    return [barre for barre in barres if jour_de_barre(barre) != jour]


def telecharger_daily(premier_jour, dernier_jour, maintenant=None, symbole=SYMBOLE):
    """Barres 1Day du premier au dernier jour inclus, au format de l'étape 2."""
    return barres_en_daily(telecharger_barres_daily(premier_jour, dernier_jour, maintenant, symbole))


def telecharger_daily_recent(date_limite, symbole=SYMBOLE, maintenant=None):
    """Environ un an de Daily jusqu'à date_limite incluse, pour les étapes 1 à 3."""
    premier_jour = date_limite - timedelta(days=JOURS_HISTORIQUE)
    return telecharger_daily(premier_jour, date_limite, maintenant, symbole)


def telecharger_horaire(debut, fin, grille, maintenant=None, symbole=SYMBOLE, instant_evaluation=None):
    """Barres 30Min assemblées ; renvoie aussi les barres brutes pour le rapport."""
    barres = telecharger_barres("30Min", debut, fin, maintenant, symbole)
    bougies, incomplets, hors_seance = assembler_horaire(
        barres, grille, debut, fin, instant_evaluation, borner_fin(fin, maintenant))
    return bougies, incomplets, hors_seance, barres


def archiver_daily(bougies, identifiant, symbole=SYMBOLE):
    """Écrit Date,High,Low,Close dans donnees/ ; ecrire_csv refuse d'écraser."""
    chemin = DOSSIER_PROJET / "donnees" / f"{symbole.lower()}_alpaca_daily_hlc_{identifiant}.csv"
    ecrire_csv(chemin, [{"Date": bougie["date"], "High": bougie["high"],
                         "Low": bougie["low"], "Close": bougie["cloture"]}
                        for bougie in bougies], ["Date", "High", "Low", "Close"])
    return chemin


def archiver_horaire(bougies, identifiant, symbole=SYMBOLE):
    """Écrit Datetime,Open,High,Low,Close avec des instants ISO en UTC."""
    chemin = DOSSIER_PROJET / "donnees" / f"{symbole.lower()}_alpaca_1h_{identifiant}.csv"
    ecrire_csv(chemin, [{"Datetime": bougie["debut"].isoformat(), "Open": bougie["ouverture"],
                         "High": bougie["high"], "Low": bougie["low"], "Close": bougie["cloture"]}
                        for bougie in bougies], ["Datetime", "Open", "High", "Low", "Close"])
    return chemin


def afficher_rapport_horaire(barres, incomplets, hors_seance):
    """Faits observés sur les barres reçues, sans interprétation."""
    print(f"Barres 30Min reçues : {len(barres)} ; minutes de début observées : {minutes_des_barres(barres)}")
    print(f"Barres hors séance ignorées : {len(hors_seance)}")
    print(f"Créneaux incomplets (aucune bougie produite) : {len(incomplets)}")
    for creneau in incomplets:
        debut = creneau["debut"].astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M")
        manquantes = ", ".join(instant.astimezone(NEW_YORK).strftime("%H:%M")
                               for instant in creneau["manquantes"])
        print(f"  {debut} New York — moitié(s) absente(s) : {manquantes}")


def main():
    analyseur = argparse.ArgumentParser(description="Télécharge et archive un titre depuis Alpaca.")
    analyseur.add_argument("--debut", type=date.fromisoformat, required=True, help="Premier jour inclus, AAAA-MM-JJ.")
    analyseur.add_argument("--fin", type=date.fromisoformat, required=True, help="Dernier jour inclus, AAAA-MM-JJ.")
    analyseur.add_argument("--symbole", choices=SYMBOLES, default=SYMBOLE, help="Titre téléchargé.")
    options = analyseur.parse_args()
    try:
        identifiant = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        symbole = options.symbole
        daily = telecharger_daily(options.debut, options.fin, symbole=symbole)
        grille = construire_grille(options.debut, options.fin)
        if not grille:
            raise ValueError("Aucune séance NASDAQ dans cette période.")
        bougies, incomplets, hors_seance, barres = telecharger_horaire(
            grille[0]["debut"], grille[-1]["fin"], grille, symbole=symbole)
        print(f"Source : Alpaca, {symbole}, flux {FLUX}, ajustement {AJUSTEMENT}")
        print(f"Daily : {len(daily)} bougies ; horaire : {len(bougies)} bougies assemblées")
        afficher_rapport_horaire(barres, incomplets, hors_seance)
        print(f"Archive Daily : {archiver_daily(daily, identifiant, symbole)}")
        print(f"Archive horaire : {archiver_horaire(bougies, identifiant, symbole)}")
        return 0
    except (ValueError, OSError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
