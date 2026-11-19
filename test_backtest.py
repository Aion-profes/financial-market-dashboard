"""Tests des mesures du backtest : positions fictives, aucun réseau, aucune archive réelle."""

from datetime import date, datetime, timedelta, timezone
import unittest

from backtest import (
    drawdown_maximal, garder_la_periode, instant_de_fin, mesurer, serie_de_pertes,
    simulations_du_protocole,
)
from etape_04_sorties_risque import CHAMPS_POSITION, PAS_FRACTION
from historique import ARCHIVE_FIN, PERIODES


UTC = timezone.utc
DEPART = datetime(2020, 1, 6, 15, 0, tzinfo=UTC)


def position(rang, resultat=None, statut="CLOTUREE", motif="STOP", **champs):
    """Position fictive : seuls les champs lus par les mesures sont remplis."""
    ligne = dict.fromkeys(CHAMPS_POSITION)
    ligne.update(statut=statut, motif=motif, ambigu_intrabar=False, cible_a_l_egalite=False,
                 seance_d1=date(2020, 1, 6) + timedelta(days=rang), contrainte="BUDGET_RISQUE")
    if statut == "CLOTUREE":
        ligne.update(sortie_instant=DEPART + timedelta(days=rang), apres_couts_eur=resultat,
                     brut_eur=resultat + 1.0, effet_change_eur=0.0, couts_eur=1.0, risque_prix_eur=4.0,
                     multiple_r_apres_couts=resultat / 4.0, seance_detention=3, quantite=1.0,
                     conversion_entree_usd=0.0)
    ligne.update(champs)
    return ligne


class TestMesures(unittest.TestCase):
    def test_serie_de_pertes(self):
        self.assertEqual(serie_de_pertes([5, -1, -2, -3, 4, -1]), 3)
        self.assertEqual(serie_de_pertes([1, 2, 0]), 0)        # un résultat nul n'est pas une perte
        self.assertEqual(serie_de_pertes([]), 0)

    def test_drawdown_maximal_depuis_un_sommet(self):
        # 1 000 -> 1 010 -> 1 004 -> 1 001 -> 1 021 : le creux est 9 EUR sous le sommet de 1 010.
        baisse, part = drawdown_maximal([10, -6, -3, 20], 1000.0)
        self.assertAlmostEqual(baisse, 9.0)
        self.assertAlmostEqual(part, 9.0 / 1010.0)
        self.assertEqual(drawdown_maximal([5, 5], 1000.0), (0.0, 0.0))

    def test_mesures_d_un_journal_complet(self):
        journal = [
            position(1, 10.0, motif="CIBLE"), position(2, -6.0), position(3, -3.0), position(4, 20.0, motif="CIBLE"),
            position(5, statut="REFUSEE", motif="PAS_DE_POSITION_TAILLE_INSUFFISANTE"),
            position(6, statut="REFUSEE", motif="FONDS_DISPONIBLES_INSUFFISANTS"),
            position(7, statut="NON_EVALUABLE", motif="BOUGIE_HORAIRE_MANQUANTE"),
            position(8, statut="OUVERTE", motif="POSITION_OUVERTE_FIN_DONNEES"),
        ]
        mesures = mesurer(journal, 1000.0)
        # Aucun cas n'est retiré : huit entrées, dont quatre sans résultat.
        self.assertEqual(mesures["decompte"]["entrees"], 8)
        self.assertEqual(mesures["decompte"]["par_statut"],
                         {"CLOTUREE": 4, "REFUSEE": 2, "NON_EVALUABLE": 1, "OUVERTE": 1})
        self.assertEqual((mesures["positions_cloturees"], mesures["positions_ouvertes"]), (4, 1))
        self.assertAlmostEqual(mesures["esperance_eur"], 5.25)
        self.assertAlmostEqual(mesures["esperance_r"], 5.25 / 4.0)
        self.assertEqual((mesures["part_gagnantes"], mesures["pire_resultat_eur"], mesures["serie_de_pertes"]),
                         (0.5, -6.0, 2))
        self.assertAlmostEqual(mesures["drawdown_eur"], 9.0)
        self.assertAlmostEqual(mesures["couts_sur_risque"], 4.0 / 16.0)
        self.assertAlmostEqual(mesures["somme_resultats_eur"], 21.0)
        self.assertAlmostEqual(mesures["somme_prix_eur"] + mesures["somme_change_eur"] - mesures["somme_couts_eur"], 21.0)
        bas, haut = mesures["intervalle_eur"]
        self.assertLess(bas, 5.25)
        self.assertGreater(haut, 5.25)

    def test_resultats_ranges_dans_l_ordre_des_sorties(self):
        # Même journal écrit dans le désordre : la série de pertes suit les dates de sortie.
        journal = [position(3, -3.0), position(1, 10.0), position(4, 20.0), position(2, -6.0)]
        self.assertEqual(mesurer(journal)["serie_de_pertes"], 2)

    def test_journal_sans_position_cloturee(self):
        mesures = mesurer([position(1, statut="REFUSEE", motif="ENTREE_SOUS_STOP")])
        self.assertIsNone(mesures["esperance_eur"])
        self.assertEqual((mesures["positions_cloturees"], mesures["decompte"]["entrees"]), (0, 1))
        self.assertIsNone(mesurer([position(1, 5.0)])["intervalle_eur"])   # une seule position : pas d'intervalle

    def test_positions_reduites_et_achats_avec_conversion_comptes(self):
        journal = [position(1, 5.0, contrainte="LIQUIDITES", conversion_entree_usd=120.0), position(2, -2.0)]
        mesures = mesurer(journal)
        self.assertEqual((mesures["positions_reduites_faute_de_fonds"], mesures["achats_avec_conversion"]), (1, 1))


