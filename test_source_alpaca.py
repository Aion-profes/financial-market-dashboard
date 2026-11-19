"""Tests de la source Alpaca : réponses HTTP simulées, sans réseau ni vraies clés."""

from datetime import date, datetime, timedelta, timezone
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.parse
from zoneinfo import ZoneInfo

from etape_03_entree_1h import construire_grille
import source_alpaca
from source_alpaca import (
    assembler_horaire, barres_en_daily, borner_fin, lire_cles,
    minutes_des_barres, telecharger_barres,
)


UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
JOUR = date(2025, 7, 7)
DEBUT = datetime(2025, 7, 7, 9, 30, tzinfo=NEW_YORK)
FIN_SEANCE = datetime(2025, 7, 7, 16, tzinfo=NEW_YORK)
MAINTENANT = datetime(2025, 7, 8, 12, tzinfo=UTC)
# Fausses clés, reconnaissables si elles fuyaient dans un message.
FAUSSES_CLES = {"APCA_API_KEY_ID": "IDENTIFIANT-FICTIF-123", "APCA_API_SECRET_KEY": "SECRET-FICTIF-456"}


def barre(debut, o=100.0, h=102.0, l=98.0, c=101.0):
    """Barre inventée au format Alpaca ; aucun cours réel."""
    instant = debut.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"t": instant, "o": o, "h": h, "l": l, "c": c, "v": 1000, "n": 10, "vw": 100.5}


def reponse_http(contenu):
    """Imite l'objet renvoyé par urlopen, utilisable avec « with »."""
    reponse = MagicMock()
    reponse.read.return_value = json.dumps(contenu).encode("utf-8")
    reponse.__enter__.return_value = reponse
    return reponse


def erreur_http(code, corps):
    return urllib.error.HTTPError("https://exemple.invalid", code, "erreur", {}, io.BytesIO(corps.encode("utf-8")))


class TestAssemblage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grille = construire_grille(JOUR, JOUR)

    def assembler(self, barres):
        return assembler_horaire(barres, self.grille, DEBUT, FIN_SEANCE, FIN_SEANCE)

    def test_deux_moities_forment_une_bougie(self):
        bougies, incomplets, hors = self.assembler([
            barre(DEBUT, o=100, h=103, l=99, c=102),
            barre(DEBUT + timedelta(minutes=30), o=102, h=105, l=97, c=104),
        ])
        premiere = bougies[0]
        self.assertEqual(premiere["debut"], DEBUT.astimezone(UTC))
        self.assertEqual(premiere["duree_minutes"], 60)
        self.assertEqual([premiere[champ] for champ in ("ouverture", "high", "low", "cloture")],
                         [100.0, 105.0, 97.0, 104.0])
        self.assertEqual(hors, [])
        # Les six autres créneaux du jour n'ont reçu aucune barre.
        self.assertEqual(len(incomplets), 6)

    def test_moitie_manquante_aucune_bougie_fabriquee(self):
        bougies, incomplets, _ = self.assembler([barre(DEBUT)])
        self.assertEqual(bougies, [])
        premier = incomplets[0]
        self.assertEqual(premier["debut"], DEBUT.astimezone(UTC))
        self.assertEqual(premier["manquantes"], [(DEBUT + timedelta(minutes=30)).astimezone(UTC)])

    def test_derniere_tranche_de_30_minutes(self):
        debut = datetime(2025, 7, 7, 15, 30, tzinfo=NEW_YORK)
        bougies, incomplets, _ = self.assembler([barre(debut, o=110, h=111, l=109, c=110.5)])
        self.assertEqual(len(bougies), 1)
        self.assertEqual(bougies[0]["duree_minutes"], 30)
        self.assertEqual(bougies[0]["cloture"], 110.5)
        self.assertNotIn(debut.astimezone(UTC), [creneau["debut"] for creneau in incomplets])

    def test_barres_hors_seance_ignorees_et_comptees(self):
        avant = datetime(2025, 7, 7, 9, 0, tzinfo=NEW_YORK)
        apres = datetime(2025, 7, 7, 16, 0, tzinfo=NEW_YORK)
        bougies, _, hors = self.assembler([
            barre(avant, h=500), barre(DEBUT), barre(DEBUT + timedelta(minutes=30)), barre(apres, l=1),
        ])
        self.assertEqual(len(bougies), 1)
        self.assertEqual(bougies[0]["high"], 102.0)
        self.assertEqual(bougies[0]["low"], 98.0)
        self.assertEqual(hors, [avant.astimezone(UTC), apres.astimezone(UTC)])

    def test_cloture_anticipee_quatre_creneaux(self):
        jour = date(2026, 11, 27)
        grille = construire_grille(jour, jour)
        ouverture = datetime(2026, 11, 27, 9, 30, tzinfo=NEW_YORK)
        barres = [barre(ouverture + timedelta(minutes=30 * numero)) for numero in range(7)]
        bougies, incomplets, hors = assembler_horaire(
            barres, grille, grille[0]["debut"], grille[-1]["fin"], grille[-1]["fin"])
        self.assertEqual([bougie["duree_minutes"] for bougie in bougies], [60, 60, 60, 30])
        self.assertEqual(incomplets, [])
        self.assertEqual(hors, [])

    def test_barre_en_double_refusee(self):
        with self.assertRaisesRegex(ValueError, "double"):
            self.assembler([barre(DEBUT), barre(DEBUT)])

    def test_minutes_de_debut_comptees(self):
        barres = [barre(DEBUT), barre(DEBUT + timedelta(minutes=30)), barre(DEBUT + timedelta(hours=1))]
        self.assertEqual(minutes_des_barres(barres), {0: 1, 30: 2})


