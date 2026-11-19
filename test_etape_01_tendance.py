"""Tests du filtre Daily, sans téléchargement ni données de marché."""

import unittest

from etape_01_tendance import (
    HistoriqueInsuffisant,
    calculer_tendance,
    tendance_admissible,
)


class TestTendanceAdmissible(unittest.TestCase):
    def test_les_quatre_conditions_sont_vraies(self):
        self.assertIs(tendance_admissible(110, 105, 100, 102, 98), True)

    def test_chaque_condition_peut_refuser_la_tendance(self):
        # Dans chaque cas, une seule condition est fausse.
        cas = {
            "cloture sous SMA50": (99, 105, 100, 102, 98),
            "SMA20 sous SMA50": (110, 99, 100, 98, 97),
            "SMA20 en baisse": (110, 105, 100, 106, 98),
            "SMA50 en baisse": (110, 105, 100, 102, 101),
        }
        for nom, valeurs in cas.items():
            with self.subTest(condition=nom):
                self.assertIs(tendance_admissible(*valeurs), False)

    def test_chaque_egalite_est_refusee(self):
        # Le signe > exclut l'égalité, même si les autres conditions passent.
        cas = {
            "cloture egale a SMA50": (100, 105, 100, 102, 98),
            "SMA20 egale a SMA50": (110, 100, 100, 99, 98),
            "SMA20 stable": (110, 105, 100, 105, 98),
            "SMA50 stable": (110, 105, 100, 102, 100),
        }
        for nom, valeurs in cas.items():
            with self.subTest(condition=nom):
                self.assertIs(tendance_admissible(*valeurs), False)


class TestCalculerTendance(unittest.TestCase):
    def test_54_clotures_signalent_un_historique_insuffisant(self):
        with self.assertRaises(HistoriqueInsuffisant) as contexte:
            calculer_tendance(range(100, 154))
        message = str(contexte.exception)
        self.assertIn("Historique insuffisant", message)
        self.assertIn("54", message)
        self.assertIn("55", message)

    def test_exactement_55_clotures_et_decalage_de_cinq_seances(self):
        resultat = calculer_tendance(range(100, 155))
        attendu = {
            "cloture": 154.0,
            "sma20": 144.5,
            "sma50": 129.5,
            "sma20_avant_5": 139.5,
            "sma50_avant_5": 124.5,
        }
        for nom, valeur in attendu.items():
            with self.subTest(valeur=nom):
                self.assertEqual(resultat[nom], valeur)
        for condition in ("c1", "c2", "c3", "c4", "admissible"):
            with self.subTest(condition=condition):
                self.assertIs(resultat[condition], True)

    def test_les_clotures_invalides_sont_refusees(self):
        for valeur in (float("nan"), float("inf"), None, 0):
            with self.subTest(valeur=valeur):
                clotures = list(range(100, 155))
                clotures[10] = valeur
                with self.assertRaisesRegex(ValueError, "Clôture invalide"):
                    calculer_tendance(clotures)

    def test_une_serie_en_baisse_est_refusee(self):
        resultat = calculer_tendance(range(154, 99, -1))
        for condition in ("c1", "c2", "c3", "c4", "admissible"):
            with self.subTest(condition=condition):
                self.assertIs(resultat[condition], False)

    def test_une_serie_constante_est_refusee(self):
        resultat = calculer_tendance([100.0] * 55)
        for condition in ("c1", "c2", "c3", "c4", "admissible"):
            with self.subTest(condition=condition):
                self.assertIs(resultat[condition], False)


if __name__ == "__main__":
    unittest.main()
