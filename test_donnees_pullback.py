"""Teste les bougies Daily du pullback, avec fichiers temporaires et sans réseau."""

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from etape_02_pullback import (
    lire_csv_pullback,
    normaliser_bougies,
    telecharger_aapl_pullback,
)


def bougie(jour=date(2025, 7, 7), high=102, low=98, cloture=100):
    """Prix fictifs : ils ne représentent aucune cotation réelle d'AAPL."""
    return {"date": jour, "high": high, "low": low, "cloture": cloture}


class TestNormalisationBougies(unittest.TestCase):
    def test_tri_conversion_et_conservation_des_entrees(self):
        entrees = [
            bougie(date(2025, 7, 8), high="103", low="99", cloture="101"),
            bougie(),
        ]
        originales = [dict(ligne) for ligne in entrees]
        resultat = normaliser_bougies(entrees)
        self.assertEqual(resultat, [
            bougie(high=102.0, low=98.0, cloture=100.0),
            bougie(date(2025, 7, 8), high=103.0, low=99.0, cloture=101.0),
        ])
        for ligne in resultat:
            for champ in ("high", "low", "cloture"):
                self.assertIsInstance(ligne[champ], float)
        self.assertEqual(entrees, originales)

    def test_doublon_sur_date_retenue_refuse(self):
        with self.assertRaises(ValueError):
            normaliser_bougies([bougie(), bougie(cloture=101)])

    def test_champs_obligatoires_refuses_si_absents(self):
        for champ in ("date", "high", "low", "cloture"):
            with self.subTest(champ=champ):
                incomplete = bougie()
                del incomplete[champ]
                with self.assertRaises(ValueError):
                    normaliser_bougies([incomplete])

    def test_prix_invalides_refuses(self):
        for champ in ("high", "low", "cloture"):
            for valeur in (float("nan"), float("inf"), float("-inf"),
                           0, -1, None, "pas-un-prix"):
                with self.subTest(champ=champ, valeur=valeur):
                    invalide = bougie()
                    invalide[champ] = valeur
                    with self.assertRaises(ValueError):
                        normaliser_bougies([invalide])

    def test_low_close_high_incoherents_refuses(self):
        for ligne in (
            bougie(high=97, low=98, cloture=100),
            bougie(high=102, low=101, cloture=100),
            bougie(high=99, low=98, cloture=100),
        ):
            with self.subTest(ligne=ligne):
                with self.assertRaises(ValueError):
                    normaliser_bougies([ligne])

    def test_egalites_low_close_high_acceptees(self):
        self.assertEqual(
            normaliser_bougies([bougie(high=100, low=100, cloture=100)]),
            [bougie(high=100.0, low=100.0, cloture=100.0)],
        )

    def test_lignes_futures_exclues_avant_validation_des_prix(self):
        # Cette ligne future n'a même pas de High, Low ou Close utilisable.
        resultat = normaliser_bougies([
            {"date": date(2025, 7, 10)},
            bougie(),
            bougie(date(2025, 7, 10), high=float("nan")),
        ], date(2025, 7, 9))
        self.assertEqual(resultat, [bougie(high=102.0, low=98.0, cloture=100.0)])

    def test_date_limite_incluse(self):
        self.assertEqual(
            normaliser_bougies([bougie()], date(2025, 7, 7)),
            [bougie(high=102.0, low=98.0, cloture=100.0)],
        )


