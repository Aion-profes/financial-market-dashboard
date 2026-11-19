"""Données horaires fictives, calendrier réel et téléchargements simulés."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from etape_03_entree_1h import (
    construire_grille,
    instant_utc,
    lire_csv_horaire,
    normaliser_horaires,
    telecharger_aapl_horaire,
)


UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
JOUR = date(2025, 7, 7)
DEBUT = datetime(2025, 7, 7, 9, 30, tzinfo=NEW_YORK)
FIN_SEANCE = datetime(2025, 7, 7, 16, tzinfo=NEW_YORK)


def bougie(debut=DEBUT, ouverture=100, high=102, low=98, cloture=101):
    """Prix inventés pour tester l'import, sans cotation réelle AAPL."""
    return {
        "debut": debut, "ouverture": ouverture,
        "high": high, "low": low, "cloture": cloture,
    }


class TestGrilleHoraire(unittest.TestCase):
    def test_seance_normale_et_derniere_tranche_de_30_minutes(self):
        grille = construire_grille(JOUR, JOUR)
        self.assertEqual(len(grille), 7)
        self.assertEqual([ligne["duree_minutes"] for ligne in grille], [60] * 6 + [30])
        self.assertEqual(grille[0]["debut"], DEBUT.astimezone(UTC))
        self.assertEqual(grille[-1]["fin"], FIN_SEANCE.astimezone(UTC))
        self.assertEqual(grille[-1]["debut"].astimezone(NEW_YORK).strftime("%H:%M"), "15:30")
        self.assertTrue(all(ligne["session"] == JOUR for ligne in grille))

    def test_cloture_anticipee_du_27_novembre_2026(self):
        grille = construire_grille(date(2026, 11, 27), date(2026, 11, 27))
        self.assertEqual([ligne["duree_minutes"] for ligne in grille], [60, 60, 60, 30])
        self.assertEqual(grille[-1]["fin"].astimezone(NEW_YORK).strftime("%H:%M"), "13:00")
        self.assertEqual(grille[-1]["debut"].astimezone(NEW_YORK).strftime("%H:%M"), "12:30")

    def test_changement_heure_sans_decalage_utc_constant(self):
        grille = construire_grille(date(2026, 10, 30), date(2026, 11, 2))
        vendredi = [ligne for ligne in grille if ligne["session"] == date(2026, 10, 30)]
        lundi = [ligne for ligne in grille if ligne["session"] == date(2026, 11, 2)]
        self.assertEqual(vendredi[0]["debut"].strftime("%H:%M"), "13:30")
        self.assertEqual(lundi[0]["debut"].strftime("%H:%M"), "14:30")
        for ligne in (vendredi[0], lundi[0]):
            self.assertEqual(ligne["debut"].astimezone(NEW_YORK).strftime("%H:%M"), "09:30")

    def test_ferie_et_week_end_sans_creneau_attendu(self):
        for jour in (date(2026, 11, 26), date(2026, 11, 28), date(2026, 11, 29)):
            with self.subTest(jour=jour):
                self.assertEqual(construire_grille(jour, jour), [])


