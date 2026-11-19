"""Tests du pullback Daily : prix fictifs, sans accès réseau."""

from datetime import date, timedelta
from decimal import Decimal
import unittest

from etape_02_pullback import (
    calculer_retracement,
    est_pivot,
    est_sommet_reference,
    scanner_pullbacks,
)


def jeu_pullback(position_sommet=60, pas=1.0, sommet=None, creux=None):
    """Prix fictifs cohérents, avec un sommet puis onze séances de repli."""
    cloture_sommet = 100.0 + pas * position_sommet
    sommet = cloture_sommet + 10 * pas if sommet is None else sommet
    creux = cloture_sommet - 15 * pas if creux is None else creux
    bougies = []
    jour = date(2025, 7, 7)
    while len(bougies) < position_sommet + 12:
        # Dates fictives : on saute le week-end et le Labor Day de 2025.
        if jour.weekday() < 5 and jour != date(2025, 9, 1):
            position = len(bougies)
            cloture = 100.0 + pas * position
            high, low = cloture + pas, cloture - pas
            if position == position_sommet - 5:
                low = creux
            if position == position_sommet:
                high = sommet
            if position > position_sommet:
                cloture = cloture_sommet
                high, low = sommet - pas, cloture_sommet
            bougies.append({"date": jour, "high": high, "low": low, "cloture": cloture})
        jour += timedelta(days=1)
    return bougies


def jeu_pullback_decimal(base, pas, sommet, creux):
    """Construit les prix décimaux exacts des deux tests de régression."""
    bougies = jeu_pullback()
    base, pas = Decimal(base), Decimal(pas)
    for position, bougie in enumerate(bougies):
        cloture = base + pas * min(position, 60)
        bougie.update(
            cloture=float(cloture), high=float(cloture + pas), low=float(cloture - pas)
        )
        if position == 55:
            bougie["low"] = float(Decimal(creux))
        if position == 60:
            bougie["high"] = float(Decimal(sommet))
        if position > 60:
            bougie.update(high=float(Decimal(sommet) - 1), low=float(cloture))
    return bougies


class TestPivots(unittest.TestCase):
    def test_sommet_connu_uniquement_apres_deux_seances(self):
        bougies = [{"high": prix, "low": 50} for prix in (90, 95, 100, 96, 91)]
        self.assertIsNone(est_pivot(bougies, 2, "sommet", 2))
        self.assertIsNone(est_pivot(bougies, 2, "sommet", 3))
        self.assertIs(est_pivot(bougies, 2, "sommet", 4), True)

    def test_creux_connu_uniquement_apres_deux_seances(self):
        bougies = [{"high": 100, "low": prix} for prix in (80, 75, 70, 74, 79)]
        self.assertIsNone(est_pivot(bougies, 2, "creux", 3))
        self.assertIs(est_pivot(bougies, 2, "creux", 4), True)

    def test_deux_seances_precedentes_sont_necessaires(self):
        bougies = [{"high": 100, "low": 50} for _ in range(5)]
        for position in (0, 1):
            with self.subTest(position=position):
                self.assertIsNone(est_pivot(bougies, position, "sommet", 4))

    def test_une_egalite_avec_un_voisin_refuse_le_pivot(self):
        for type_pivot, champ in (("sommet", "high"), ("creux", "low")):
            for voisin in (0, 1, 3, 4):
                with self.subTest(type_pivot=type_pivot, voisin=voisin):
                    bougies = [{"high": 90, "low": 80} for _ in range(5)]
                    bougies[2] = {"high": 100, "low": 70}
                    bougies[voisin][champ] = bougies[2][champ]
                    self.assertIs(est_pivot(bougies, 2, type_pivot, 4), False)


