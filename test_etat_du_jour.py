"""Tests du résumé « état du jour » : prix fictifs, calendrier réel, aucun réseau."""

from copy import deepcopy
from datetime import date, datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from etape_03_entree_1h import scenario_fictif
from etape_04_sorties_risque import chercher_candidats
from etat_du_jour import (
    EN_ATTENTE, NON_REMPLIE, REMPLIE, SANS_OBJET, VERDICTS,
    charger_marche, expliquer_motif, nombre_fr, resumer,
)
from test_etape_03_entree_1h import jeu_horaire
from test_source_alpaca import barre


NEW_YORK = ZoneInfo("America/New_York")


def etats(resume):
    return [condition["etat"] for condition in resume["conditions"]]


class TestVerdicts(unittest.TestCase):
    """Sommet fictif à 120, creux à 100, repli à 112 : la limite des 50 % est à 110."""

    @classmethod
    def setUpClass(cls):
        cls.daily_base, cls.horaires_base, cls.ouverture_j3 = scenario_fictif()

    def setUp(self):
        self.daily = deepcopy(self.daily_base)
        self.horaires = deepcopy(self.horaires_base)

    def test_entree_simulee_a_l_ouverture_de_j3(self):
        resume = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        self.assertEqual(resume["verdict"], "ENTREE_SIMULEE")
        self.assertEqual(etats(resume), [REMPLIE, REMPLIE, REMPLIE])
        self.assertEqual(resume["entree"]["prix"], 114.2)
        self.assertEqual(resume["entree"]["instant"], self.ouverture_j3)
        self.assertIn("114,20", resume["phrase"])
        configuration = resume["configuration"]
        self.assertEqual(configuration["sommet"], 120.0)
        self.assertEqual(configuration["creux_reference"], 100.0)
        self.assertEqual(configuration["limite_50"], 110.0)
        self.assertEqual(configuration["plus_bas_repli"], 112.0)
        self.assertAlmostEqual(configuration["retracement"], 0.40)
        self.assertEqual(configuration["age_seances"], 3)
        self.assertEqual(configuration["fenetre_debut"], self.daily[63]["date"])
        self.assertEqual(configuration["fenetre_fin"], self.daily[70]["date"])

    def test_signal_a_la_cloture_de_j2_conditions_remplies(self):
        fin_j2 = self.horaires[6]["fin"]
        resume = resumer("AAPL", self.daily, self.horaires, fin_j2)
        self.assertEqual(resume["verdict"], "CONDITIONS_REMPLIES")
        self.assertEqual(etats(resume), [REMPLIE, REMPLIE, REMPLIE])
        self.assertIsNone(resume["entree"])
        self.assertEqual(resume["signal"]["ouverture_attendue"], self.ouverture_j3)
        # J10 tombe huit séances plus tard : sa date doit déjà être connue.
        self.assertEqual(resume["configuration"]["fenetre_fin"], self.daily[70]["date"])
        self.assertEqual(len(resume["configuration"]["seances"]), 11)
        self.assertIn("J2", resume["conditions"][1]["detail"])
        self.assertIn("J3", resume["conditions"][1]["detail"])

    def test_plan_en_attente_puis_position_candidate(self):
        # À la clôture de J2, le signal existe : le stop est figé, l'entrée n'a pas encore eu lieu.
        attente = resumer("AAPL", self.daily, self.horaires, self.horaires[6]["fin"])
        self.assertEqual(attente["plan_en_attente"]["plus_bas"], 112.0)
        self.assertLess(attente["plan_en_attente"]["stop"], 112.0)
        self.assertEqual(attente["plan_en_attente"]["ouverture_attendue"], self.ouverture_j3)
        # À l'ouverture de J3, l'entrée est acceptée : plus de plan en attente, une position candidate.
        entree = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        self.assertIsNone(entree["plan_en_attente"])
        candidats = chercher_candidats(entree["marche"])
        self.assertEqual(len(candidats), 1)
        self.assertEqual(candidats[0]["stop"], attente["plan_en_attente"]["stop"])   # stop inchangé
        self.assertIn("position simulée", entree["phrase"])

    def test_avant_la_confirmation_aucune_configuration(self):
        milieu_j2 = self.horaires[3]["fin"]
        resume = resumer("AAPL", self.daily, self.horaires, milieu_j2)
        self.assertEqual(resume["verdict"], "NON_REMPLIES")
        self.assertEqual(etats(resume), [REMPLIE, NON_REMPLIE, SANS_OBJET])
        self.assertIsNone(resume["configuration"])
        self.assertIsNone(resume["signal"])

    def test_gap_a_l_ouverture_tentative_utilisee(self):
        daily, horaires, ouverture = scenario_fictif(gap=True)
        resume = resumer("AAPL", daily, horaires, ouverture)
        self.assertEqual(resume["verdict"], "NON_REMPLIES")
        self.assertEqual(resume["conditions"][1]["etat"], NON_REMPLIE)
        self.assertIn("50 %", resume["phrase"])
        self.assertIsNone(resume["entree"])
        # L'Open à 109 est déjà connu : le repli affiché en tient compte.
        self.assertEqual(resume["configuration"]["plus_bas_repli"], 109.0)
        self.assertAlmostEqual(resume["configuration"]["retracement"], 0.55)

    def test_sans_declencheur_le_titre_reste_en_attente(self):
        daily, horaires, ouverture = jeu_horaire(signal_j=5)
        resume = resumer("AAPL", daily, horaires, ouverture)
        self.assertEqual(resume["verdict"], "EN_ATTENTE")
        self.assertEqual(etats(resume), [REMPLIE, REMPLIE, EN_ATTENTE])
        self.assertIsNone(resume["signal"])

    def test_historique_insuffisant_non_evaluable(self):
        resume = resumer("AAPL", self.daily[20:], self.horaires, self.ouverture_j3)
        self.assertEqual(resume["verdict"], "NON_EVALUABLE")
        self.assertIn("insuffisant", resume["phrase"])
        self.assertEqual(resume["conditions"], [])

    def test_aucune_bougie_daily_non_evaluable(self):
        resume = resumer("AAPL", [], [], self.ouverture_j3)
        self.assertEqual(resume["verdict"], "NON_EVALUABLE")

    def test_le_futur_ne_change_ni_le_verdict_ni_les_tableaux(self):
        attendu = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        for bougie in self.daily[63:]:
            bougie.update(high=999.0, low=1.0, cloture=1.0)
        premiere_j3 = next(ligne for ligne in self.horaires if ligne["debut"] == self.ouverture_j3)
        premiere_j3.update(high=999.0, low=1.0, cloture=1.0)
        resume = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        for champ in ("verdict", "phrase", "conditions", "configuration", "entree", "prix"):
            with self.subTest(champ=champ):
                self.assertEqual(resume[champ], attendu[champ])
        # Seules les 63 séances terminées (jusqu'à J2) sont retenues.
        self.assertEqual(len(resume["daily"]), 63)
        self.assertEqual(len(resume["tendances"]), 63)
        self.assertIsNone(resume["horaires"][-1]["cloture"])

    def test_dernier_prix_et_variation_depuis_la_cloture_precedente(self):
        resume = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        prix = resume["prix"]
        self.assertEqual(prix["valeur"], 114.2)
        self.assertEqual(prix["instant"], self.ouverture_j3)
        self.assertAlmostEqual(prix["reference"], 114.1)
        self.assertAlmostEqual(prix["variation"], 114.2 / 114.1 - 1)

    def test_seuil_sma20_de_la_seance_en_cours(self):
        resume = resumer("AAPL", self.daily, self.horaires, self.ouverture_j3)
        self.assertAlmostEqual(resume["seuil_sma20"], 0.96 * resume["tendances"][-1]["sma20"])

    def test_chaque_verdict_a_un_libelle(self):
        for instant in (self.horaires[3]["fin"], self.horaires[6]["fin"], self.ouverture_j3):
            self.assertIn(resumer("AAPL", self.daily, self.horaires, instant)["verdict"], VERDICTS)