class TestNormalisationHoraire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grille = construire_grille(JOUR, JOUR)

    def normaliser(self, bougies, instant=FIN_SEANCE):
        return normaliser_horaires(bougies, instant, self.grille)

    def test_tri_conversion_utc_et_conservation_des_entrees(self):
        entrees = [
            bougie(DEBUT + timedelta(hours=1), ouverture="101", high="103", low="99", cloture="102"),
            bougie(debut=DEBUT.isoformat()),
        ]
        originales = deepcopy(entrees)
        resultat = self.normaliser(entrees)
        self.assertEqual(resultat[0]["debut"], DEBUT.astimezone(UTC))
        self.assertEqual(resultat[0]["fin"], (DEBUT + timedelta(hours=1)).astimezone(UTC))
        self.assertEqual(resultat[1]["ouverture"], 101.0)
        self.assertIsInstance(resultat[1]["cloture"], float)
        self.assertEqual(entrees, originales)

    def test_instant_sans_fuseau_refuse_et_conversion_iso(self):
        for valeur in (datetime(2025, 7, 7, 9, 30), "2025-07-07T09:30:00"):
            with self.subTest(valeur=valeur):
                with self.assertRaisesRegex(ValueError, "fuseau"):
                    instant_utc(valeur)
        self.assertEqual(instant_utc("2025-07-07T09:30:00-04:00"), DEBUT.astimezone(UTC))

    def test_doublon_meme_instant_dans_deux_fuseaux_refuse(self):
        with self.assertRaisesRegex(ValueError, "double"):
            self.normaliser([bougie(), bougie(debut=DEBUT.astimezone(UTC))])

    def test_horaires_hors_grille_refuses(self):
        for debut in (DEBUT - timedelta(hours=1), DEBUT + timedelta(minutes=30), FIN_SEANCE):
            with self.subTest(debut=debut):
                with self.assertRaisesRegex(ValueError, "grille"):
                    self.normaliser([bougie(debut=debut)])

    def test_fin_ou_disponibilite_anticipee_refusee(self):
        for supplement in (
            {"fin": DEBUT + timedelta(minutes=30)},
            {"disponible_a": DEBUT + timedelta(minutes=59)},
            {"ouverture_disponible_a": DEBUT - timedelta(seconds=1)},
        ):
            with self.subTest(supplement=supplement):
                with self.assertRaises(ValueError):
                    self.normaliser([dict(bougie(), **supplement)])

    def test_prix_invalides_refuses(self):
        for champ in ("ouverture", "high", "low", "cloture"):
            for valeur in (0, -1, float("nan"), float("inf"), True, "invalide"):
                with self.subTest(champ=champ, valeur=valeur):
                    ligne = bougie()
                    ligne[champ] = valeur
                    with self.assertRaises(ValueError):
                        self.normaliser([ligne])

    def test_ohlc_incoherents_refuses_et_egalites_acceptees(self):
        for ligne in (
            bougie(high=97), bougie(ouverture=103), bougie(cloture=97),
        ):
            with self.subTest(ligne=ligne):
                with self.assertRaises(ValueError):
                    self.normaliser([ligne])
        resultat = self.normaliser([bougie(ouverture=100, high=100, low=100, cloture=100)])
        self.assertEqual(resultat[0]["low"], 100.0)

    def test_prix_absents_conserves_sans_remplissage(self):
        resultat = self.normaliser([bougie(ouverture=None, high=None, low=None, cloture=None)])
        self.assertTrue(all(resultat[0][champ] is None for champ in ("ouverture", "high", "low", "cloture")))

    def test_bougie_future_ignoree_avant_lecture_des_prix(self):
        resultat = self.normaliser([
            bougie(),
            {"debut": DEBUT + timedelta(hours=1), "high": "invalide"},
        ], DEBUT)
        self.assertEqual(len(resultat), 1)
        self.assertEqual(resultat[0]["ouverture"], 100)

    def test_open_inclus_a_sa_borne_hlc_inacheves_ignores(self):
        ligne = bougie(high="invalide", low=-1, cloture=float("nan"))
        resultat = self.normaliser([ligne], DEBUT)
        self.assertEqual(resultat[0]["ouverture"], 100.0)
        for champ in ("high", "low", "cloture"):
            self.assertIsNone(resultat[0][champ])

    def test_hlc_disponibles_a_la_fin_du_creneau(self):
        resultat = self.normaliser([bougie()], DEBUT + timedelta(hours=1))
        self.assertEqual(resultat[0]["high"], 102.0)
        self.assertEqual(resultat[0]["low"], 98.0)
        self.assertEqual(resultat[0]["cloture"], 101.0)

    def test_disponibilite_tardive_masque_les_valeurs(self):
        ligne = dict(bougie(), disponible_a=DEBUT + timedelta(hours=2),
                     ouverture_disponible_a=DEBUT + timedelta(minutes=1))
        au_debut = self.normaliser([ligne], DEBUT)[0]
        self.assertIsNone(au_debut["ouverture"])
        a_la_fin = self.normaliser([ligne], DEBUT + timedelta(hours=1))[0]
        self.assertEqual(a_la_fin["ouverture"], 100.0)
        self.assertIsNone(a_la_fin["cloture"])