class TestSommetReference(unittest.TestCase):
    def test_exactement_20_seances_precedentes_suffisent(self):
        bougies = [{"high": 90, "low": 80} for _ in range(23)]
        bougies[20]["high"] = 100
        self.assertIsNone(est_sommet_reference(bougies, 20, 21))
        self.assertIs(est_sommet_reference(bougies, 20, 22), True)

    def test_19_seances_precedentes_ne_suffisent_pas(self):
        bougies = [{"high": 90, "low": 80} for _ in range(22)]
        bougies[19]["high"] = 100
        self.assertIsNone(est_sommet_reference(bougies, 19, 21))

    def test_record_exclut_la_21e_seance_precedente(self):
        bougies = [{"high": 90, "low": 80} for _ in range(24)]
        bougies[0]["high"] = 1000  # Hors de la fenêtre des vingt précédentes.
        bougies[21]["high"] = 100
        self.assertIs(est_sommet_reference(bougies, 21, 23), True)

    def test_egalite_dans_les_20_precedentes_refuse_le_record(self):
        bougies = [{"high": 90, "low": 80} for _ in range(23)]
        bougies[0]["high"] = 100
        bougies[20]["high"] = 100
        self.assertIs(est_sommet_reference(bougies, 20, 22), False)


class TestRetracement(unittest.TestCase):
    def test_ratio_40_pour_cent(self):
        self.assertEqual(calculer_retracement(170, 145, 160), 0.40)

    def test_limite_50_pour_cent_et_depassement(self):
        self.assertEqual(calculer_retracement(170, 145, 157.5), 0.50)
        self.assertGreater(calculer_retracement(170, 145, 157.49), 0.50)

    def test_hausse_nulle_ou_negative_refusee(self):
        for sommet, creux in ((100, 100), (99, 100)):
            with self.subTest(sommet=sommet, creux=creux):
                with self.assertRaisesRegex(ValueError, "strictement positive"):
                    calculer_retracement(sommet, creux, 90)


