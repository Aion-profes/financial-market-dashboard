"""Tests des graphiques : on vérifie ce qui est tracé, sans navigateur ni réseau."""

from datetime import timedelta
import unittest

from etape_03_entree_1h import scenario_fictif
from etape_04_sorties_risque import (
    PAS_FRACTION, cotation_fixe, scenario_fictif_sortie, simuler_portefeuille,
)
from etat_du_jour import nombre_fr, resumer
from graphiques import (
    ECART_ETIQUETTES, HAUTEUR, JETONS, MARGES, configuration_recente,
    fenetre_ouverte, figure_daily, figure_horaire,
)
from test_etape_03_entree_1h import jeu_horaire


def noms(figure):
    return [trace.name for trace in figure.data]


def textes(figure):
    return [annotation.text for annotation in figure.layout.annotations]


class TestGraphiques(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        daily, horaires, ouverture_j3 = scenario_fictif()
        # Deux heures après l'ouverture de J3 : la bougie d'entrée est terminée.
        cls.entree = resumer("FICTIF", daily, horaires, ouverture_j3 + timedelta(hours=2))
        cls.avant = resumer("FICTIF", daily, horaires, horaires[3]["fin"])
        daily, horaires, ouverture_j3 = jeu_horaire(signal_j=5)
        cls.attente = resumer("FICTIF", daily, horaires, ouverture_j3)

    def test_daily_avec_configuration_niveaux_et_entree(self):
        figure = figure_daily(self.entree)
        self.assertEqual(noms(figure)[:3], ["Bougies Daily", "SMA20", "SMA50"])
        self.assertIn("Entrée simulée", noms(figure))
        etiquettes = textes(figure)
        for attendu in ("Sommet 120,00", "Limite 50 % 110,00", "Creux 100,00"):
            self.assertIn(attendu, etiquettes)
        self.assertTrue(any(texte.startswith("SMA20") for texte in etiquettes))
        self.assertIn("Fenêtre J3–J10", etiquettes)
        # Une seule échelle verticale, et aucun curseur ajouté sous les bougies.
        self.assertNotIn("yaxis2", figure.layout.to_plotly_json())
        self.assertFalse(figure.layout.xaxis.rangeslider.visible)

    def test_daily_reserve_les_seances_futures_de_la_fenetre(self):
        figure = figure_daily(self.entree)
        categories = list(figure.layout.xaxis.categoryarray)
        bougies = len(figure.data[0].x)
        # J3 est en cours : J3 à J10 ne sont pas encore des bougies Daily terminées.
        self.assertEqual(len(categories) - bougies, 8)
        self.assertEqual(categories[-1], self.entree["configuration"]["fenetre_fin"].strftime("%d/%m/%Y"))

    def test_daily_sans_configuration_ne_trace_aucun_niveau(self):
        self.assertIsNone(configuration_recente(self.avant))
        self.assertFalse(fenetre_ouverte(self.avant))
        figure = figure_daily(self.avant)
        self.assertEqual(noms(figure), ["Bougies Daily", "SMA20", "SMA50"])
        self.assertFalse(any(texte.startswith(("Sommet", "Limite", "Creux")) for texte in textes(figure)))
        self.assertEqual(len(figure.layout.xaxis.categoryarray), len(figure.data[0].x))

    def test_periode_limite_le_nombre_de_bougies(self):
        self.assertEqual(len(figure_daily(self.entree, nombre_seances=20).data[0].x), 20)

    def test_horaire_signal_et_entree(self):
        figure = figure_horaire(self.entree)
        self.assertEqual(noms(figure), ["Bougies 1 h", "Signal 1 h", "Entrée simulée"])
        self.assertIn("Entrée 114,20", textes(figure))
        # Seules les bougies horaires complètes sont dessinées.
        self.assertTrue(all(valeur is not None for valeur in figure.data[0].close))

    def test_horaire_en_attente_sans_signal(self):
        figure = figure_horaire(self.attente)
        self.assertEqual(noms(figure), ["Bougies 1 h"])
        self.assertTrue(fenetre_ouverte(self.attente))

    def position_fictive(self):
        """Scénario prolongé : entrée à J3, objectif atteint à D3, sans coûts."""
        daily, horaires, instant = scenario_fictif_sortie()
        etat = resumer("FICTIF", daily, horaires, instant)
        portefeuille = simuler_portefeuille([etat["marche"]], cotation_fixe(1.0), pas_quantite=PAS_FRACTION)
        return etat, portefeuille["positions"][0]

    def test_horaire_avec_position_stop_objectif_et_sortie(self):
        etat, position = self.position_fictive()
        figure = figure_horaire(etat, position=position)
        self.assertEqual(noms(figure), ["Bougies 1 h", "Signal 1 h", "Entrée simulée", "Sortie simulée"])
        etiquettes = textes(figure)
        self.assertIn(f"Stop {nombre_fr(position['stop'])}", etiquettes)
        self.assertIn(f"Objectif {nombre_fr(position['cible'])}", etiquettes)
        self.assertIn("Entrée 114,20", etiquettes)
        # Après l'achat, les niveaux du signal ne sont plus tracés sur le graphique horaire.
        self.assertFalse(any(texte.startswith(("Sommet", "Limite")) for texte in etiquettes))
        bas, haut = figure.layout.yaxis.range
        self.assertLess(bas, position["stop"])
        self.assertGreater(haut, position["cible"])

    def test_horaire_position_refusee_garde_les_niveaux_du_signal(self):
        etat, position = self.position_fictive()
        refusee = dict(position, statut="REFUSEE", motif="PAS_DE_POSITION_TAILLE_INSUFFISANTE")
        etiquettes = textes(figure_horaire(etat, position=refusee))
        self.assertFalse(any(texte.startswith(("Stop", "Objectif")) for texte in etiquettes))
        self.assertTrue(any(texte.startswith("Sommet") for texte in etiquettes))
        self.assertEqual(etiquettes, textes(figure_horaire(etat)))

    def test_etiquettes_de_droite_ne_se_chevauchent_pas(self):
        for figure in (figure_daily(self.entree), figure_horaire(self.entree)):
            bas, haut = figure.layout.yaxis.range
            pixels = (HAUTEUR - MARGES["t"] - MARGES["b"]) / (haut - bas)
            positions = sorted((annotation.y - bas) * pixels - annotation.ay
                               for annotation in figure.layout.annotations if annotation.showarrow)
            ecarts = [suivante - precedente for precedente, suivante in zip(positions, positions[1:])]
            self.assertTrue(all(ecart >= ECART_ETIQUETTES - 0.01 for ecart in ecarts), ecarts)

    def test_mode_sombre_utilise_ses_propres_couleurs(self):
        clair, sombre = figure_daily(self.entree, "light"), figure_daily(self.entree, "dark")
        self.assertEqual(clair.data[1].line.color, JETONS["light"]["sma20"])
        self.assertEqual(sombre.data[1].line.color, JETONS["dark"]["sma20"])
        self.assertEqual(sombre.data[0].increasing.fillcolor, JETONS["dark"]["surface"])

    def test_aucune_donnee_aucune_figure(self):
        vide = resumer("FICTIF", [], [], self.entree["instant"])
        self.assertIsNone(figure_daily(vide))
        self.assertIsNone(figure_horaire(vide))


if __name__ == "__main__":
    unittest.main()
