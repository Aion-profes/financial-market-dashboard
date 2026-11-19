"""Tests de la configuration : fichiers fictifs, aucun réseau, aucune donnée personnelle."""

from pathlib import Path
import tempfile
import unittest

import os
from unittest import mock

from configuration import EXEMPLE, VARIABLE, bareme_connu, decrire_compte, lire_configuration
from etape_04_sorties_risque import SCENARIOS_DE_COUTS


def ecrire(dossier, texte):
    chemin = Path(dossier) / "configuration_test.toml"
    chemin.write_text(texte, encoding="utf-8")
    return chemin


class TestConfiguration(unittest.TestCase):
    def test_exemple_publie_valide_et_sans_donnee_personnelle(self):
        configuration = lire_configuration(EXEMPLE)
        # Capital de l'expérience et les deux scénarios de coûts, calculés côte à côte.
        self.assertEqual((configuration["capital_eur"], configuration["usd_depart"]), (1000.0, 0.0))
        self.assertEqual(tuple(configuration["scenarios"]), SCENARIOS_DE_COUTS)
        # L'exemple ne décrit aucun compte réel.
        self.assertEqual(configuration["compte"]["type"], "a_renseigner")
        self.assertEqual(configuration["compte"]["devises_detenues"], [])
        self.assertIn("configuration d'exemple", decrire_compte(configuration["compte"]))

    def test_fichier_local_exclu_de_la_publication(self):
        exclusions = (EXEMPLE.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("configuration_locale.toml", exclusions)
        self.assertNotIn("configuration_exemple.toml", exclusions)

    def test_compte_decrit_en_une_ligne(self):
        with tempfile.TemporaryDirectory() as dossier:
            # Compte imaginaire : sert seulement à vérifier la phrase produite.
            chemin = ecrire(dossier, '[compte]\ntype = "marge"\ndevises_detenues = ["GBP", "USD"]\nfractions = true\n'
                                     'conversion = "manuelle"\ntarification = "inconnue"\n'
                                     '[simulation]\ncapital_eur = 2000\nscenarios = ["THEORIQUE_SANS_COUTS"]\n')
            configuration = lire_configuration(chemin)
        self.assertEqual((configuration["capital_eur"], configuration["scenarios"]), (2000.0, ["THEORIQUE_SANS_COUTS"]))
        texte = decrire_compte(configuration["compte"])
        for attendu in ("marge", "GBP, USD", "fractions activées", "manuelle", "tarification inconnue"):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, texte)

    def test_fichier_designe_par_la_variable_d_environnement(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = ecrire(dossier, '[simulation]\ncapital_eur = 500\nscenarios = ["THEORIQUE_SANS_COUTS"]\n')
            with mock.patch.dict(os.environ, {VARIABLE: str(chemin)}):
                self.assertEqual(lire_configuration()["capital_eur"], 500.0)

    def test_bareme_connu_seulement_s_il_est_indique(self):
        self.assertEqual(bareme_connu({"tarification": "tiered"}), "tiered")
        self.assertEqual(bareme_connu({"tarification": "fixed"}), "fixed")
        self.assertIsNone(bareme_connu({"tarification": "inconnue"}))
        self.assertIsNone(bareme_connu({}))

    def test_configurations_invalides_refusees(self):
        cas = (
            '[simulation]\nscenarios = ["IBKR_INCONNU"]\n',                                   # scénario inconnu
            '[simulation]\nscenarios = []\n',                                                  # aucun scénario
            '[simulation]\ncapital_eur = -5\nscenarios = ["THEORIQUE_SANS_COUTS"]\n',          # capital négatif
            '[simulation]\ncapital_eur = 0\nusd_depart = 0\nscenarios = ["THEORIQUE_SANS_COUTS"]\n',
            '[simulation]\ncapital_eur = "mille"\nscenarios = ["THEORIQUE_SANS_COUTS"]\n',     # pas un nombre
            'ceci n est pas du TOML',
        )
        for texte in cas:
            with self.subTest(texte=texte), tempfile.TemporaryDirectory() as dossier:
                with self.assertRaises(ValueError):
                    lire_configuration(ecrire(dossier, texte))


if __name__ == "__main__":
    unittest.main()
