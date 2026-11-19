"""Test de la page : on l'exécute sans navigateur, en mode démonstration (prix fictifs)."""

import os
import unittest

from streamlit.testing.v1 import AppTest

from configuration import EXEMPLE, VARIABLE


FIXED = "IBKR_CASH_AUTO_FRACTIONS_FIXED"
TIERED = "IBKR_CASH_AUTO_FRACTIONS_TIERED"
THEORIQUE = "THEORIQUE_SANS_COUTS"
PERSONNALISEE = "PERSONNALISEE"


def setUpModule():
    """La page lit toujours la configuration d'exemple : le résultat ne dépend pas du PC."""
    global _AVANT
    _AVANT = os.environ.get(VARIABLE)
    os.environ[VARIABLE] = str(EXEMPLE)


def tearDownModule():
    if _AVANT is None:
        os.environ.pop(VARIABLE, None)
    else:
        os.environ[VARIABLE] = _AVANT


def ouvrir(section=None, moment=None, configuration=None):
    """Lance la page en démonstration : ni réseau, ni clés Alpaca, ni taux de change réels."""
    page = AppTest.from_file("tableau_de_bord.py", default_timeout=120)
    page.query_params["mode"] = "demo"
    page.run()
    if configuration is not None:
        page.selectbox(key="configuration").set_value(configuration).run()
    if moment is not None:
        page.radio(key="moment_demo").set_value(moment).run()
    if section is not None:
        page.radio(key="section").set_value(section).run()
    return page


def textes(page):
    return " ".join(str(element.value) for element in page.markdown)


def legendes(page):
    return " ".join(str(element.value) for element in page.caption)


def chiffres(page):
    return {element.label: element.value for element in page.metric}


def sans_erreur(test, page):
    test.assertFalse(page.exception, [str(erreur.value) for erreur in page.exception])


class TestVueEnsemble(unittest.TestCase):
    """Réglages par défaut : configuration d'exemple, barème « Fixed » en détail."""

    @classmethod
    def setUpClass(cls):
        cls.page = ouvrir()

    def test_la_page_s_execute_sans_erreur(self):
        sans_erreur(self, self.page)
        self.assertEqual(self.page.title[0].value, "Tableau de bord")
        self.assertIn("prix inventés", legendes(self.page))

    def test_menu_de_gauche_cinq_sections(self):
        # Les options affichées portent une icône devant le nom de la section.
        options = self.page.radio(key="section").options
        self.assertEqual([option.split("  ", 1)[1] for option in options],
                         ["Vue d'ensemble", "Analyse d'un titre", "Positions simulées", "Backtest", "Hypothèses"])
        self.assertTrue(all(option.startswith(":material/") for option in options))
        self.assertEqual(self.page.radio(key="section").value, "Vue d'ensemble")

    def test_carte_du_titre_prix_verdict_et_conditions(self):
        self.assertIn("**FICTIF**", textes(self.page))
        self.assertIn("$", chiffres(self.page)["Dernier prix"])
        self.assertIn("Tendance", textes(self.page))
        self.assertIn("Déclencheur", textes(self.page))
        self.assertIn("Entrée simulée le", legendes(self.page))

    def test_chiffres_du_portefeuille_sans_le_mot_net(self):
        for libelle in ("Valorisation", "Positions prises", "Résultat après coûts simulés", "Coûts simulés"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, chiffres(self.page))
        self.assertEqual(chiffres(self.page)["Positions prises"], "1 / 1")
        self.assertNotIn("Résultat net", textes(self.page) + legendes(self.page))
        self.assertIn("pas un résultat net", legendes(self.page))

    def test_baremes_compares_sans_en_choisir_un(self):
        comparaison = self.page.dataframe[0].value
        self.assertEqual(list(comparaison["Barème"]), ["IBKR · Fixed", "IBKR · Tiered"])
        self.assertEqual(list(comparaison["Prises"]), [1, 1])
        couts = list(comparaison["Coûts"])
        self.assertGreater(couts[0], couts[1])   # « Fixed » coûte plus cher sur un petit ordre

    def test_bareme_par_defaut_issu_de_la_configuration(self):
        self.assertEqual(self.page.session_state["configuration"], FIXED)
        self.assertEqual(self.page.selectbox(key="configuration").format_func(TIERED), "IBKR · Tiered")
        self.assertEqual((self.page.session_state["capital"], self.page.session_state["usd_depart"]), (1000.0, 0.0))

    def test_bouton_analyser_ouvre_le_titre(self):
        page = ouvrir()
        page.button(key="ouvrir-FICTIF").click().run()
        sans_erreur(self, page)
        self.assertEqual(page.session_state["section"], "Analyse d'un titre")
        self.assertEqual(page.title[0].value, "Analyse d'un titre")