class TestCSVHoraire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grille = construire_grille(JOUR, JOUR)

    def lire(self, texte, instant=FIN_SEANCE):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "fictif_horaire.csv"
            chemin.write_text(texte, encoding="utf-8")
            return lire_csv_horaire(chemin, instant, self.grille)

    def test_csv_virgule_et_vrais_ohlc(self):
        resultat = self.lire(
            "Datetime,Open,High,Low,Close,Symbol\n"
            "2025-07-07T09:30:00-04:00,100,102,98,101,AAPL\n"
        )
        self.assertEqual(resultat[0]["debut"], DEBUT.astimezone(UTC))
        self.assertEqual([resultat[0][champ] for champ in ("ouverture", "high", "low", "cloture")],
                         [100.0, 102.0, 98.0, 101.0])

    def test_csv_point_virgule_et_decimales_virgule(self):
        resultat = self.lire(
            "Datetime;Open;High;Low;Close\n"
            "2025-07-07T09:30:00-04:00;100,5;102,5;98,5;101,5\n"
        )
        self.assertEqual(resultat[0]["ouverture"], 100.5)
        self.assertEqual(resultat[0]["cloture"], 101.5)

    def test_colonnes_ohlc_obligatoires(self):
        for colonne in ("Datetime", "Open", "High", "Low", "Close"):
            noms = [champ for champ in ("Datetime", "Open", "High", "Low", "Close") if champ != colonne]
            with self.subTest(colonne=colonne):
                with self.assertRaises(ValueError):
                    self.lire(",".join(noms) + "\n")

    def test_csv_cellules_vides_reste_indisponible(self):
        resultat = self.lire(
            "Datetime,Open,High,Low,Close\n2025-07-07T09:30:00-04:00,,,,\n"
        )
        self.assertTrue(all(resultat[0][champ] is None for champ in ("ouverture", "high", "low", "cloture")))

    def test_csv_ligne_future_ignoree_avant_prix_et_symbol(self):
        resultat = self.lire(
            "Datetime,Open,High,Low,Close,Symbol\n"
            "2025-07-07T09:30:00-04:00,100,102,98,101,AAPL\n"
            "2025-07-07T10:30:00-04:00,invalide,nan,-1,,NVDA\n",
            DEBUT,
        )
        self.assertEqual(len(resultat), 1)
        self.assertEqual(resultat[0]["ouverture"], 100.0)

    def test_csv_hlc_encore_inconnus_ignores_avant_conversion(self):
        resultat = self.lire(
            "Datetime,Open,High,Low,Close\n"
            "2025-07-07T09:30:00-04:00,100,invalide,-1,nan\n",
            DEBUT,
        )
        self.assertEqual(resultat[0]["ouverture"], 100.0)
        self.assertIsNone(resultat[0]["cloture"])

    def test_symbol_etranger_et_datetime_sans_fuseau_refuses(self):
        for texte in (
            "Datetime,Open,High,Low,Close,Symbol\n2025-07-07T09:30:00-04:00,100,102,98,101,NVDA\n",
            "Datetime,Open,High,Low,Close\n2025-07-07T09:30:00,100,102,98,101\n",
        ):
            with self.subTest(texte=texte):
                with self.assertRaises(ValueError):
                    self.lire(texte)

    def test_colonnes_de_disponibilite_et_fin(self):
        resultat = self.lire(
            "Datetime,Open,High,Low,Close,End,AvailableAt,OpenAvailableAt\n"
            "2025-07-07T09:30:00-04:00,100,102,98,101,2025-07-07T10:30:00-04:00,"
            "2025-07-07T10:35:00-04:00,2025-07-07T09:31:00-04:00\n"
        )
        self.assertEqual(resultat[0]["disponible_a"], (DEBUT + timedelta(hours=1, minutes=5)).astimezone(UTC))
        self.assertEqual(resultat[0]["ouverture_disponible_a"], (DEBUT + timedelta(minutes=1)).astimezone(UTC))


class TestTelechargementHoraire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grille = construire_grille(JOUR, JOUR)

    def donnees(self):
        return pd.DataFrame(
            # Des décimaux, comme Yahoo : une colonne d'entiers refuse nan et inf.
            {"Open": [100.0, 101.0], "High": [102.0, 103.0],
             "Low": [98.0, 99.0], "Close": [101.0, 102.0]},
            index=pd.DatetimeIndex([DEBUT, DEBUT + timedelta(hours=1)]),
        )

    @patch("yfinance.download")
    def test_ohlc_conserves_et_options_explicites(self, download):
        download.return_value = self.donnees()
        resultat = telecharger_aapl_horaire(JOUR, FIN_SEANCE, self.grille)
        self.assertEqual(len(resultat), 2)
        self.assertEqual([resultat[0][champ] for champ in ("ouverture", "high", "low", "cloture")],
                         [100.0, 102.0, 98.0, 101.0])
        download.assert_called_once()
        args, options = download.call_args
        self.assertEqual(args, ("AAPL",))
        self.assertEqual(options["interval"], "1h")
        for champ in ("auto_adjust", "back_adjust", "repair", "rounding", "prepost",
                      "ignore_tz", "multi_level_index", "threads", "progress"):
            with self.subTest(champ=champ):
                self.assertIs(options[champ], False)
        self.assertIs(options["keepna"], True)

    @patch("yfinance.download")
    def test_telechargement_en_cours_conserve_open_seulement(self, download):
        donnees = self.donnees()
        donnees.loc[DEBUT, ["High", "Low", "Close"]] = [float("nan"), -1, float("inf")]
        download.return_value = donnees
        resultat = telecharger_aapl_horaire(JOUR, DEBUT, self.grille)
        self.assertEqual(len(resultat), 1)
        self.assertEqual(resultat[0]["ouverture"], 100.0)
        self.assertIsNone(resultat[0]["high"])
        self.assertIsNone(resultat[0]["low"])
        self.assertIsNone(resultat[0]["cloture"])

    @patch("yfinance.download")
    def test_telechargement_vide_et_panne_proposent_csv(self, download):
        for donnees in (None, pd.DataFrame()):
            with self.subTest(donnees=type(donnees).__name__):
                download.return_value = donnees
                with self.assertRaisesRegex(ValueError, "csv"):
                    telecharger_aapl_horaire(JOUR, FIN_SEANCE, self.grille)
        download.side_effect = RuntimeError("panne simulée")
        with self.assertRaisesRegex(ValueError, "csv"):
            telecharger_aapl_horaire(JOUR, FIN_SEANCE, self.grille)

    @patch("yfinance.download")
    def test_telechargement_sans_open_refuse(self, download):
        download.return_value = self.donnees().drop(columns=["Open"])
        with self.assertRaises(ValueError):
            telecharger_aapl_horaire(JOUR, FIN_SEANCE, self.grille)


if __name__ == "__main__":
    unittest.main()
