"""Tests de la bascule vers Alpaca et du choix du titre, sans réseau ni vraies clés."""

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from etape_01_tendance import SYMBOLES, lire_csv, telecharger_clotures
from etape_02_pullback import lire_csv_pullback, telecharger_bougies
from etape_03_entree_1h import construire_grille, lire_csv_horaire, telecharger_marche
from source_alpaca import (
    assembler_horaire, telecharger_barres, telecharger_daily, telecharger_daily_recent,
)
from test_source_alpaca import FAUSSES_CLES, barre, reponse_http


UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
JOUR = date(2025, 7, 7)       # lundi, séance normale
LENDEMAIN = date(2025, 7, 8)
DEBUT = datetime(2025, 7, 7, 9, 30, tzinfo=NEW_YORK)
FIN_SEANCE = datetime(2025, 7, 7, 16, tzinfo=NEW_YORK)


def demi_heures(nombre):
    """Barres fictives de 30 minutes depuis 09:30, toutes différentes."""
    return [barre(DEBUT + timedelta(minutes=30 * numero), o=100 + numero, h=110 + numero,
                  l=90 + numero, c=105 + numero) for numero in range(nombre)]


def daily_alpaca(*jours):
    """Barres 1Day fictives, horodatées à minuit New York comme chez Alpaca."""
    return [barre(datetime(jour.year, jour.month, jour.day, tzinfo=NEW_YORK)) for jour in jours]


