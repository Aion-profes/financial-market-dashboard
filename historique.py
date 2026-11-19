"""Historique long pour le backtest : cours bruts, divisions d'actions, archive figée.

Pourquoi des cours bruts ? Les cours « ajustés » fournis par la source sont arrondis
(au centime, ou à quatre décimales). Avant une division d'actions, cet arrondi peut
transformer une égalité en dépassement et créer un faux signal. Ce module télécharge
donc les cours bruts et les rend continus lui-même, avec le rapport exact de chaque
division, sans arrondi.

Deux séries en sortent, et elles ne se mélangent jamais :
- les cours CONTINUS : cours brut divisé par le facteur de sa date. Ils servent aux
  indicateurs et aux signaux des étapes 1 à 3 ; une division n'y crée aucun saut ;
- les cours RÉELS de l'époque : retrouvés par l'étape 4 pour chaque position, avec le
  même facteur. Ils servent au pas de prix, aux quantités et aux commissions.

Lancer :  python historique.py              télécharge puis fige l'archive (une seule fois)
          python historique.py --verifier   relit l'archive, contrôle ses empreintes, sans réseau
Ce programme ne calcule ni signal ni performance.
"""

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

from etape_01_tendance import DOSSIER_PROJET, SYMBOLES, ecrire_csv
from etape_03_entree_1h import construire_grille, instant_utc
from etape_04_sorties_risque import facteur_de_division
from source_alpaca import DEMI_HEURE, assembler_horaire, jour_de_barre, telecharger_barres


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc
DOSSIER = DOSSIER_PROJET / "donnees" / "historique"
MANIFESTE = "manifeste.json"
COLONNES = ["t", "o", "h", "l", "c"]

# Divisions d'actions : (date d'effet, rapport). Faits publics, vérifiés contre les données
# à chaque téléchargement : un désaccord arrête le programme.
DIVISIONS = {
    "AAPL": ((date(2020, 8, 31), 4),),
    "NVDA": ((date(2021, 7, 20), 4), (date(2024, 6, 10), 10)),
    "AVGO": ((date(2024, 7, 15), 10),),
}

# Périodes du protocole, fixées le 16 novembre 2026 d'après la seule couverture des données,
# avant tout calcul de performance. Elles ne se modifient pas après lecture d'un résultat.
PERIODES = {
    "mise_en_route": (date(2016, 1, 4), date(2016, 3, 31)),
    "developpement": (date(2016, 4, 1), date(2024, 6, 28)),
    "tampon": (date(2024, 7, 1), date(2024, 7, 31)),
    "validation": (date(2024, 8, 1), date(2026, 8, 31)),
}
# L'archive va un mois plus loin : une position entrée fin août doit pouvoir se dénouer.
ARCHIVE_DEBUT, ARCHIVE_FIN = date(2016, 1, 4), date(2026, 9, 30)
TOLERANCE_COHERENCE = 0.005   # 0,5 % d'écart entre la bougie Daily et les barres de 30 minutes


def minuit(jour):
    return datetime.combine(jour, time(0, 0), NEW_YORK)


def jour_new_york(barre):
    return instant_utc(barre["t"]).astimezone(NEW_YORK).date()


def rendre_continu(barres, divisions):
    """Cours continus : chaque cours brut est divisé par le facteur de division de sa date."""
    continues = []
    for barre in barres:
        facteur = facteur_de_division(divisions, jour_new_york(barre))
        continues.append({"t": barre["t"], **{champ: barre[champ] / facteur for champ in ("o", "h", "l", "c")}})
    return continues


def detecter_divisions(brutes, ajustees):
    """Divisions visibles dans les données : le rapport « brut / ajusté » change ce jour-là."""
    par_jour = {jour_de_barre(barre): barre["c"] for barre in ajustees}
    divisions, precedent = [], None
    for barre in sorted(brutes, key=lambda ligne: ligne["t"]):
        jour = jour_de_barre(barre)
        if jour not in par_jour:
            continue
        rapport = barre["c"] / par_jour[jour]
        if precedent is not None and abs(rapport / precedent - 1) > 0.01:
            divisions.append((jour, round(precedent / rapport)))
        precedent = rapport
    return tuple(divisions)


def verifier_divisions(symbole, brutes, ajustees, debut, fin):
    """Refuse de continuer si la table DIVISIONS et les données ne racontent pas la même histoire."""
    attendues = tuple(division for division in DIVISIONS[symbole] if debut < division[0] <= fin)
    constatees = detecter_divisions(brutes, ajustees)
    if constatees != attendues:
        raise ValueError(f"Divisions d'actions de {symbole} : table {attendues}, données {constatees}. "
                         "Corriger la table DIVISIONS avant tout calcul.")
    return attendues