class TestLectureCSVPullback(unittest.TestCase):
    def lire_texte(self, texte, limite=date(2025, 7, 9)):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "aapl_ohlc.csv"
            chemin.write_text(texte, encoding="utf-8")
            return lire_csv_pullback(chemin, limite)

    def test_csv_virgule_trie_les_dates(self):
        resultat = self.lire_texte(
            "Date,High,Low,Close\n"
            "2025-07-08,103,99,101\n"
            "2025-07-07,102,98,100\n"
        )
        self.assertEqual(resultat, [
            bougie(high=102.0, low=98.0, cloture=100.0),
            bougie(date(2025, 7, 8), high=103.0, low=99.0, cloture=101.0),
        ])

    def test_csv_point_virgule_et_decimales_virgule(self):
        resultat = self.lire_texte(
            "Date;High;Low;Close\n2025-07-07;102,5;98,25;100,75\n"
        )
        self.assertEqual(resultat, [bougie(high=102.5, low=98.25, cloture=100.75)])

    def test_ancienne_archive_date_close_refusee_explicitement(self):
        with self.assertRaisesRegex(ValueError, r"High.*Low|Low.*High"):
            self.lire_texte("Date,Close\n2025-07-07,100\n")

    def test_chaque_colonne_est_obligatoire(self):
        for entete, ligne in (
            ("High,Low,Close", "102,98,100"),
            ("Date,Low,Close", "2025-07-07,98,100"),
            ("Date,High,Close", "2025-07-07,102,100"),
            ("Date,High,Low", "2025-07-07,102,98"),
        ):
            with self.subTest(entete=entete):
                with self.assertRaises(ValueError):
                    self.lire_texte(f"{entete}\n{ligne}\n")

    def test_symbol_aapl_accepte(self):
        resultat = self.lire_texte(
            "Date,High,Low,Close,Symbol\n2025-07-07,102,98,100,AAPL\n"
        )
        self.assertEqual(resultat, [bougie(high=102.0, low=98.0, cloture=100.0)])

    def test_autre_symbol_refuse(self):
        for symbole in ("NVDA", "aapl", ""):
            with self.subTest(symbole=symbole):
                with self.assertRaisesRegex(ValueError, "AAPL"):
                    self.lire_texte(
                        "Date,High,Low,Close,Symbol\n"
                        f"2025-07-07,102,98,100,{symbole}\n"
                    )

    def test_future_ligne_invalide_ne_change_pas_le_resultat(self):
        resultat = self.lire_texte(
            "Date,High,Low,Close,Symbol\n"
            "2025-07-07,102,98,100,AAPL\n"
            "2025-07-10,invalide,nan,,NVDA\n"
        )
        self.assertEqual(resultat, [bougie(high=102.0, low=98.0, cloture=100.0)])

    def test_date_en_double_refusee(self):
        with self.assertRaises(ValueError):
            self.lire_texte(
                "Date,High,Low,Close\n"
                "2025-07-07,102,98,100\n2025-07-07,103,99,101\n"
            )

    def test_prix_non_fini_et_bougie_incoherente_refuses(self):
        for valeurs in ("nan,98,100", "102,inf,100", "102,98,nan", "99,98,100"):
            with self.subTest(valeurs=valeurs):
                with self.assertRaises(ValueError):
                    self.lire_texte(f"Date,High,Low,Close\n2025-07-07,{valeurs}\n")


class TestTelechargementPullback(unittest.TestCase):
    def dataframe(self):
        # Un vrai tableau pandas, rempli seulement de prix fictifs.
        return pd.DataFrame(
            {"High": [102, 103], "Low": [98, 99], "Close": [100, 101]},
            index=pd.to_datetime(["2025-07-07", "2025-07-08"]),
        )

    @patch("yfinance.download")
    def test_download_conserve_les_vrais_high_low_et_les_flags(self, download):
        download.return_value = self.dataframe()
        resultat = telecharger_aapl_pullback(date(2025, 7, 8))
        self.assertEqual(resultat, [
            bougie(high=102.0, low=98.0, cloture=100.0),
            bougie(date(2025, 7, 8), high=103.0, low=99.0, cloture=101.0),
        ])
        download.assert_called_once()
        args, options = download.call_args
        self.assertEqual(args, ("AAPL",))
        self.assertEqual(options["end"], "2025-07-09")  # end est exclue.
        self.assertEqual(options["interval"], "1d")
        for option in ("auto_adjust", "back_adjust", "repair", "rounding",
                       "prepost", "multi_level_index", "threads", "progress"):
            with self.subTest(option=option):
                self.assertIs(options[option], False)
        self.assertIs(options["keepna"], True)
        self.assertIs(options["ignore_tz"], True)

    @patch("yfinance.download")
    def test_download_future_ligne_invalide_exclue(self, download):
        donnees = self.dataframe()
        donnees.loc[pd.Timestamp("2025-07-10")] = [float("nan"), -1, float("inf")]
        download.return_value = donnees
        self.assertEqual(len(telecharger_aapl_pullback(date(2025, 7, 8))), 2)

    @patch("yfinance.download")
    def test_download_vide_propose_csv(self, download):
        for donnees in (None, pd.DataFrame()):
            with self.subTest(donnees=type(donnees).__name__):
                download.return_value = donnees
                with self.assertRaisesRegex(ValueError, "--csv"):
                    telecharger_aapl_pullback(date(2025, 7, 8))

    @patch("yfinance.download")
    def test_download_sans_high_low_refuse_sans_inventer(self, download):
        download.return_value = self.dataframe()[["Close"]]
        with self.assertRaisesRegex(ValueError, r"High.*Low|Low.*High"):
            telecharger_aapl_pullback(date(2025, 7, 8))

    @patch("yfinance.download")
    def test_erreur_reseau_propose_csv(self, download):
        download.side_effect = RuntimeError("panne réseau simulée")
        with self.assertRaisesRegex(ValueError, "--csv"):
            telecharger_aapl_pullback(date(2025, 7, 8))


if __name__ == "__main__":
    unittest.main()
