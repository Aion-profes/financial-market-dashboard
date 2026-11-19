"""Enchaîne les vérifications de MISSION_ALPACA.md et garde toute la sortie dans un fichier.

À lancer avec le bouton « Run Python File » de VS Code ou :
    python lancer_mission_alpaca.py
Aucune clé n'est lue ni affichée ici : les programmes appelés s'en chargent.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys


DOSSIER = Path(__file__).resolve().parent
YAHOO_DAILY = DOSSIER / "donnees" / "aapl_entree_daily_20261113_150143_329817.csv"
YAHOO_HORAIRE = DOSSIER / "donnees" / "aapl_1h_20261113_150143_329817.csv"
INSTANT = "2026-11-13T15:01:43+00:00"
DEBUT = "2026-10-14"


def executer(titre, arguments, journal):
    """Lance un programme du projet avec le même Python et recopie sa sortie."""
    environnement = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    resultat = subprocess.run(
        [sys.executable] + [str(argument) for argument in arguments],
        cwd=DOSSIER, env=environnement, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    texte = (f"\n===== {titre} (code de sortie {resultat.returncode}) =====\n"
             + resultat.stdout + resultat.stderr)
    journal.write(texte)
    journal.flush()
    print(texte.encode("ascii", errors="replace").decode("ascii"))
    return resultat


def chemin_annonce(sortie, etiquette):
    """Retrouve dans la sortie la ligne « étiquette : chemin »."""
    for ligne in sortie.splitlines():
        if ligne.startswith(etiquette + " : "):
            return Path(ligne.split(" : ", 1)[1].strip())
    return None


def rejouer(nom, daily, horaire, identifiant, journal):
    sortie = DOSSIER / "resultats" / f"rejeu_{nom}_{identifiant}.csv"
    executer(f"Rejeu étape 3 sur {nom}", [
        "etape_03_entree_1h.py", "--csv-daily", daily, "--csv-horaire", horaire,
        "--instant", INSTANT, "--debut", DEBUT, "--derniers", "3", "--sortie", sortie,
    ], journal)
    return sortie


def main():
    identifiant = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    chemin_journal = DOSSIER / "resultats" / f"mission_alpaca_{identifiant}.log"
    chemin_journal.parent.mkdir(parents=True, exist_ok=True)
    with chemin_journal.open("x", encoding="utf-8") as journal:
        journal.write(f"Python {sys.version}\n{sys.executable}\n")
        executer("Tests", ["-m", "unittest", "discover"], journal)
        comparaison = executer("Comparaison Alpaca / Yahoo", ["comparer_sources.py"], journal)
        alpaca_daily = chemin_annonce(comparaison.stdout, "Archive Daily")
        alpaca_horaire = chemin_annonce(comparaison.stdout, "Archive horaire")
        if comparaison.returncode != 0 or not alpaca_daily or not alpaca_horaire:
            journal.write("\nArrêt : pas d'archives Alpaca, donc pas de rejeu de l'étape 3.\n")
            print(f"Arret avant le rejeu. Journal : {chemin_journal}")
            return 1
        rejeu_yahoo = rejouer("yahoo", YAHOO_DAILY, YAHOO_HORAIRE, identifiant, journal)
        rejeu_alpaca = rejouer("alpaca", alpaca_daily, alpaca_horaire, identifiant, journal)
        executer("Comparaison des deux journaux",
                 ["comparer_sources.py", "--journaux", rejeu_yahoo, rejeu_alpaca], journal)
    print(f"Termine. Journal : {chemin_journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