def controler_coherence(daily, demi_heures, grille):
    """Séances où la bougie Daily et les barres de 30 minutes ne donnent pas le même plus haut ou plus bas.

    Une valeur aberrante dans la bougie Daily (transaction hors séance, erreur de saisie) créerait
    un faux sommet. Ce contrôle la repère ; il ne corrige rien.
    """
    seances, bornes = {}, {}
    for creneau in grille:
        debut, fin = bornes.get(creneau["session"], (creneau["debut"], creneau["fin"]))
        bornes[creneau["session"]] = (min(debut, creneau["debut"]), max(fin, creneau["fin"]))
    for barre in demi_heures:
        instant = instant_utc(barre["t"])
        jour = instant.astimezone(NEW_YORK).date()
        if jour in bornes and bornes[jour][0] <= instant < bornes[jour][1]:
            haut, bas = seances.get(jour, (barre["h"], barre["l"]))
            seances[jour] = (max(haut, barre["h"]), min(bas, barre["l"]))
    ecarts = []
    for barre in daily:
        jour = jour_de_barre(barre)
        if jour not in seances:
            continue
        haut, bas = seances[jour]
        ecart = max(abs(barre["h"] / haut - 1), abs(barre["l"] / bas - 1))
        if ecart > TOLERANCE_COHERENCE:
            ecarts.append({"date": jour, "daily_haut": barre["h"], "daily_bas": barre["l"],
                           "intraday_haut": haut, "intraday_bas": bas, "ecart": ecart})
    return ecarts


def corriger_daily(daily, ecarts):
    """Applique la règle de nettoyage, fixée avant tout calcul de performance.

    Sur une séance signalée par controler_coherence, le plus haut (ou le plus bas) Daily qui
    s'écarte de plus de 0,5 % est remplacé par celui des barres de 30 minutes de la séance
    régulière. L'ouverture et la clôture ne sont jamais touchées. Renvoie les bougies
    corrigées et la liste des corrections, pour qu'aucune ne soit silencieuse.
    """
    par_jour = {ecart["date"]: ecart for ecart in ecarts}
    corrigees, corrections = [], []
    for barre in daily:
        ecart = par_jour.get(jour_de_barre(barre))
        if ecart is None:
            corrigees.append(barre)
            continue
        nouvelle = dict(barre)
        for champ, intraday in (("h", ecart["intraday_haut"]), ("l", ecart["intraday_bas"])):
            if abs(barre[champ] / intraday - 1) > TOLERANCE_COHERENCE:
                nouvelle[champ] = intraday
                corrections.append({"date": ecart["date"], "champ": "plus haut" if champ == "h" else "plus bas",
                                    "avant": barre[champ], "apres": intraday})
        if not nouvelle["l"] <= nouvelle["c"] <= nouvelle["h"]:
            raise ValueError(f"Séance du {ecart['date']} : la clôture Daily sort de la fourchette des barres de "
                             "30 minutes. Cas non prévu par la règle de nettoyage : à examiner à la main.")
        corrigees.append(nouvelle)
    return corrigees, corrections


def daily_au_format_du_projet(daily):
    """Bougies Daily au format des étapes 1 à 4, avec leur ouverture."""
    return [{"date": jour_de_barre(barre), "ouverture": barre["o"], "high": barre["h"],
             "low": barre["l"], "cloture": barre["c"]} for barre in daily]


def telecharger_brut(symbole, debut=ARCHIVE_DEBUT, fin=ARCHIVE_FIN, maintenant=None):
    """Télécharge les barres brutes (Daily et 30 minutes de séance) et vérifie les divisions."""
    maintenant = datetime.now(UTC) if maintenant is None else maintenant
    arrivee = minuit(fin + timedelta(days=1))   # fin incluse
    daily = telecharger_barres("1Day", minuit(debut), arrivee, maintenant, symbole, ajustement="raw")
    ajustees = telecharger_barres("1Day", minuit(debut), arrivee, maintenant, symbole)
    verifier_divisions(symbole, daily, ajustees, debut, fin)
    grille = construire_grille(debut, fin)
    moities = set()
    for creneau in grille:
        instant = creneau["debut"]
        while instant < creneau["fin"]:
            moities.add(instant)
            instant += DEMI_HEURE
    demi_heures = []
    for annee in range(debut.year, fin.year + 1):
        depart = max(minuit(debut), minuit(date(annee, 1, 1)))
        terme = min(arrivee, minuit(date(annee + 1, 1, 1)))
        if terme <= depart:
            continue
        barres = telecharger_barres("30Min", depart, terme, maintenant, symbole, ajustement="raw")
        # Seules les demi-heures de la séance régulière sont gardées.
        demi_heures.extend(barre for barre in barres if instant_utc(barre["t"]) in moities)
    return daily, demi_heures


