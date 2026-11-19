"""Tests des taux de change BCE : fichiers fictifs, aucun réseau."""

from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from source_bce import (
    convertisseur, instant_de_disponibilite, lire_csv_taux, lire_taux, taux_de_reference,
    taux_eur_par_usd,
)


FRANCFORT = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
# Taux inventés, au format du fichier de la BCE (du plus récent au plus ancien).
FICHIER = (
    "Date,USD,JPY,\n"
    "2025-07-08,1.2500,170.1,\n"
    "2025-07-07,1.2000,169.9,\n"
    "2025-07-04,N/A,169.5,\n"
    "2025-07-03,1.1000,169.0,\n"
)


class TestLecture(unittest.TestCase):
    def test_colonne_usd_lue_et_jour_sans_cotation_ignore(self):
        taux = lire_taux(FICHIER)
        self.assertEqual(taux, {date(2025, 7, 8): 1.25, date(2025, 7, 7): 1.2, date(2025, 7, 3): 1.1})

    def test_fichier_vide_ou_taux_invalide_refuse(self):
        for texte in ("Date,USD\n", "Date,JPY\n2025-07-07,170\n", "Date,USD\n2025-07-07,-1\n",
                      "Date,USD\n2025-07-07,abc\n"):
            with self.subTest(texte=texte), self.assertRaises(ValueError):
                lire_taux(texte)

    def test_archive_relue_hors_ligne(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "bce_eurusd_fictif.csv"
            chemin.write_text("Date,USD_par_EUR\n2025-07-07,1.2\n2025-07-08,1.25\n", encoding="utf-8")
            self.assertEqual(lire_csv_taux(chemin), {date(2025, 7, 7): 1.2, date(2025, 7, 8): 1.25})


class TestDisponibilite(unittest.TestCase):
    def setUp(self):
        self.taux = lire_taux(FICHIER)

    def test_taux_du_jour_utilisable_a_partir_de_18_heures_a_francfort(self):
        avant = datetime(2025, 7, 8, 17, 59, tzinfo=FRANCFORT)
        apres = datetime(2025, 7, 8, 18, 0, tzinfo=FRANCFORT)
        self.assertAlmostEqual(taux_eur_par_usd(self.taux, avant), 1 / 1.20)   # taux de la veille
        self.assertAlmostEqual(taux_eur_par_usd(self.taux, apres), 1 / 1.25)
        self.assertEqual(instant_de_disponibilite(date(2025, 7, 8)), apres)

    def test_marge_de_prudence_apres_l_heure_annoncee_par_la_bce(self):
        # La BCE annonce « vers 16:00 » : à 16:30 à Francfort, le taux du jour n'est pas encore utilisé.
        peu_apres = datetime(2025, 7, 8, 16, 30, tzinfo=FRANCFORT)
        self.assertEqual(taux_de_reference(self.taux, peu_apres)["jour"], date(2025, 7, 7))

    def test_entree_avant_publication_taux_de_la_veille(self):
        # 10:30 à New York = 16:30 à Francfort : l'entrée du 8 juillet utilise le taux du 7.
        entree = datetime(2025, 7, 8, 10, 30, tzinfo=NEW_YORK)
        cotation = taux_de_reference(self.taux, entree)
        self.assertEqual((cotation["jour"], cotation["usd_par_eur"]), (date(2025, 7, 7), 1.20))
        self.assertLessEqual(cotation["disponible_depuis"], entree)

    def test_decision_apres_publication_taux_du_jour(self):
        # 12:30 à New York = 18:30 à Francfort : le taux du 8 juillet est disponible.
        decision = datetime(2025, 7, 8, 12, 30, tzinfo=NEW_YORK)
        cotation = taux_de_reference(self.taux, decision)
        self.assertEqual((cotation["jour"], cotation["usd_par_eur"]), (date(2025, 7, 8), 1.25))

    def test_jour_sans_nouveau_taux_dernier_taux_publie(self):
        # Vendredi 4 juillet : « N/A ». Vendredi soir et samedi gardent le taux du jeudi 3.
        for instant in (datetime(2025, 7, 4, 20, 0, tzinfo=FRANCFORT), datetime(2025, 7, 5, 12, 0, tzinfo=FRANCFORT)):
            with self.subTest(instant=instant):
                cotation = taux_de_reference(self.taux, instant)
                self.assertEqual((cotation["jour"], cotation["usd_par_eur"]), (date(2025, 7, 3), 1.10))

    def test_heure_d_ete_et_heure_d_hiver_a_francfort(self):
        # 18:00 à Francfort vaut 16:00 UTC en été et 17:00 UTC en hiver : le fuseau gère le changement.
        self.assertEqual(instant_de_disponibilite(date(2025, 7, 8)).utcoffset(), timedelta(hours=2))
        self.assertEqual(instant_de_disponibilite(date(2025, 12, 8)).utcoffset(), timedelta(hours=1))

    def test_sens_du_taux_usd_vers_eur_par_division(self):
        # 1 EUR = 1,25 USD : 100 USD valent 100 / 1,25 = 80 EUR, jamais 125.
        cotation = taux_de_reference(self.taux, datetime(2025, 7, 8, 19, 0, tzinfo=FRANCFORT))
        self.assertEqual(cotation["usd_par_eur"], 1.25)
        self.assertAlmostEqual(100 * cotation["eur_par_usd"], 80.0)
        self.assertAlmostEqual(100 / cotation["usd_par_eur"], 80.0)
        self.assertAlmostEqual(cotation["usd_par_eur"] * cotation["eur_par_usd"], 1.0)

    def test_aucun_taux_avant_le_premier_ni_taux_trop_ancien(self):
        self.assertIsNone(taux_eur_par_usd(self.taux, datetime(2025, 7, 3, 17, 0, tzinfo=FRANCFORT)))
        tard = instant_de_disponibilite(date(2025, 7, 8)) + timedelta(days=7, minutes=1)
        self.assertIsNone(taux_de_reference(self.taux, tard))
        self.assertIsNotNone(taux_de_reference(self.taux, tard - timedelta(minutes=2)))

    def test_convertisseur_et_instant_sans_fuseau(self):
        convertir = convertisseur(self.taux)
        self.assertAlmostEqual(convertir(datetime(2025, 7, 8, 18, 0, tzinfo=FRANCFORT))["eur_par_usd"], 0.8)
        with self.assertRaises(ValueError):
            convertir(datetime(2025, 7, 8, 18, 0))


if __name__ == "__main__":
    unittest.main()
