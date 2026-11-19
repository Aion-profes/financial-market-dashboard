"""Configuration de la simulation : capital de l'expérience et scénarios de coûts calculés.

Deux fichiers au format TOML (du texte : « clé = valeur ») :
- configuration_exemple.toml : publié avec le projet, sans aucune donnée personnelle ;
- configuration_locale.toml : facultatif, propre à cette machine, jamais publié (.gitignore).
Si le fichier local existe, il est lu ; sinon l'exemple sert de configuration.
La variable d'environnement CONFIGURATION_SIMULATION peut désigner un autre fichier :
les tests l'utilisent pour lire toujours l'exemple, quel que soit le PC.
"""

import os
from pathlib import Path
import tomllib

from etape_01_tendance import DOSSIER_PROJET
from etape_04_sorties_risque import CAPITAL_DEPART, CONFIGURATIONS


EXEMPLE = DOSSIER_PROJET / "configuration_exemple.toml"
LOCALE = DOSSIER_PROJET / "configuration_locale.toml"
VARIABLE = "CONFIGURATION_SIMULATION"


def lire_configuration(chemin=None):
    """Lit et contrôle la configuration ; renvoie un dictionnaire prêt à l'emploi."""
    if chemin is None and os.environ.get(VARIABLE):
        chemin = Path(os.environ[VARIABLE])
    if chemin is None:
        chemin = LOCALE if LOCALE.exists() else EXEMPLE
    try:
        with open(chemin, "rb") as fichier:
            contenu = tomllib.load(fichier)
    except (OSError, tomllib.TOMLDecodeError) as erreur:
        raise ValueError(f"Configuration illisible ({chemin.name}) : {erreur}") from None
    simulation = contenu.get("simulation", {})
    scenarios = list(simulation.get("scenarios", []))
    inconnus = [nom for nom in scenarios if nom not in CONFIGURATIONS]
    if not scenarios or inconnus:
        raise ValueError(f"Configuration {chemin.name} : scénarios absents ou inconnus {inconnus}. "
                         f"Choix possibles : {', '.join(sorted(CONFIGURATIONS))}.")
    try:
        capital = float(simulation.get("capital_eur", CAPITAL_DEPART))
        usd_depart = float(simulation.get("usd_depart", 0.0))
    except (TypeError, ValueError):
        raise ValueError(f"Configuration {chemin.name} : capital_eur et usd_depart doivent être des nombres.") from None
    if capital < 0 or usd_depart < 0 or capital + usd_depart <= 0:
        raise ValueError(f"Configuration {chemin.name} : liquidités positives, et somme non nulle.")
    return {"fichier": chemin.name, "compte": dict(contenu.get("compte", {})),
            "capital_eur": capital, "usd_depart": usd_depart, "scenarios": scenarios}


def bareme_connu(compte):
    """« fixed » ou « tiered » si la configuration indique le barème du compte, sinon None."""
    tarification = (compte or {}).get("tarification")
    return tarification if tarification in ("fixed", "tiered") else None


def decrire_compte(compte):
    """Une ligne lisible sur le compte décrit ; rien si la configuration ne le renseigne pas."""
    if not compte or compte.get("type") in (None, "a_renseigner"):
        return "Compte non décrit : configuration d'exemple."
    fractions = "fractions activées" if compte.get("fractions") else "actions entières"
    devises = ", ".join(compte.get("devises_detenues", [])) or "devises non précisées"
    return (f"Compte {compte.get('type')}, devises détenues : {devises}, {fractions}, conversion "
            f"{compte.get('conversion', 'non précisée')}, tarification {compte.get('tarification', 'inconnue')}.")
