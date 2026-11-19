"""Tests causaux du déclencheur horaire, avec prix fictifs et sans réseau."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import unittest

from etape_02_pullback import scanner_pullbacks
from etape_03_entree_1h import (
    construire_grille,
    declencheur_horaire,
    scanner_entrees,
)


def jeu_horaire(signal_j=2):
    """Hausse fictive 100→120, repli à 112 et première cassure au jour choisi."""
    grille = construire_grille(date(2025, 1, 6), date(2025, 5, 31))
    sessions = list(dict.fromkeys(ligne["session"] for ligne in grille))[:72]
    daily = []
    for position, jour in enumerate(sessions):
        cloture = 80.0 + 0.5 * position
        high, low = cloture + 0.5, cloture - 0.5
        if position == 58:
            low = 100.0
        if position == 60:
            high = 120.0
        if position > 60:
            cloture = 114.0 + 0.1 * (position - 61)
            high = 117.0 if position == 61 else (116.0 if position == 62 else 118.0)
            low = 112.0
        daily.append({"date": jour, "high": high, "low": low, "cloture": cloture})
    horaires = []
    for position in range(62, 72):
        creneaux = [ligne for ligne in grille if ligne["session"] == sessions[position]]
        for numero, creneau in enumerate(creneaux):
            ligne = dict(creneau, ouverture=112.8, high=115.0, low=112.0, cloture=112.8)
            if numero == 0:
                ligne["high"] = daily[position]["high"]
                if position > 62:
                    ligne["ouverture"] = 114.2
            if numero == len(creneaux) - 1:
                ligne["cloture"] = daily[position]["cloture"]
            if position == 60 + signal_j and numero == len(creneaux) - 2:
                ligne["high"] = 113.0
            horaires.append(ligne)
    ouverture_j3 = next(ligne["debut"] for ligne in horaires if ligne["session"] == sessions[63])
    return daily, horaires, ouverture_j3


def evenements(journal, statut):
    return [ligne for ligne in journal if ligne["statut"] == statut]


class TestComparaisonHoraire(unittest.TestCase):
    def test_cloture_strictement_superieure(self):
        self.assertIs(declencheur_horaire(114, 113), True)

    def test_egalite_refusee(self):
        self.assertIs(declencheur_horaire(113, 113), False)

    def test_simple_meche_sans_cloture_suffisante(self):
        # Un High actuel à 114 n'est pas un argument du déclencheur.
        self.assertIs(declencheur_horaire(112.8, 113), False)

    def test_prix_manquant_distinct_de_false(self):
        self.assertIsNone(declencheur_horaire(None, 113))
        self.assertIsNone(declencheur_horaire(114, None))

    def test_prix_invalides_refuses(self):
        for prix in (float("nan"), float("inf"), 0, -1, True):
            with self.subTest(prix=prix), self.assertRaises(ValueError):
                declencheur_horaire(prix, 113)


class TestChronologieHoraire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily_base, cls.horaires_base, cls.ouverture_j3 = jeu_horaire()

    def setUp(self):
        self.daily = deepcopy(self.daily_base)
        self.horaires = deepcopy(self.horaires_base)

    def scanner(self, limite=None):
        return scanner_entrees(self.daily, self.horaires, limite or self.ouverture_j3)

    def premiere_j3(self):
        return next(ligne for ligne in self.horaires if ligne["debut"] == self.ouverture_j3)

    def test_signal_cloture_j2_puis_entree_j3_daily_reste_attente(self):
        journal = self.scanner()
        signaux = evenements(journal, "SIGNAL")
        entrees = evenements(journal, "ENTREE_ACCEPTEE")
        self.assertEqual(len(signaux), 1)
        self.assertEqual(len(entrees), 1)
        signal, entree = signaux[0], entrees[0]
        self.assertEqual(signal["age_seances"], 2)
        self.assertEqual(signal["statut_daily"], "ATTENTE_J3")
        self.assertEqual(signal["duree_minutes"], 30)
        self.assertEqual(signal["high_precedent"], 113.0)
        self.assertAlmostEqual(signal["cloture_signal"], 114.1)
        self.assertEqual(signal["ouverture_attendue"], self.ouverture_j3)
        self.assertEqual(entree["age_seances"], 3)
        self.assertEqual(entree["statut_daily"], "ATTENTE_J3")
        self.assertIs(entree["entree_simulee"], True)
        self.assertEqual(entree["instant"], self.ouverture_j3)
        self.assertEqual(entree["prix_entree"], 114.2)
        self.assertEqual(scanner_pullbacks(self.daily)[62]["statut"], "ATTENTE_J3")

    def test_aucun_signal_avant_confirmation_effective_j2(self):
        barres_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]]
        barres_j2[2].update(high=116.0, cloture=115.5)
        journal = self.scanner(barres_j2[-1]["fin"] - timedelta(seconds=1))
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))

    def test_gap_sous_50_pour_cent_annule_entree(self):
        self.premiere_j3().update(ouverture=109.0, low=109.0)
        journal = self.scanner()
        refus = evenements(journal, "ENTREE_ANNULEE")
        self.assertEqual(len(refus), 1)
        self.assertIn("RETRACEMENT_SUPERIEUR_50", refus[0]["motif"])
        self.assertIs(refus[0]["entree_simulee"], False)
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))

    def test_ouverture_exactement_50_pour_cent_acceptee(self):
        self.premiere_j3().update(ouverture=110.0, low=110.0)
        entrees = evenements(self.scanner(), "ENTREE_ACCEPTEE")
        self.assertEqual(len(entrees), 1)
        self.assertEqual(entrees[0]["prix_entree"], 110.0)

    def test_gap_nouveau_high_daily_annule_entree(self):
        self.premiere_j3().update(ouverture=120.01, high=121.0)
        refus = evenements(self.scanner(), "ENTREE_ANNULEE")
        self.assertEqual(len(refus), 1)
        self.assertIn("NOUVEAU_HIGH", refus[0]["motif"])

    def test_open_egal_sommet_daily_ne_invalide_pas(self):
        self.premiere_j3().update(ouverture=120.0, high=120.0)
        entrees = evenements(self.scanner(), "ENTREE_ACCEPTEE")
        self.assertEqual(len(entrees), 1)
        self.assertEqual(entrees[0]["prix_entree"], 120.0)

    def test_open_sous_niveau_horaire_seul_ne_suffit_pas_a_annuler(self):
        self.premiere_j3().update(ouverture=111.0, low=111.0)
        entrees = evenements(self.scanner(), "ENTREE_ACCEPTEE")
        self.assertEqual(len(entrees), 1)
        self.assertEqual(entrees[0]["prix_entree"], 111.0)

    def test_sma_precedente_egalite_4_pour_cent_et_depassement(self):
        # Une référence plus basse isole le contrôle SMA de celui des 50 %.
        self.daily[58]["low"] = 80.0
        sma_j2 = scanner_pullbacks(self.daily)[62]["sma20"]
        seuil = float(Decimal(str(sma_j2)) * Decimal("0.96"))
        for ouverture, accepte in ((seuil, True), (seuil - 0.00001, False)):
            with self.subTest(ouverture=ouverture):
                self.premiere_j3().update(ouverture=ouverture, low=ouverture)
                journal = self.scanner()
                self.assertEqual(bool(evenements(journal, "ENTREE_ACCEPTEE")), accepte)
                if not accepte:
                    refus = evenements(journal, "ENTREE_ANNULEE")
                    self.assertEqual(len(refus), 1)
                    self.assertIn("LOW_SOUS_SMA20_PRECEDENTE", refus[0]["motif"])

    def test_high_low_close_futurs_entree_inconnus_a_ouverture(self):
        attendu = self.scanner()
        self.premiere_j3().update(high=float("nan"), low=-1, cloture=None)
        self.daily[63].update(high=999, low=1, cloture=1)
        self.assertEqual(self.scanner(), attendu)

    def test_invalidation_apres_entree_ne_efface_pas_entree_passee(self):
        attendu = evenements(self.scanner(), "ENTREE_ACCEPTEE")
        premiere = self.premiere_j3()
        premiere.update(high=125.0, low=109.0, cloture=114.2)
        self.daily[63].update(high=125.0, low=109.0)
        journal = self.scanner(premiere["fin"])
        self.assertEqual(evenements(journal, "ENTREE_ACCEPTEE"), attendu)

    def test_daily_du_jour_future_non_utilisee_le_matin(self):
        attendu = evenements(self.scanner(), "ENTREE_ACCEPTEE")
        self.daily[63].update(high=118.0, low=90.0, cloture=90.0)
        self.assertEqual(evenements(self.scanner(), "ENTREE_ACCEPTEE"), attendu)

    def test_ajout_futur_ne_change_pas_journal_passe(self):
        journal = self.scanner()
        daily_court = self.daily[:63]
        horaires_courts = [ligne for ligne in self.horaires if ligne["debut"] <= self.ouverture_j3]
        self.assertEqual(scanner_entrees(daily_court, horaires_courts, self.ouverture_j3), journal)

    def test_open_attendu_manquant_pas_de_report_vers_ligne_suivante(self):
        self.horaires.remove(self.premiere_j3())
        journal = self.scanner(self.ouverture_j3 + timedelta(hours=1))
        inconnus = [ligne for ligne in journal if ligne["evenement"] == "OUVERTURE"
                    and ligne["instant"] == self.ouverture_j3]
        self.assertEqual(len(inconnus), 1)
        self.assertEqual(inconnus[0]["statut"], "NON_EVALUABLE")
        self.assertIn("OPEN", inconnus[0]["motif"])
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))

    def test_vrai_high_precedent_manquant_bloque_signal(self):
        barres_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]]
        self.horaires.remove(barres_j2[-2])
        journal = self.scanner()
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(evenements(journal, "NON_EVALUABLE"))

    def test_daily_insuffisant_reste_non_evaluable(self):
        journal = scanner_entrees(self.daily[20:], self.horaires, self.ouverture_j3)
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(evenements(journal, "NON_EVALUABLE"))

    def test_daily_manquant_ne_raccourcit_pas_le_compte_des_seances(self):
        del self.daily[61]
        journal = self.scanner()
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(evenements(journal, "NON_EVALUABLE"))

    def test_repli_invalide_dans_bougie_signal_meme_si_close_remonte(self):
        barres_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]]
        barres_j2[-1].update(high=113.5, cloture=113.0)
        self.daily[62]["cloture"] = 113.0
        premiere = self.premiere_j3()
        premiere.update(low=109.0, cloture=114.2)
        journal = self.scanner(premiere["fin"])
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(any("RETRACEMENT_SUPERIEUR_50" in ligne["motif"] for ligne in journal))

    def test_debut_analyse_apres_j2_ne_fabrique_pas_un_premier_signal(self):
        jour_j4 = self.daily[64]["date"]
        premiere_j4 = next(ligne for ligne in self.horaires if ligne["session"] == jour_j4)
        premiere_j4.update(high=118.0, cloture=116.0)
        journal = scanner_entrees(self.daily, self.horaires, premiere_j4["fin"], debut=jour_j4)
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(evenements(journal, "NON_EVALUABLE"))

    def test_daily_j2_recu_apres_cloture_avant_open_j3(self):
        derniere_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]][-1]
        reception = derniere_j2["fin"] + timedelta(minutes=5)
        self.daily[62]["disponible_a"] = reception
        journal = self.scanner()
        signaux = evenements(journal, "SIGNAL")
        self.assertEqual(len(signaux), 1)
        self.assertEqual(signaux[0]["instant"], reception)
        self.assertEqual(len(evenements(journal, "ENTREE_ACCEPTEE")), 1)

    def test_signal_horaire_recu_tardivement_avant_open_j3(self):
        derniere_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]][-1]
        reception = derniere_j2["fin"] + timedelta(minutes=5)
        derniere_j2["disponible_a"] = reception
        journal = self.scanner()
        signaux = evenements(journal, "SIGNAL")
        self.assertEqual(len(signaux), 1)
        self.assertEqual(signaux[0]["instant"], reception)
        self.assertEqual(len(evenements(journal, "ENTREE_ACCEPTEE")), 1)

    def test_daily_j2_recu_apres_open_j3_pas_entree_retroactive(self):
        reception = self.ouverture_j3 + timedelta(minutes=5)
        self.daily[62]["disponible_a"] = reception
        journal = self.scanner(reception)
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        self.assertTrue(evenements(journal, "NON_EVALUABLE"))

    def test_entree_annulee_par_gap_reste_annulee_malgre_nouvelle_cassure(self):
        premiere = self.premiere_j3()
        premiere.update(ouverture=109.0, low=109.0)
        seconde = self.horaires[self.horaires.index(premiere) + 1]
        seconde.update(high=117.0, cloture=116.0)
        journal = self.scanner(seconde["fin"])
        self.assertEqual(len(evenements(journal, "SIGNAL")), 1)
        self.assertEqual(len(evenements(journal, "ENTREE_ANNULEE")), 1)
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))

    def test_signal_recu_apres_ouverture_sans_rearmement(self):
        # Daily J2 reçu trop tard : l'ouverture J3 est manquée, sans seconde chance.
        self.daily[62]["disponible_a"] = self.ouverture_j3 + timedelta(minutes=5)
        premiere = self.premiere_j3()
        premiere.update(high=116.0, cloture=115.5)
        journal = self.scanner(premiere["fin"])
        self.assertFalse(evenements(journal, "SIGNAL"))
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))
        consommes = evenements(journal, "SANS_REARMEMENT")
        self.assertEqual(len(consommes), 2)
        self.assertTrue(all(ligne["signal_horaire"] is None for ligne in consommes))

    def test_cloture_j2_ecrit_une_seule_ligne_au_moment_du_signal(self):
        journal = self.scanner()
        instant = evenements(journal, "SIGNAL")[0]["instant"]
        clotures = [ligne for ligne in journal
                    if ligne["instant"] == instant and ligne["evenement"] == "CLOTURE"]
        self.assertEqual(len(clotures), 1)

    def test_premiere_bougie_j3_prend_reference_derniere_j2(self):
        barres_j2 = [ligne for ligne in self.horaires if ligne["session"] == self.daily[62]["date"]]
        barres_j2[-1].update(high=113.5, cloture=113.0)
        self.daily[62]["cloture"] = 113.0
        premiere = self.premiere_j3()
        premiere["cloture"] = 114.2
        journal = self.scanner(premiere["fin"])
        signaux = evenements(journal, "SIGNAL")
        entrees = evenements(journal, "ENTREE_ACCEPTEE")
        self.assertEqual(len(signaux), 1)
        self.assertEqual(signaux[0]["reference_debut"], barres_j2[-1]["debut"])
        self.assertEqual(signaux[0]["high_precedent"], 113.5)
        self.assertEqual(len(entrees), 1)
        self.assertEqual(entrees[0]["instant"], premiere["fin"])

    def test_premier_signal_unique_et_une_seule_entree(self):
        premiere = self.premiere_j3()
        premiere["cloture"] = 114.2
        journal = self.scanner(self.horaires[13]["fin"])
        self.assertEqual(len(evenements(journal, "SIGNAL")), 1)
        self.assertEqual(len(evenements(journal, "ENTREE_ACCEPTEE")), 1)

    def test_signal_fin_j10_ne_permet_jamais_ouverture_j11(self):
        daily, horaires, _ = jeu_horaire(signal_j=10)
        ouverture_j11 = next(ligne["debut"] for ligne in horaires if ligne["session"] == daily[71]["date"])
        journal = scanner_entrees(daily, horaires, ouverture_j11)
        signaux = evenements(journal, "SIGNAL")
        self.assertEqual(len(signaux), 1)
        self.assertEqual(signaux[0]["age_seances"], 10)
        refus = evenements(journal, "ENTREE_ANNULEE")
        self.assertEqual(len(refus), 1)
        self.assertEqual(refus[0]["age_seances"], 11)
        self.assertIn("J10", refus[0]["motif"])
        self.assertFalse(evenements(journal, "ENTREE_ACCEPTEE"))


if __name__ == "__main__":
    unittest.main()