class TestScannerPullbacks(unittest.TestCase):
    def test_confirmation_j2_puis_bornes_j3_et_j10(self):
        bougies = jeu_pullback()
        tableau = scanner_pullbacks(bougies)
        for position in range(62):
            with self.subTest(position=position):
                self.assertIsNone(tableau[position]["date_sommet"])
        self.assertEqual(tableau[62]["date_sommet"], bougies[60]["date"])
        self.assertEqual(tableau[62]["date_confirmation_sommet"], bougies[62]["date"])
        self.assertEqual(tableau[62]["age_seances"], 2)
        self.assertEqual(tableau[62]["statut"], "ATTENTE_J3")
        self.assertIs(tableau[62]["admissible"], False)
        self.assertEqual(tableau[63]["age_seances"], 3)
        self.assertIs(tableau[63]["admissible"], True)
        self.assertEqual(tableau[70]["age_seances"], 10)
        self.assertEqual(tableau[70]["statut"], "ADMISSIBLE")
        self.assertIs(tableau[70]["admissible"], True)
        self.assertEqual(tableau[70]["statut_apres_cloture"], "EXPIREE")
        self.assertEqual(tableau[71]["statut"], "AUCUNE_CONFIGURATION")
        self.assertIsNone(tableau[71]["date_sommet"])

    def test_les_bougies_futures_ne_modifient_pas_le_passe(self):
        bougies = jeu_pullback()
        historique_court = scanner_pullbacks(bougies[:63])
        historique_complet = scanner_pullbacks(bougies)
        self.assertEqual(historique_court, historique_complet[:63])
        autres_bougies = [dict(bougie) for bougie in bougies]
        for bougie in autres_bougies[63:]:
            bougie.update(high=500, low=150, cloture=400)
        historique_modifie = scanner_pullbacks(autres_bougies)
        self.assertEqual(historique_court, historique_modifie[:63])

    def test_dernier_creux_j_moins_1_deja_connu_a_j2(self):
        bougies = jeu_pullback()
        bougies[59]["low"] = 150
        tableau = scanner_pullbacks(bougies)
        self.assertEqual(tableau[62]["date_creux"], bougies[59]["date"])
        self.assertEqual(tableau[62]["date_confirmation_creux"], bougies[61]["date"])
        self.assertEqual(tableau[62]["creux_reference"], 150)

    def test_creux_du_jour_du_sommet_exclu_et_low_j0_hors_repli(self):
        bougies = jeu_pullback()
        bougies[60]["low"] = 140
        self.assertIs(est_pivot(bougies, 60, "creux", 62), True)
        tableau = scanner_pullbacks(bougies)
        self.assertEqual(tableau[62]["date_creux"], bougies[55]["date"])
        self.assertEqual(tableau[62]["creux_reference"], 145)
        self.assertEqual(tableau[62]["plus_bas_repli"], 160)

    def test_profondeur_exactement_50_acceptee_depassement_definitif(self):
        for low, admissible in ((157.5, True), (157.49, False)):
            with self.subTest(low=low):
                bougies = jeu_pullback()
                bougies[63]["low"] = low
                tableau = scanner_pullbacks(bougies)
                self.assertIs(tableau[63]["admissible"], admissible)
                self.assertIs(tableau[63]["profondeur_respectee"], admissible)
                if not admissible:
                    self.assertEqual(tableau[63]["statut"], "INVALIDE")
                    self.assertIn("RETRACEMENT_SUPERIEUR_50", tableau[63]["motif"])
                    self.assertEqual(tableau[64]["statut"], "AUCUNE_CONFIGURATION")

    def test_low_exactement_4_pour_cent_sous_sma_tolere(self):
        for ecart, admissible in ((0.0, True), (-0.01, False)):
            with self.subTest(ecart=ecart):
                bougies = jeu_pullback(creux=100)
                sma_precedente = sum(bougie["cloture"] for bougie in bougies[43:63]) / 20
                bougies[63]["low"] = float(
                    Decimal("0.96") * Decimal(str(sma_precedente))
                ) + ecart
                tableau = scanner_pullbacks(bougies)
                self.assertIs(tableau[63]["sma_respectee"], admissible)
                self.assertIs(tableau[63]["profondeur_respectee"], True)
                self.assertIs(tableau[63]["admissible"], admissible)
                if not admissible:
                    self.assertIn("LOW_SOUS_SMA20_PRECEDENTE", tableau[63]["motif"])
                    self.assertEqual(tableau[64]["statut"], "AUCUNE_CONFIGURATION")

    def test_sma_precedente_recalculee_a_chaque_seance(self):
        bougies = jeu_pullback(creux=100)
        sma_j0 = sum(bougie["cloture"] for bougie in bougies[41:61]) / 20
        sma_j4 = sum(bougie["cloture"] for bougie in bougies[45:65]) / 20
        bougies[65]["low"] = 0.96 * sma_j4 - 0.01
        self.assertGreater(bougies[65]["low"], 0.96 * sma_j0)
        tableau = scanner_pullbacks(bougies)
        self.assertEqual(tableau[65]["statut"], "INVALIDE")
        self.assertIn("LOW_SOUS_SMA20_PRECEDENTE", tableau[65]["motif"])

    def test_breach_j1_pris_en_compte_des_confirmation_j2(self):
        bougies = jeu_pullback(creux=100)
        sma_j0 = sum(bougie["cloture"] for bougie in bougies[41:61]) / 20
        bougies[61]["low"] = 0.96 * sma_j0 - 0.01
        tableau = scanner_pullbacks(bougies)
        self.assertEqual(tableau[62]["statut"], "INVALIDE")
        self.assertIn("LOW_SOUS_SMA20_PRECEDENTE", tableau[62]["motif"])
        self.assertEqual(tableau[63]["statut"], "AUCUNE_CONFIGURATION")

    def test_tendance_interrompue_invalide_definitivement(self):
        bougies = jeu_pullback(pas=0.1, sommet=110, creux=90)
        bougies[63].update(cloture=103, low=102)
        tableau = scanner_pullbacks(bougies)
        self.assertIs(tableau[63]["tendance_daily"], False)
        self.assertIs(tableau[63]["sma_respectee"], True)
        self.assertIs(tableau[63]["profondeur_respectee"], True)
        self.assertEqual(tableau[63]["statut"], "INVALIDE")
        self.assertIn("TENDANCE_INTERROMPUE", tableau[63]["motif"])
        self.assertEqual(tableau[64]["statut"], "AUCUNE_CONFIGURATION")

    def test_nouveau_high_invalide_meme_si_son_pivot_echoue(self):
        bougies = jeu_pullback()
        for position in range(64, len(bougies)):
            bougies[position]["high"] = 175 + position - 64
        self.assertIs(est_pivot(bougies, 64, "sommet", 66), False)
        tableau = scanner_pullbacks(bougies)
        self.assertEqual(tableau[64]["statut"], "INVALIDE")
        self.assertIn("NOUVEAU_HIGH", tableau[64]["motif"])
        for ligne in tableau[65:]:
            self.assertEqual(ligne["statut"], "AUCUNE_CONFIGURATION")
            self.assertIsNone(ligne["date_sommet"])

    def test_high_egal_au_sommet_apres_confirmation_ne_invalide_pas(self):
        bougies = jeu_pullback()
        bougies[64]["high"] = 170
        tableau = scanner_pullbacks(bougies)
        for position in (64, 65, 66):
            with self.subTest(position=position):
                self.assertEqual(tableau[position]["statut"], "ADMISSIBLE")
                self.assertIs(tableau[position]["admissible"], True)
                self.assertEqual(tableau[position]["date_sommet"], bougies[60]["date"])
                self.assertNotIn("NOUVEAU_HIGH", tableau[position]["motif"])

    def test_nouveau_record_cree_sa_configuration_seulement_a_son_j2(self):
        bougies = jeu_pullback()
        bougies[64]["high"] = 175
        self.assertIs(est_sommet_reference(bougies, 64, 66), True)
        tableau = scanner_pullbacks(bougies)
        # L'ancienne configuration est invalidée dès le High supérieur, à J0.
        self.assertEqual(tableau[64]["statut"], "INVALIDE")
        self.assertIn("NOUVEAU_HIGH", tableau[64]["motif"])
        self.assertEqual(tableau[64]["date_sommet"], bougies[60]["date"])
        self.assertEqual(tableau[65]["statut"], "AUCUNE_CONFIGURATION")
        self.assertIsNone(tableau[65]["date_sommet"])
        # Le nouveau sommet devient connu deux séances après son apparition.
        self.assertEqual(tableau[66]["date_sommet"], bougies[64]["date"])
        self.assertEqual(tableau[66]["date_confirmation_sommet"], bougies[66]["date"])
        self.assertEqual(tableau[66]["sommet"], 175)
        self.assertEqual(tableau[66]["age_seances"], 2)
        self.assertEqual(tableau[66]["statut"], "ATTENTE_J3")
        self.assertIs(tableau[66]["admissible"], False)
        self.assertEqual(tableau[67]["age_seances"], 3)
        self.assertEqual(tableau[67]["statut"], "ADMISSIBLE")
        self.assertIs(tableau[67]["admissible"], True)

    def test_depassement_de_profondeur_a_j10_invalide_avant_expiration(self):
        bougies = jeu_pullback()
        bougies[70]["low"] = 157.49
        tableau = scanner_pullbacks(bougies)
        self.assertIs(tableau[69]["admissible"], True)
        self.assertEqual(tableau[70]["age_seances"], 10)
        self.assertEqual(tableau[70]["statut"], "INVALIDE")
        self.assertEqual(tableau[70]["statut_apres_cloture"], "INVALIDE")
        self.assertIs(tableau[70]["admissible"], False)
        self.assertIn("RETRACEMENT_SUPERIEUR_50", tableau[70]["motif"])
        self.assertEqual(tableau[71]["statut"], "AUCUNE_CONFIGURATION")

    def test_regression_50_pour_cent_sur_prix_decimaux(self):
        self.assertEqual(calculer_retracement(100.01, 90.03, 95.02), 0.5)
        for low, admissible in ((95.02, True), (95.01999, False)):
            with self.subTest(low=low):
                bougies = jeu_pullback_decimal("90", "0.1", "100.01", "90.03")
                bougies[63]["low"] = low
                tableau = scanner_pullbacks(bougies)
                self.assertEqual(tableau[63]["sommet"], 100.01)
                self.assertEqual(tableau[63]["creux_reference"], 90.03)
                self.assertIs(tableau[63]["sma_respectee"], True)
                self.assertIs(tableau[63]["profondeur_respectee"], admissible)
                self.assertIs(tableau[63]["admissible"], admissible)
                if admissible:
                    self.assertEqual(tableau[63]["retracement"], 0.5)
                else:
                    self.assertGreater(tableau[63]["retracement"], 0.5)
                    self.assertEqual(tableau[63]["statut"], "INVALIDE")
                    self.assertIn("RETRACEMENT_SUPERIEUR_50", tableau[63]["motif"])

    def test_regression_4_pour_cent_sur_sma_decimale(self):
        for low, respecte in ((96.1728, True), (96.172799, False)):
            with self.subTest(low=low):
                bougies = jeu_pullback_decimal("99.675", "0.01", "103", "85")
                # Le contrôle de J1 utilise la SMA20 de J0, exactement 100.18.
                bougies[61]["low"] = low
                tableau = scanner_pullbacks(bougies)
                self.assertEqual(tableau[60]["sma20"], 100.18)
                self.assertIs(tableau[62]["profondeur_respectee"], True)
                self.assertIs(tableau[62]["sma_respectee"], respecte)
                if respecte:
                    self.assertEqual(tableau[63]["statut"], "ADMISSIBLE")
                    self.assertIs(tableau[63]["admissible"], True)
                else:
                    self.assertEqual(tableau[62]["statut"], "INVALIDE")
                    self.assertIn("LOW_SOUS_SMA20_PRECEDENTE", tableau[62]["motif"])
                    self.assertEqual(tableau[63]["statut"], "AUCUNE_CONFIGURATION")

    def test_tendance_j1_inconnue_reste_non_evaluable(self):
        bougies = jeu_pullback(position_sommet=52)
        tableau = scanner_pullbacks(bougies)
        self.assertIsNone(tableau[53]["tendance_daily"])
        self.assertIs(tableau[54]["tendance_daily"], True)
        for position in range(54, 63):
            with self.subTest(position=position):
                self.assertIsNone(tableau[position]["tendance_continue"])
                self.assertIsNone(tableau[position]["admissible"])
                self.assertEqual(tableau[position]["statut"], "NON_EVALUABLE")

    def test_violation_certaine_prime_sur_tendance_inconnue(self):
        bougies = jeu_pullback(position_sommet=52, creux=80)
        sma_j0 = sum(bougie["cloture"] for bougie in bougies[33:53]) / 20
        bougies[53]["low"] = 0.96 * sma_j0 - 0.01
        tableau = scanner_pullbacks(bougies)
        self.assertIsNone(tableau[54]["tendance_continue"])
        self.assertIs(tableau[54]["sma_respectee"], False)
        self.assertEqual(tableau[54]["statut"], "INVALIDE")
        self.assertIs(tableau[54]["admissible"], False)

    def test_creux_reference_absent_rend_non_evaluable(self):
        bougies = jeu_pullback()
        bougies[55]["low"] = bougies[55]["cloture"] - 1
        tableau = scanner_pullbacks(bougies)
        self.assertIsNone(tableau[63]["creux_reference"])
        self.assertIsNone(tableau[63]["retracement"])
        self.assertEqual(tableau[63]["statut"], "NON_EVALUABLE")
        self.assertIsNone(tableau[63]["admissible"])


if __name__ == "__main__":
    unittest.main()
