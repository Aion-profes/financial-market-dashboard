"""Vérifie la lecture et les dates des données Daily, sans accès réseau."""

from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from etape_01_tendance import (
    calculer_tendance,
    construire_tableau,
    date_limite_evaluation,
    lire_csv,
    normaliser_cotations,
    verifier_seances_nasdaq,
)


class TestLectureCSV(unittest.TestCase):
    def lire_texte(self, texte, limite=date(2025, 7, 9)):
        # Chaque test utilise son propre fichier temporaire.
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "aapl.csv"
            chemin.write_text(texte, encoding="utf-8")
            return lire_csv(chemin, limite)

    def test_lecture_trie_les_dates(self):
        resultat = self.lire_texte(
            "Date,Close\n2025-07-09,102\n2025-07-07,100\n2025-07-08,101\n"
        )
        self.assertEqual(resultat, [
            (date(2025, 7, 7), 100.0),
            (date(2025, 7, 8), 101.0),
            (date(2025, 7, 9), 102.0),
        ])

    def test_date_en_double_refusee(self):
        with self.assertRaisesRegex(ValueError, "Dates en double"):
            self.lire_texte("Date,Close\n2025-07-07,100\n2025-07-07,101\n")

    def test_prix_non_finis_refuses(self):
        for prix in ("nan", "inf"):
            with self.subTest(prix=prix):
                with self.assertRaisesRegex(ValueError, "Clôture invalide"):
                    self.lire_texte(f"Date,Close\n2025-07-07,{prix}\n")

    def test_ligne_future_exclue_avant_validation_du_prix(self):
        resultat = self.lire_texte(
            "Date,Close\n2025-07-07,100\n2025-07-10,pas-un-prix\n"
        )
        self.assertEqual(resultat, [(date(2025, 7, 7), 100.0)])

    def test_date_et_close_sont_obligatoires(self):
        for texte in ("Date,Open\n2025-07-07,100\n", "Close\n100\n"):
            with self.subTest(entete=texte.splitlines()[0]):
                with self.assertRaisesRegex(ValueError, "Date et Close sont obligatoires"):
                    self.lire_texte(texte)


class TestNormalisation(unittest.TestCase):
    def test_tri_et_exclusion_du_futur(self):
        resultat = normaliser_cotations([
            (date(2025, 7, 9), 102),
            (date(2025, 7, 7), 100),
            (date(2025, 7, 10), None),
        ], date(2025, 7, 9))
        self.assertEqual(resultat, [
            (date(2025, 7, 7), 100.0),
            (date(2025, 7, 9), 102.0),
        ])


class TestDateEvaluation(unittest.TestCase):
    def setUp(self):
        # À 00 h 30 à Paris le 8 juillet, il est encore le 7 à New York.
        self.maintenant = datetime(2025, 7, 8, 0, 30, tzinfo=ZoneInfo("Europe/Paris"))

    def test_jour_courant_defini_a_new_york(self):
        self.assertEqual(
            date_limite_evaluation(maintenant=self.maintenant), date(2025, 7, 6)
        )

    def test_jour_courant_new_york_refuse(self):
        with self.assertRaisesRegex(ValueError, "date courante à New York"):
            date_limite_evaluation(date(2025, 7, 7), self.maintenant)

    def test_date_passee_acceptee(self):
        self.assertEqual(
            date_limite_evaluation(date(2025, 7, 3), self.maintenant), date(2025, 7, 3)
        )


class TestSeancesNasdaq(unittest.TestCase):
    def test_jour_ferie_et_week_end_ne_sont_pas_des_seances_manquantes(self):
        # Le 4 juillet 2025 est férié ; les 5 et 6 juillet sont un week-end.
        verifier_seances_nasdaq([
            (date(2025, 7, 3), 100.0),
            (date(2025, 7, 7), 101.0),
        ])

    def test_week_end_et_jour_ferie_refuses_comme_cotations(self):
        for jour in (date(2025, 7, 4), date(2025, 7, 5)):
            with self.subTest(jour=jour):
                with self.assertRaisesRegex(ValueError, "hors séance NASDAQ"):
                    verifier_seances_nasdaq([(jour, 100.0)])

    def test_vraie_seance_absente_refusee(self):
        # Le 8 juillet est une vraie séance, absente de cet historique.
        with self.assertRaisesRegex(ValueError, "Séance NASDAQ manquante : 2025-07-08"):
            verifier_seances_nasdaq([
                (date(2025, 7, 7), 100.0),
                (date(2025, 7, 9), 102.0),
            ])


class TestTableau(unittest.TestCase):
    def setUp(self):
        # Série fictive : ces prix servent uniquement à tester les calculs.
        self.cotations = []
        jour = date(2025, 3, 3)
        while len(self.cotations) < 60:
            if jour.weekday() < 5:
                self.cotations.append((jour, 100.0 + len(self.cotations)))
            jour += timedelta(days=1)

    def test_verdict_indisponible_avant_la_55e_cloture(self):
        tableau = construire_tableau(self.cotations)
        self.assertEqual(len(tableau), 60)
        for numero, ligne in enumerate(tableau[:54], start=1):
            with self.subTest(ligne=numero):
                self.assertIsNone(ligne["admissible"])
        self.assertIs(tableau[54]["admissible"], True)
        self.assertIsNone(tableau[53]["sma50_avant_5"])
        self.assertEqual(tableau[54]["sma50_avant_5"], 124.5)

    def test_les_prix_futurs_ne_modifient_pas_les_lignes_passees(self):
        tableau_court = construire_tableau(self.cotations[:55])
        tableau_complet = construire_tableau(self.cotations)
        self.assertEqual(tableau_court, tableau_complet[:55])
        # On change fortement les cinq prix futurs : le passé reste identique.
        autres_prix_futurs = self.cotations[:55] + [
            (jour, 10000.0) for jour, _ in self.cotations[55:]
        ]
        tableau_modifie = construire_tableau(autres_prix_futurs)
        self.assertEqual(tableau_court, tableau_modifie[:55])
        self.assertNotEqual(tableau_complet[-1]["sma20"], tableau_modifie[-1]["sma20"])

    def test_derniere_ligne_coherente_avec_le_calcul_direct(self):
        derniere_ligne = construire_tableau(self.cotations)[-1]
        resultat_direct = calculer_tendance([prix for _, prix in self.cotations])
        self.assertEqual(derniere_ligne["date"], self.cotations[-1][0])
        self.assertEqual(
            {nom: valeur for nom, valeur in derniere_ligne.items() if nom != "date"},
            resultat_direct,
        )


if __name__ == "__main__":
    unittest.main()