class TestProtocole(unittest.TestCase):
    def test_une_position_appartient_a_la_periode_de_son_entree(self):
        debut, fin = PERIODES["developpement"]
        journal = [position(0, 1.0, seance_d1=debut - timedelta(days=1)), position(0, 1.0, seance_d1=debut),
                   position(0, 1.0, seance_d1=fin), position(0, 1.0, seance_d1=fin + timedelta(days=3))]
        self.assertEqual([ligne["seance_d1"] for ligne in garder_la_periode(journal, "developpement")], [debut, fin])
        self.assertEqual(garder_la_periode(journal, "validation"), [])

    def test_fin_d_evaluation_apres_la_periode_sans_depasser_l_archive(self):
        for nom in ("developpement", "validation"):
            with self.subTest(nom=nom):
                fin = instant_de_fin(nom).date()
                self.assertGreater(fin, PERIODES[nom][1])
                self.assertLessEqual(fin, ARCHIVE_FIN)
        # Le développement s'arrête avant le début de la validation.
        self.assertLess(instant_de_fin("developpement").date(), PERIODES["validation"][0])

    def test_cinq_simulations_memes_regles(self):
        simulations = simulations_du_protocole()
        self.assertEqual(sorted(simulations), [
            "IBKR_CASH_AUTO_FRACTIONS_FIXED__defavorable", "IBKR_CASH_AUTO_FRACTIONS_FIXED__principal",
            "IBKR_CASH_AUTO_FRACTIONS_TIERED__defavorable", "IBKR_CASH_AUTO_FRACTIONS_TIERED__principal",
            "THEORIQUE_SANS_COUTS"])
        principal, pas = simulations["IBKR_CASH_AUTO_FRACTIONS_FIXED__principal"]
        defavorable, _ = simulations["IBKR_CASH_AUTO_FRACTIONS_FIXED__defavorable"]
        self.assertEqual((principal["glissement_bps"], defavorable["glissement_bps"], pas), (2.0, 10.0, PAS_FRACTION))
        self.assertEqual((principal["reglement"], defavorable["reglement"]), ("historique", "historique_plus_un"))


if __name__ == "__main__":
    unittest.main()
