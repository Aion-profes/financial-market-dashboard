"""Taux de change EUR/USD : taux de référence quotidiens de la Banque centrale européenne.

Ce taux sert à VALORISER la simulation en EUR. Ce n'est ni un prix d'exécution,
ni le taux qu'appliquerait un courtier : la BCE le publie « pour information
seulement » et déconseille de s'en servir pour des transactions.
Règles : SPEC_SORTIES_RISQUE.md, section 8.

Sens du taux. La BCE écrit « 1 EUR = x USD ». Convertir des USD en EUR, c'est
donc DIVISER par x : avec x = 1,25, 100 USD valent 100 / 1,25 = 80 EUR.
"""

import csv
from datetime import date, datetime, time, timedelta
import io
import ssl
import urllib.error
import urllib.request
import zipfile
from zoneinfo import ZoneInfo

from etape_01_tendance import DOSSIER_PROJET, ecrire_csv
from etape_03_entree_1h import instant_utc


ADRESSE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
FRANCFORT = ZoneInfo("Europe/Berlin")
# La BCE annonce une mise à jour « vers 16:00 CET » et le fichier ne contient que des dates :
# l'heure réelle de chaque publication passée est inconnue. Convention prudente : le taux daté
# d'un jour n'est utilisé qu'à partir de 18:00 à Francfort (midi à New York la plupart de l'année).
# Cette marge couvre un retard de publication et les deux lectures possibles de « CET » en été.
HEURE_DISPONIBILITE = time(18, 0)
AGE_MAXIMUM = timedelta(days=7)     # au-delà, le dernier taux est jugé trop ancien


def lire_taux(texte):
    """Lit le fichier de la BCE (colonnes Date, USD, …) ; renvoie {date: USD pour 1 EUR}."""
    taux = {}
    for ligne in csv.DictReader(io.StringIO(texte)):
        valeur = (ligne.get("USD") or "").strip()
        if not valeur or valeur == "N/A":
            continue   # jour sans cotation : aucun taux n'est inventé
        try:
            jour, cours = date.fromisoformat(ligne["Date"].strip()), float(valeur)
        except (KeyError, ValueError) as erreur:
            raise ValueError(f"Fichier de taux BCE illisible : {erreur}") from None
        if cours <= 0:
            raise ValueError(f"Taux BCE invalide le {jour} : {valeur}")
        taux[jour] = cours
    if not taux:
        raise ValueError("Fichier de taux BCE vide ou sans colonne USD.")
    return taux


def telecharger_taux():
    """Télécharge tout l'historique EUR/USD de la BCE (un fichier compressé)."""
    try:
        import certifi   # certificats à jour : ceux de Windows ne suffisent pas pour ce site
        contexte = ssl.create_default_context(cafile=certifi.where())
        requete = urllib.request.Request(ADRESSE, headers={"User-Agent": "python-urllib"})
        with urllib.request.urlopen(requete, timeout=30, context=contexte) as reponse:
            archive = zipfile.ZipFile(io.BytesIO(reponse.read()))
        return lire_taux(archive.read(archive.namelist()[0]).decode("utf-8"))
    except (urllib.error.URLError, OSError, zipfile.BadZipFile, IndexError) as erreur:
        raise ValueError(
            f"Taux de change BCE indisponibles : {erreur}\n"
            "Solution de secours : --csv-taux avec une archive bce_eurusd_*.csv."
        ) from None


def instant_de_disponibilite(jour):
    """Moment à partir duquel la simulation s'autorise le taux daté de ce jour (convention)."""
    return datetime.combine(jour, HEURE_DISPONIBILITE, FRANCFORT)


def taux_de_reference(taux, instant):
    """Dernier taux réputé disponible à cet instant ; None s'il n'y en a pas ou s'il est trop ancien.

    Renvoie un dictionnaire qui nomme le sens de chaque valeur :
    usd_par_eur (la cotation de la BCE) et eur_par_usd (son inverse).
    Un jour sans publication (week-end, jour férié TARGET) garde le dernier taux publié.
    """
    limite = instant_utc(instant)
    disponibles = [jour for jour in taux if instant_de_disponibilite(jour) <= limite]
    if not disponibles:
        return None
    jour = max(disponibles)
    if limite - instant_de_disponibilite(jour) > AGE_MAXIMUM:
        return None
    return {"jour": jour, "usd_par_eur": taux[jour], "eur_par_usd": 1 / taux[jour],
            "disponible_depuis": instant_de_disponibilite(jour)}


def taux_eur_par_usd(taux, instant):
    """Valeur en EUR de 1 USD au dernier taux disponible ; None s'il manque."""
    cotation = taux_de_reference(taux, instant)
    return None if cotation is None else cotation["eur_par_usd"]


def convertisseur(taux):
    """Renvoie la fonction « instant -> taux de référence » attendue par l'étape 4."""
    return lambda instant: taux_de_reference(taux, instant)


def archiver_taux(taux, identifiant):
    """Écrit Date,USD_par_EUR dans donnees/ ; ecrire_csv refuse d'écraser."""
    chemin = DOSSIER_PROJET / "donnees" / f"bce_eurusd_{identifiant}.csv"
    ecrire_csv(chemin, [{"Date": jour, "USD_par_EUR": taux[jour]} for jour in sorted(taux)],
               ["Date", "USD_par_EUR"])
    return chemin


def lire_csv_taux(chemin):
    """Relit une archive bce_eurusd_*.csv, pour travailler hors ligne."""
    with open(chemin, encoding="utf-8-sig", newline="") as fichier:
        texte = fichier.read().replace("USD_par_EUR", "USD")
    return lire_taux(texte)