def empreinte(chemin):
    """Empreinte SHA-256 d'un fichier : elle change au moindre octet modifié."""
    with open(chemin, "rb") as fichier:
        return hashlib.sha256(fichier.read()).hexdigest()


def chemins(symbole, dossier=DOSSIER):
    return (dossier / f"{symbole.lower()}_1day_brut.csv", dossier / f"{symbole.lower()}_30min_brut.csv")


def figer_archive(donnees, dossier=DOSSIER, debut=ARCHIVE_DEBUT, fin=ARCHIVE_FIN, cree_le=None):
    """Écrit l'archive et son manifeste. Refuse d'écraser : une archive figée ne se réécrit pas.

    donnees : {symbole: (barres Daily brutes, barres de 30 minutes brutes)}.
    """
    if (dossier / MANIFESTE).exists():
        raise ValueError(f"Une archive existe déjà dans {dossier} : elle est figée et n'est pas réécrite.")
    dossier.mkdir(parents=True, exist_ok=True)
    fichiers = {}
    for symbole, (daily, demi_heures) in donnees.items():
        for chemin, barres in zip(chemins(symbole, dossier), (daily, demi_heures)):
            ecrire_csv(chemin, [{colonne: barre[colonne] for colonne in COLONNES} for barre in barres], COLONNES)
            fichiers[chemin.name] = {"lignes": len(barres), "sha256": empreinte(chemin)}
    manifeste = {
        "cree_le": (cree_le or datetime.now(UTC)).isoformat(), "source": "Alpaca, flux SIP, cours bruts",
        "debut": debut.isoformat(), "fin": fin.isoformat(),
        "divisions": {symbole: [[jour.isoformat(), rapport] for jour, rapport in DIVISIONS.get(symbole, ())]
                      for symbole in donnees},
        "periodes": {nom: [premier.isoformat(), dernier.isoformat()] for nom, (premier, dernier) in PERIODES.items()},
        "fichiers": fichiers,
    }
    with open(dossier / MANIFESTE, "w", encoding="utf-8") as fichier:
        json.dump(manifeste, fichier, ensure_ascii=False, indent=2)
    return manifeste


def lire_manifeste(dossier=DOSSIER):
    try:
        with open(dossier / MANIFESTE, encoding="utf-8") as fichier:
            return json.load(fichier)
    except (OSError, ValueError) as erreur:
        raise ValueError(f"Archive absente ou illisible dans {dossier} : {erreur}") from None


def lire_archive(symbole, dossier=DOSSIER):
    """Relit les barres brutes d'un titre, après avoir contrôlé l'empreinte de chaque fichier."""
    manifeste = lire_manifeste(dossier)
    resultat = []
    for chemin in chemins(symbole, dossier):
        attendu = manifeste["fichiers"].get(chemin.name)
        if attendu is None or not chemin.exists():
            raise ValueError(f"Archive incomplète : {chemin.name} manque.")
        if empreinte(chemin) != attendu["sha256"]:
            raise ValueError(f"Archive modifiée depuis son gel : {chemin.name} n'a plus la même empreinte.")
        with open(chemin, encoding="utf-8-sig", newline="") as fichier:
            resultat.append([{"t": ligne["t"], **{champ: float(ligne[champ]) for champ in ("o", "h", "l", "c")}}
                             for ligne in csv.DictReader(fichier)])
    return tuple(resultat)


def preparer_historique(symbole, instant, dossier=DOSSIER):
    """Séries continues d'un titre, prêtes pour les étapes 1 à 4, jusqu'à l'instant donné.

    Renvoie un dictionnaire : daily, horaires, divisions, creneaux_incomplets, corrections.
    """
    daily, demi_heures = lire_archive(symbole, dossier)
    divisions = DIVISIONS.get(symbole, ())
    limite = instant_utc(instant)
    grille = construire_grille(ARCHIVE_DEBUT, limite.astimezone(NEW_YORK).date())
    # Nettoyage sur les cours bruts, avant de les rendre continus.
    daily, corrections = corriger_daily(daily, controler_coherence(daily, demi_heures, grille))
    continus = daily_au_format_du_projet(rendre_continu(daily, divisions))
    horaires, incomplets, _ = assembler_horaire(
        rendre_continu(demi_heures, divisions), grille, minuit(ARCHIVE_DEBUT), limite, limite, limite)
    return {"symbole": symbole, "daily": continus, "horaires": horaires, "divisions": divisions,
            "creneaux_incomplets": incomplets, "corrections": corrections}