class TestDaily(unittest.TestCase):
    def test_date_lue_a_new_york_et_format_etape_2(self):
        minuit = datetime(2025, 7, 7, 0, 0, tzinfo=NEW_YORK)
        bougies = barres_en_daily([barre(minuit + timedelta(days=1), h=103, l=99, c=101),
                                   barre(minuit, h=102, l=98, c=100)])
        self.assertEqual(bougies, [
            {"date": date(2025, 7, 7), "high": 102.0, "low": 98.0, "cloture": 100.0},
            {"date": date(2025, 7, 8), "high": 103.0, "low": 99.0, "cloture": 101.0},
        ])

    def test_bougie_incoherente_refusee(self):
        minuit = datetime(2025, 7, 7, 0, 0, tzinfo=NEW_YORK)
        with self.assertRaises(ValueError):
            barres_en_daily([barre(minuit, h=97, l=98, c=100)])


class TestTelechargement(unittest.TestCase):
    def telecharger(self, intervalle="30Min"):
        return telecharger_barres(intervalle, DEBUT, FIN_SEANCE, MAINTENANT)

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_parametres_imposes_et_cles_dans_les_en_tetes(self, urlopen):
        urlopen.return_value = reponse_http({"bars": {"AAPL": [barre(DEBUT)]}, "next_page_token": None})
        self.assertEqual(len(self.telecharger()), 1)
        requete = urlopen.call_args.args[0]
        parametres = urllib.parse.parse_qs(urllib.parse.urlparse(requete.full_url).query)
        self.assertEqual(parametres["symbols"], ["AAPL"])
        self.assertEqual(parametres["timeframe"], ["30Min"])
        self.assertEqual(parametres["adjustment"], ["split"])
        self.assertEqual(parametres["feed"], ["sip"])
        self.assertEqual(requete.get_header("Apca-api-key-id"), "IDENTIFIANT-FICTIF-123")
        self.assertEqual(requete.get_header("Apca-api-secret-key"), "SECRET-FICTIF-456")
        # Les clés voyagent dans les en-têtes, jamais dans l'adresse.
        for cle in FAUSSES_CLES.values():
            self.assertNotIn(cle, requete.full_url)

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_pagination_sur_deux_pages(self, urlopen):
        urlopen.side_effect = [
            reponse_http({"bars": {"AAPL": [barre(DEBUT)]}, "next_page_token": "JETON-PAGE-2"}),
            reponse_http({"bars": {"AAPL": [barre(DEBUT + timedelta(minutes=30))]}, "next_page_token": None}),
        ]
        barres = self.telecharger()
        self.assertEqual(len(barres), 2)
        self.assertEqual(urlopen.call_count, 2)
        premiere, seconde = (appel.args[0].full_url for appel in urlopen.call_args_list)
        self.assertNotIn("page_token", premiere)
        self.assertIn("page_token=JETON-PAGE-2", seconde)

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_page_vide_avec_jeton_ne_tronque_pas(self, urlopen):
        urlopen.side_effect = [
            reponse_http({"bars": {}, "next_page_token": "SUITE"}),
            reponse_http({"bars": {"AAPL": [barre(DEBUT)]}, "next_page_token": None}),
        ]
        self.assertEqual(len(self.telecharger()), 1)

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_pagination_sans_fin_refusee(self, urlopen):
        urlopen.return_value = reponse_http({"bars": {"AAPL": []}, "next_page_token": "ENCORE"})
        with patch.object(source_alpaca, "PAGES_MAXIMUM", 3):
            with self.assertRaisesRegex(ValueError, "Pagination"):
                self.telecharger()
        self.assertEqual(urlopen.call_count, 3)

    @patch("source_alpaca.urllib.request.urlopen")
    def test_cles_absentes_message_clair_sans_appel_reseau(self, urlopen):
        for presentes in ({}, {"APCA_API_KEY_ID": "IDENTIFIANT-FICTIF-123"}):
            with self.subTest(presentes=list(presentes)):
                with patch.dict(os.environ, presentes, clear=True):
                    with self.assertRaisesRegex(ValueError, "APCA_API_SECRET_KEY") as contexte:
                        self.telecharger()
                self.assertNotIn("IDENTIFIANT-FICTIF-123", str(contexte.exception))
        urlopen.assert_not_called()

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_erreur_http_message_exact_sans_les_cles(self, urlopen):
        # On imagine le pire : le serveur renvoie les clés dans son message.
        urlopen.side_effect = erreur_http(
            403, '{"message":"subscription does not permit querying recent SIP data '
                 'IDENTIFIANT-FICTIF-123 SECRET-FICTIF-456"}')
        with self.assertRaises(ValueError) as contexte:
            self.telecharger()
        message = str(contexte.exception)
        self.assertIn("403", message)
        self.assertIn("subscription does not permit querying recent SIP data", message)
        for cle in FAUSSES_CLES.values():
            self.assertNotIn(cle, message)
        # Aucune seconde tentative avec un autre flux.
        self.assertEqual(urlopen.call_count, 1)

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_panne_reseau_sans_les_cles(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("panne simulée SECRET-FICTIF-456")
        with self.assertRaises(ValueError) as contexte:
            self.telecharger()
        self.assertIn("panne simulée", str(contexte.exception))
        self.assertNotIn("SECRET-FICTIF-456", str(contexte.exception))

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_reponse_sans_champ_bars_refusee(self, urlopen):
        urlopen.return_value = reponse_http({"message": "inattendu"})
        with self.assertRaisesRegex(ValueError, "bars"):
            self.telecharger()

    @patch.dict(os.environ, FAUSSES_CLES)
    @patch("source_alpaca.urllib.request.urlopen")
    def test_fin_bornee_a_quinze_minutes_plus_une_de_marge(self, urlopen):
        urlopen.return_value = reponse_http({"bars": {"AAPL": []}, "next_page_token": None})
        maintenant = DEBUT + timedelta(hours=2)
        telecharger_barres("30Min", DEBUT, FIN_SEANCE, maintenant)
        parametres = urllib.parse.parse_qs(urllib.parse.urlparse(urlopen.call_args.args[0].full_url).query)
        # 15 minutes imposées par Alpaca, plus 1 minute pour l'écart d'horloge du PC.
        attendu = (maintenant - timedelta(minutes=16)).astimezone(UTC).isoformat()
        self.assertEqual(parametres["end"], [attendu])

    def test_borner_fin_garde_une_fin_deja_ancienne(self):
        self.assertEqual(borner_fin(FIN_SEANCE, MAINTENANT), FIN_SEANCE.astimezone(UTC))

    @patch.dict(os.environ, FAUSSES_CLES)
    def test_periode_vide_apres_bornage_refusee(self):
        with self.assertRaisesRegex(ValueError, "vide"):
            telecharger_barres("30Min", DEBUT, FIN_SEANCE, DEBUT + timedelta(minutes=10))

    @patch.dict(os.environ, FAUSSES_CLES)
    def test_lire_cles_renvoie_les_deux_valeurs(self):
        self.assertEqual(lire_cles(), ("IDENTIFIANT-FICTIF-123", "SECRET-FICTIF-456"))


if __name__ == "__main__":
    unittest.main()