class TestAnalyse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = ouvrir("Analyse d'un titre")

    def test_niveaux_conditions_et_graphiques(self):
        sans_erreur(self, self.page)
        for libelle in ("Sommet de référence", "Plus bas du repli", "Repli", "Âge"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, chiffres(self.page))
        for condition in ("Tendance Daily", "Pullback Daily", "Déclencheur 1 h"):
            self.assertIn(condition, textes(self.page))
        self.assertEqual(len(self.page.get("plotly_chart")), 2)

    def test_position_simulee_chiffres_cles_puis_detail(self):
        self.assertIn("**Position simulée**", textes(self.page))
        for libelle in ("Stop", "Objectif", "Quantité", "Risque prévu", "Résultat après coûts simulés"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, chiffres(self.page))
        # Le détail reste disponible, replié : niveaux, paiement, sortie, coûts, change.
        for libelle in ("Paiement de l'achat", "Sortie théorique", "Résultat de prix", "Effet de change", "Coûts simulés"):
            with self.subTest(libelle=libelle):
                self.assertIn(f":gray[{libelle}]", textes(self.page))
        self.assertIn("objectif atteint", legendes(self.page))
        self.assertIn("glissement de 2,0 point(s) de base du prix", legendes(self.page))
        self.assertIn("ce n'est pas un résultat net réaliste", legendes(self.page))

    def test_signal_en_attente_seul_le_stop_est_connu(self):
        page = ouvrir("Analyse d'un titre", "Signal à la clôture de J2")
        sans_erreur(self, page)
        self.assertIn("Stop, figé à la clôture du signal", chiffres(page))
        self.assertNotIn("Quantité", chiffres(page))
        self.assertIn("sera refusée", legendes(page))

    def test_position_ouverte_deux_heures_apres_l_entree(self):
        page = ouvrir("Analyse d'un titre", "Deux heures après l'entrée")
        sans_erreur(self, page)
        self.assertEqual(chiffres(page)["Détention"], "D1 sur 10")
        self.assertNotIn("Résultat après coûts simulés", chiffres(page))


class TestPositions(unittest.TestCase):
    def test_liquidites_journal_et_decompte(self):
        page = ouvrir("Positions simulées")
        sans_erreur(self, page)
        for libelle in ("Liquidités en EUR", "Liquidités en USD", "En attente de règlement", "Valorisation en EUR"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, chiffres(page))
        # La vente vient d'avoir lieu : son produit attend le jour de règlement suivant.
        self.assertNotEqual(chiffres(page)["En attente de règlement"], "0,00 USD")
        self.assertIn("1 entrée(s) acceptée(s) par l'étape 3 : 1 clôturée(s)", legendes(page))
        self.assertIn("objectif atteint × 1", legendes(page))
        self.assertIn("aucun cas n'est retiré", legendes(page))
        self.assertIn("fonds réglés seulement", legendes(page))


class TestBacktest(unittest.TestCase):
    def test_resultats_du_protocole_fige(self):
        page = ouvrir("Backtest")
        sans_erreur(self, page)
        self.assertIn("Pas d'avantage démontré après coûts", textes(page))
        valeurs = [element.value for element in page.metric]
        self.assertIn("-2,24 EUR", valeurs)    # développement, « Tiered », exécution principale
        self.assertIn("+10,82 EUR", valeurs)   # validation
        self.assertEqual(len(page.get("plotly_chart")), 2)
        self.assertEqual(len(page.dataframe[0].value), 10)   # 5 simulations × 2 périodes


class TestHypotheses(unittest.TestCase):
    def test_hypotheses_en_vigueur_et_etiquettes(self):
        page = ouvrir("Hypothèses")
        sans_erreur(self, page)
        self.assertIn("| Commissions |", textes(page))
        self.assertIn("Lire les étiquettes", textes(page))
        self.assertIn("Simulation uniquement", textes(page))
        self.assertEqual(page.segmented_control(key="execution").value, "principal")

    def test_execution_defavorable_dix_points_de_base(self):
        page = ouvrir("Hypothèses")
        page.segmented_control(key="execution").set_value("defavorable").run()
        sans_erreur(self, page)
        self.assertIn("10,0 point(s) de base", textes(page))

    def test_sans_couts_le_resultat_est_dit_brut_theorique(self):
        page = ouvrir(configuration=THEORIQUE)
        sans_erreur(self, page)
        self.assertIn("Résultat brut théorique", chiffres(page))
        self.assertNotIn("Résultat après coûts simulés", chiffres(page))

    def test_personnalisee_frais_et_actions_entieres_position_refusee_mais_visible(self):
        page = ouvrir("Hypothèses", configuration=PERSONNALISEE)
        page.number_input(key="capital").set_value(400.0)
        page.selectbox(key="commissions").set_value("ibkr_fixe").run()
        sans_erreur(self, page)
        # Les réglages survivent au changement de section.
        page.radio(key="section").set_value("Analyse d'un titre").run()
        sans_erreur(self, page)
        self.assertEqual(page.session_state["capital"], 400.0)
        # 0,5 % de 400 EUR = 2 EUR : une action entière, avec ses frais, risque davantage.
        self.assertIn(":gray[Plus petite quantité]", textes(page))
        self.assertIn("même la plus petite quantité dépasse une limite de risque", legendes(page))
        page.radio(key="section").set_value("Vue d'ensemble").run()
        self.assertEqual(chiffres(page)["Positions prises"], "0 / 1")

    def test_personnalisee_usd_deja_detenus_achat_sans_conversion(self):
        page = ouvrir("Hypothèses", configuration=PERSONNALISEE)
        page.number_input(key="capital").set_value(0.0)
        page.number_input(key="usd_depart").set_value(1000.0).run()
        page.radio(key="section").set_value("Analyse d'un titre").run()
        sans_erreur(self, page)
        self.assertIn("**Aucune conversion**", textes(page))


if __name__ == "__main__":
    unittest.main()