def rapport_de_couverture(symbole, daily, demi_heures, debut=ARCHIVE_DEBUT, fin=ARCHIVE_FIN):
    """Compte ce que l'archive contient, par période du protocole. Aucun signal, aucune performance."""
    grille = construire_grille(debut, fin)
    seances = sorted({creneau["session"] for creneau in grille})
    presentes = {jour_de_barre(barre) for barre in daily}
    fin_consultable = minuit(fin + timedelta(days=1))
    _, incomplets, _ = assembler_horaire(demi_heures, grille, minuit(debut), fin_consultable,
                                         fin_consultable, fin_consultable)
    trouees = sorted({creneau["debut"].astimezone(NEW_YORK).date() for creneau in incomplets})
    ecarts = controler_coherence(daily, demi_heures, grille)
    par_periode = {}
    for nom, (premier, dernier) in PERIODES.items():
        dans = [jour for jour in seances if premier <= jour <= dernier]
        par_periode[nom] = {
            "seances": len(dans), "daily_manquantes": [jour for jour in dans if jour not in presentes],
            "horaires_trouees": [jour for jour in trouees if premier <= jour <= dernier],
            "incoherences": [ecart for ecart in ecarts if premier <= ecart["date"] <= dernier],
        }
    return {"symbole": symbole, "daily": len(daily), "demi_heures": len(demi_heures),
            "premiere": min(presentes), "derniere": max(presentes), "periodes": par_periode}


def afficher_rapport(rapport):
    print(f"\n=== {rapport['symbole']} : {rapport['daily']} bougies Daily du {rapport['premiere']} au "
          f"{rapport['derniere']}, {rapport['demi_heures']} barres de 30 minutes ===")
    divisions = ", ".join(f"{jour} (1 pour {rapport_division})" for jour, rapport_division in DIVISIONS[rapport["symbole"]])
    print(f"Divisions d'actions vérifiées contre les données : {divisions}")
    for nom, bilan in rapport["periodes"].items():
        premier, dernier = PERIODES[nom]
        print(f"  {nom:14s} {premier} – {dernier} : {bilan['seances']:4d} séances ; Daily manquantes "
              f"{len(bilan['daily_manquantes'])} ; séances horaires trouées {len(bilan['horaires_trouees'])} ; "
              f"incohérences Daily / 30 minutes {len(bilan['incoherences'])}")
        for ecart in bilan["incoherences"][:12]:
            print(f"      {ecart['date']} : Daily {ecart['daily_bas']}–{ecart['daily_haut']}, "
                  f"30 minutes {ecart['intraday_bas']}–{ecart['intraday_haut']} (écart {100 * ecart['ecart']:.1f} %)")
        if bilan["horaires_trouees"]:
            print(f"      séances trouées : {', '.join(str(jour) for jour in bilan['horaires_trouees'][:12])}")


def main():
    analyseur = argparse.ArgumentParser(description="Archive figée de l'historique long (aucune performance calculée).")
    analyseur.add_argument("--verifier", action="store_true", help="Relit l'archive existante, sans réseau.")
    options = analyseur.parse_args()
    try:
        if options.verifier:
            manifeste = lire_manifeste()
            donnees = {symbole: lire_archive(symbole) for symbole in SYMBOLES}
            print(f"Archive du {manifeste['cree_le']} : empreintes conformes.")
        else:
            print(f"Téléchargement des cours bruts du {ARCHIVE_DEBUT} au {ARCHIVE_FIN} (quelques minutes)…")
            donnees = {symbole: telecharger_brut(symbole) for symbole in SYMBOLES}
            manifeste = figer_archive(donnees)
            print(f"Archive figée dans {DOSSIER} le {manifeste['cree_le']}.")
        for symbole, (daily, demi_heures) in donnees.items():
            afficher_rapport(rapport_de_couverture(symbole, daily, demi_heures))
            _, corrections = corriger_daily(daily, controler_coherence(
                daily, demi_heures, construire_grille(ARCHIVE_DEBUT, ARCHIVE_FIN)))
            for correction in corrections:
                print(f"  Nettoyage {correction['date']} : {correction['champ']} Daily "
                      f"{correction['avant']} -> {correction['apres']}")
        print("\nAucun signal ni aucune performance n'ont été calculés.")
        return 0
    except (ValueError, OSError) as erreur:
        print(f"ERREUR : {erreur}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