class TestTextes(unittest.TestCase):
    def test_motifs_traduits_et_code_inconnu_conserve(self):
        texte = expliquer_motif("NOUVEAU_HIGH,RETRACEMENT_SUPERIEUR_50;CODE_INCONNU")
        self.assertIn("nouveau plus haut", texte)
        self.assertIn("50 %", texte)
        self.assertIn("CODE_INCONNU", texte)
        self.assertEqual(expliquer_motif(None), "")

    def test_nombre_a_la_francaise(self):
        self.assertEqual(nombre_fr(344.285), "344,29")
        self.assertEqual(nombre_fr(46.95, 1), "47,0")
        self.assertEqual(nombre_fr(None), "ND")


class TestChargement(unittest.TestCase):
    @patch("etat_du_jour.telecharger_horaire")
    @patch("etat_du_jour.telecharger_barres_daily")
    def test_open_daily_conserve_et_titre_transmis(self, barres_daily, horaire):
        lundi = datetime(2025, 7, 7, tzinfo=NEW_YORK)
        mardi = datetime(2025, 7, 8, tzinfo=NEW_YORK)
        barres_daily.return_value = [barre(lundi, o=100.5), barre(mardi, o=101.5)]
        horaire.return_value = ([], [], [], [])
        maintenant = datetime(2025, 7, 8, 17, 0, tzinfo=NEW_YORK)
        marche = charger_marche("NVDA", maintenant)
        self.assertEqual([bougie["ouverture"] for bougie in marche["daily"]], [100.5, 101.5])
        self.assertEqual(marche["daily"][0]["date"], date(2025, 7, 7))
        self.assertEqual(barres_daily.call_args.args[3], "NVDA")
        self.assertEqual(horaire.call_args.args[4], "NVDA")
        # L'horaire est masqué à l'instant évalué, comme dans l'étape 3.
        self.assertEqual(horaire.call_args.args[5], marche["instant"])

    @patch("etat_du_jour.telecharger_horaire")
    @patch("etat_du_jour.telecharger_barres_daily")
    def test_seance_daily_manquante_refusee(self, barres_daily, horaire):
        lundi = datetime(2025, 7, 7, tzinfo=NEW_YORK)
        mercredi = datetime(2025, 7, 9, tzinfo=NEW_YORK)
        barres_daily.return_value = [barre(lundi), barre(mercredi)]
        horaire.return_value = ([], [], [], [])
        with self.assertRaisesRegex(ValueError, "manquante"):
            charger_marche("AAPL", datetime(2025, 7, 9, 17, 0, tzinfo=NEW_YORK))


if __name__ == "__main__":
    unittest.main()