class TestSymbole(unittest.TestCase):
    def test_univers_du_projet(self):
        self.assertEqual(SYMBOLES, ("AAPL", "NVDA", "AVGO"))

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_alpaca_demande_et_lit_le_titre_choisi(self, urlopen):
        # La réponse contient aussi AAPL : seul le titre demandé doit être lu.
        urlopen.return_value = reponse_http({
            "bars": {"NVDA": [barre(DEBUT)], "AAPL": [barre(DEBUT), barre(DEBUT)]},
            "next_page_token": None,
        })
        barres = telecharger_barres("30Min", DEBUT, FIN_SEANCE,
                                    datetime(2025, 7, 8, 12, tzinfo=UTC), "NVDA")
        self.assertEqual(len(barres), 1)
        self.assertIn("symbols=NVDA", urlopen.call_args.args[0].full_url)

    def test_csv_controle_le_titre_demande(self):
        fichiers = (
            (lire_csv, "Date,Close,Symbol\n2025-07-07,100,{}\n", JOUR),
            (lire_csv_pullback, "Date,High,Low,Close,Symbol\n2025-07-07,102,98,100,{}\n", JOUR),
        )
        for lecteur, modele, limite in fichiers:
            with self.subTest(lecteur=lecteur.__name__), tempfile.TemporaryDirectory() as dossier:
                bon = Path(dossier) / "nvda.csv"
                bon.write_text(modele.format("NVDA"), encoding="utf-8")
                self.assertEqual(len(lecteur(bon, limite, "NVDA")), 1)
                autre = Path(dossier) / "aapl.csv"
                autre.write_text(modele.format("AAPL"), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "NVDA"):
                    lecteur(autre, limite, "NVDA")

    def test_csv_horaire_controle_le_titre_demande(self):
        grille = construire_grille(JOUR, JOUR)
        modele = "Datetime,Open,High,Low,Close,Symbol\n2025-07-07T09:30:00-04:00,100,102,98,101,{}\n"
        with tempfile.TemporaryDirectory() as dossier:
            bon = Path(dossier) / "avgo.csv"
            bon.write_text(modele.format("AVGO"), encoding="utf-8")
            self.assertEqual(len(lire_csv_horaire(bon, FIN_SEANCE, grille, "AVGO")), 1)
            autre = Path(dossier) / "aapl.csv"
            autre.write_text(modele.format("AAPL"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "AVGO"):
                lire_csv_horaire(autre, FIN_SEANCE, grille, "AVGO")


class TestChoixDeLaSource(unittest.TestCase):
    BOUGIES = [
        {"date": JOUR, "high": 102.0, "low": 98.0, "cloture": 100.0},
        {"date": LENDEMAIN, "high": 103.0, "low": 99.0, "cloture": 101.0},
    ]

    @patch("source_alpaca.telecharger_daily_recent")
    def test_etape_1_alpaca_par_defaut_ne_garde_que_les_clotures(self, recent):
        recent.return_value = list(self.BOUGIES)
        self.assertEqual(telecharger_clotures(LENDEMAIN, "NVDA"),
                         [(JOUR, 100.0), (LENDEMAIN, 101.0)])
        recent.assert_called_once_with(LENDEMAIN, "NVDA")

    @patch("source_alpaca.telecharger_daily_recent")
    def test_etape_2_alpaca_par_defaut_et_date_limite_respectee(self, recent):
        recent.return_value = list(self.BOUGIES)
        self.assertEqual(telecharger_bougies(JOUR, "AVGO"), [self.BOUGIES[0]])
        recent.assert_called_once_with(JOUR, "AVGO")

    @patch("source_alpaca.telecharger_daily_recent")
    def test_panne_alpaca_propose_yahoo_et_csv(self, recent):
        recent.side_effect = ValueError("Alpaca a répondu HTTP 500 : panne simulée")
        for telecharger in (telecharger_clotures, telecharger_bougies):
            with self.subTest(fonction=telecharger.__name__):
                with self.assertRaisesRegex(ValueError, "panne simulée") as contexte:
                    telecharger(LENDEMAIN)
                self.assertIn("--source yahoo", str(contexte.exception))
                self.assertIn("--csv", str(contexte.exception))

    @patch("source_alpaca.telecharger_daily_recent")
    @patch("yfinance.download")
    def test_source_yahoo_utilise_yfinance_avec_le_titre(self, download, recent):
        download.return_value = pd.DataFrame(
            {"High": [102.0, 103.0], "Low": [98.0, 99.0], "Close": [100.0, 101.0]},
            index=pd.to_datetime(["2025-07-07", "2025-07-08"]),
        )
        self.assertEqual(telecharger_clotures(LENDEMAIN, "NVDA", "yahoo"),
                         [(JOUR, 100.0), (LENDEMAIN, 101.0)])
        self.assertEqual(telecharger_bougies(LENDEMAIN, "NVDA", "yahoo"), self.BOUGIES)
        for appel in download.call_args_list:
            self.assertEqual(appel.args, ("NVDA",))
        recent.assert_not_called()

    @patch("source_alpaca.telecharger_barres")
    def test_un_an_de_daily_jusqu_a_la_date_limite(self, barres):
        barres.return_value = daily_alpaca(JOUR, LENDEMAIN)
        maintenant = datetime(2025, 7, 20, tzinfo=UTC)
        self.assertEqual(len(telecharger_daily_recent(LENDEMAIN, "NVDA", maintenant)), 2)
        intervalle, debut, fin, _, symbole = barres.call_args.args
        self.assertEqual((intervalle, symbole), ("1Day", "NVDA"))
        self.assertEqual(debut.date(), LENDEMAIN - timedelta(days=370))
        self.assertEqual(fin.date(), LENDEMAIN)


class TestRetardDeQuinzeMinutes(unittest.TestCase):
    """Alpaca gratuit ne montre pas les 15 dernières minutes : rien de partiel n'est gardé."""

    @classmethod
    def setUpClass(cls):
        cls.grille = construire_grille(JOUR, JOUR)

    @patch("source_alpaca.telecharger_barres")
    def test_barre_daily_du_jour_ecartee_tant_que_la_seance_est_partielle(self, barres):
        cas = (
            (datetime(2025, 7, 8, 12, 0, tzinfo=NEW_YORK), 1),    # séance en cours
            (datetime(2025, 7, 8, 16, 15, tzinfo=NEW_YORK), 1),   # clôture pas encore consultable
            (datetime(2025, 7, 8, 16, 16, tzinfo=NEW_YORK), 2),   # 15 minutes + 1 de marge
            (datetime(2025, 7, 20, 12, 0, tzinfo=NEW_YORK), 2),   # relecture historique
        )
        for maintenant, attendu in cas:
            with self.subTest(maintenant=maintenant):
                barres.return_value = daily_alpaca(JOUR, LENDEMAIN)
                bougies = telecharger_daily(JOUR, LENDEMAIN, maintenant)
                self.assertEqual(len(bougies), attendu)
                self.assertEqual(bougies[0]["date"], JOUR)

    def test_creneau_en_cours_garde_seulement_son_open(self):
        # À 11:35, Alpaca montre jusqu'à 11:20 : la barre de 11:00 est partielle.
        consultable = datetime(2025, 7, 7, 11, 20, tzinfo=NEW_YORK)
        limite = datetime(2025, 7, 7, 11, 35, tzinfo=NEW_YORK)
        bougies, incomplets, hors = assembler_horaire(
            demi_heures(4), self.grille, DEBUT, FIN_SEANCE, limite, consultable)
        self.assertEqual(len(bougies), 2)
        complete, en_cours = bougies
        self.assertEqual([complete[champ] for champ in ("ouverture", "high", "low", "cloture")],
                         [100.0, 111.0, 90.0, 106.0])
        self.assertEqual(en_cours["ouverture"], 102.0)
        for champ in ("high", "low", "cloture"):
            self.assertIsNone(en_cours[champ])
        # Un créneau en cours n'est pas une anomalie de données.
        self.assertEqual(incomplets, [])
        self.assertEqual(hors, [])

    def test_trou_ancien_reste_signale_meme_avec_une_fin_consultable(self):
        barres = [barre(DEBUT)]
        bougies, incomplets, _ = assembler_horaire(
            barres, self.grille, DEBUT, FIN_SEANCE, FIN_SEANCE, FIN_SEANCE)
        self.assertEqual(bougies, [])
        self.assertEqual(len(incomplets), 7)

    @patch("etape_03_entree_1h.telecharger_bougies")
    @patch("source_alpaca.telecharger_barres")
    def test_etape_3_masque_les_prix_posterieurs_a_l_instant_evalue(self, barres, daily):
        daily.return_value = []
        barres.return_value = demi_heures(13)   # toute la séance, connue aujourd'hui
        limite = datetime(2025, 7, 7, 11, 15, tzinfo=NEW_YORK)
        _, horaires = telecharger_marche(JOUR, limite, self.grille, "NVDA", "alpaca")
        self.assertEqual(len(horaires), 2)
        self.assertEqual(horaires[0]["cloture"], 106.0)
        self.assertEqual(horaires[1]["ouverture"], 102.0)
        for champ in ("high", "low", "cloture"):
            self.assertIsNone(horaires[1][champ])
        self.assertEqual(barres.call_args.args[4], "NVDA")
        daily.assert_called_once_with(JOUR, "NVDA", "alpaca")


if __name__ == "__main__":
    unittest.main()
