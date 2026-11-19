"""Tests des sorties et du risque : prix fictifs, calendrier réel, aucun réseau."""

from copy import deepcopy
from datetime import date, timedelta
import unittest
from zoneinfo import ZoneInfo

from etape_02_pullback import scanner_pullbacks
from etape_03_entree_1h import construire_grille, scanner_entrees
from etape_04_sorties_risque import (
    BAREMES_COMMISSIONS, CHAMPS_POSITION, CONFIGURATIONS, INSTRUMENT_FICTIF, MODES_CONVERSION,
    PAS_ENTIER, PAS_FRACTION, SCENARIOS_CHANGE, SCENARIOS_DE_COUTS, arrondir_au_pas, calculer_atr,
    calculer_cible, calculer_quantite, calculer_stop, calendrier_de_reglement, chercher_candidats,
    commission_usd, configurer, cotation_fixe, cout_conversion_eur, creer_hypotheses,
    decrire_hypotheses, decrire_position, delai_de_reglement, delais_de, dernier_prix_connu,
    distance_de_risque, facteur_de_division, instant_de_reglement, jours_feries_bancaires,
    libelle_resultat, plan_en_attente,
    preparer_marche, prix_fr, regler_achat, regler_vente, sans_couts, scenario_fictif_sortie,
    simuler_portefeuille, simuler_sortie,
)
from test_etape_03_entree_1h import jeu_horaire


AUCUN = creer_hypotheses()   # ni commission, ni coût de conversion, ni glissement
STOP, CIBLE = 96.0, 108.0   # l'exemple de la spécification : entrée 100, plus bas 97, ATR 4
un_pour_un = cotation_fixe(1.0)   # taux de change fictif : 1 USD = 1 EUR


def especes(eur=1000.0, usd=0.0):
    """Les deux soldes d'un compte : des EUR et des USD."""
    return {"EUR": eur, "USD": usd}


def taux_selon(avant, apres, bascule):
    """Taux fictif (EUR pour 1 USD) qui change après l'instant « bascule »."""
    return lambda instant: cotation_fixe(avant if instant <= bascule else apres)(instant)


def bougie_daily(cloture, high=None, low=None):
    return {"high": cloture + 0.5 if high is None else high,
            "low": cloture - 0.5 if low is None else low, "cloture": cloture}


def marche_fictif(symbole="FICTIF", premier_jour=date(2025, 7, 7), seances=12):
    """Bougies plates inventées : Open 100, High 101, Low 99, Close 100 sur chaque créneau."""
    grille = construire_grille(premier_jour, premier_jour + timedelta(days=40))
    sessions = sorted({creneau["session"] for creneau in grille})
    fins = {creneau["session"]: creneau["fin"] for creneau in grille}
    visibles = sessions[:seances]
    horaires = {creneau["debut"]: dict(creneau, ouverture=100.0, high=101.0, low=99.0, cloture=100.0)
                for creneau in grille if creneau["session"] in visibles}
    return {
        "symbole": symbole, "limite": fins[visibles[-1]], "grille": grille, "fins": fins,
        "sessions": sessions, "rangs": {session: rang for rang, session in enumerate(sessions)},
        "horaires": horaires, "journal": [],
        # Le Close Daily (100,5) diffère du Close horaire (100) pour reconnaître la sortie D10.
        "daily": {session: {"date": session, "high": 101.0, "low": 99.0, "cloture": 100.5}
                  for session in visibles},
        "receptions": {session: fins[session] for session in visibles},
        "atr": {session: 4.0 for session in visibles},
        "premiere_seance": visibles[0], "instrument": INSTRUMENT_FICTIF,
    }


def creneaux_de(marche, rang_seance):
    session = marche["sessions"][rang_seance]
    return [creneau for creneau in marche["grille"] if creneau["session"] == session]


def ajouter_entree(marche, rang_seance, numero_bougie=0, prix=100.0, plus_bas=97.0):
    """Écrit dans le journal un signal puis une entrée acceptée, comme le ferait l'étape 3."""
    creneau = creneaux_de(marche, rang_seance)[numero_bougie]
    marche["horaires"][creneau["debut"]]["ouverture"] = prix
    repere = ("configuration", rang_seance, numero_bougie)
    marche["journal"].append({"signal_horaire": True, "statut": "SIGNAL", "date_sommet": repere,
                              "instant": creneau["debut"], "plus_bas_repli": plus_bas})
    marche["journal"].append({"signal_horaire": None, "statut": "ENTREE_ACCEPTEE", "date_sommet": repere,
                              "instant": creneau["debut"], "prix_entree": prix,
                              "session": creneau["session"]})
    return creneau


class TestATR(unittest.TestCase):
    def test_quinze_seances_necessaires(self):
        bougies = [bougie_daily(100.0) for _ in range(15)]
        self.assertEqual(calculer_atr(bougies[:14]), [None] * 14)
        atr = calculer_atr(bougies)
        self.assertEqual(atr[:14], [None] * 14)
        self.assertEqual(atr[14], 1.0)   # quatorze écarts de 1,0 (High − Low)

    def test_lissage_de_wilder(self):
        bougies = [bougie_daily(100.0) for _ in range(15)] + [bougie_daily(100.0, high=110.0, low=95.0)]
        # (13 × 1 + 15) / 14 = 2
        self.assertEqual(calculer_atr(bougies)[15], 2.0)

    def test_gap_compte_dans_l_ecart_vrai(self):
        bougies = [bougie_daily(100.0)] + [bougie_daily(110.5, high=111.0, low=110.0)] * 14
        # Première séance après le gap : max(1 ; |111 − 100| ; |110 − 100|) = 11, puis treize écarts de 1.
        self.assertAlmostEqual(calculer_atr(bougies)[14], (11 + 13 * 1) / 14)


class TestStopEtCible(unittest.TestCase):
    def test_exemple_de_la_specification(self):
        self.assertEqual(calculer_stop(97, 4, "0.01"), (96.0, 96.0))
        self.assertEqual(calculer_cible(100, 96, "0.01"), (108.0, 108.0, 2.0))

    def test_stop_arrondi_vers_le_bas(self):
        self.assertEqual(calculer_stop(100, 0.33, "0.01"), (99.9175, 99.91))
        self.assertEqual(calculer_stop(100, 0.33, "0.05")[1], 99.90)

    def test_stop_exact_malgre_la_representation_des_decimaux(self):
        # En float, 90,07 − 0,25 × 0,04 vaut 90,05999… : un arrondi naïf donnerait 90,05.
        self.assertLess(90.07 - 0.25 * 0.04, 90.06)
        self.assertEqual(calculer_stop(90.07, 0.04, "0.01")[1], 90.06)

    def test_cible_arrondie_vers_le_haut_et_ratio_effectif(self):
        brute, cible, ratio = calculer_cible(344.285, 340.0, "0.01")
        self.assertEqual((brute, cible), (352.855, 352.86))   # 344,285 + 2 × 4,285 = 352,855
        self.assertAlmostEqual(ratio, (352.86 - 344.285) / 4.285)
        self.assertGreater(ratio, 2.0)

    def test_non_regression_entree_reelle_au_demi_centime(self):
        # AAPL, 16/10/2026 : l'ouverture Alpaca vaut 344,285 (et non 344,29) ; stop arrondi 339,93.
        _, stop = calculer_stop(341.6, 6.647398402601524, "0.01")
        self.assertEqual(stop, 339.93)
        self.assertEqual(distance_de_risque(344.285, stop), 4.355)
        brute, cible, ratio = calculer_cible(344.285, stop, "0.01")
        self.assertEqual((brute, cible), (352.995, 353.0))    # 344,285 + 2 × 4,355, arrondi vers le haut
        self.assertAlmostEqual(ratio, 8.715 / 4.355)
        # Avec une entrée à 344,29 tout rond, le même calcul donnerait bien 353,01.
        self.assertEqual(calculer_cible(344.29, stop, "0.01")[:2], (353.01, 353.01))

    def test_prix_affiche_sans_arrondi_trompeur(self):
        self.assertEqual(prix_fr(344.285), "344,285")   # et non « 344,29 »
        self.assertEqual(prix_fr(344.29), "344,29")
        self.assertEqual(prix_fr(100.0), "100,00")
        self.assertEqual(prix_fr(339.9), "339,90")
        self.assertEqual(prix_fr(4.355), "4,355")
        self.assertEqual(prix_fr(None), "ND")

    def test_entree_au_stop_ou_dessous_refusee(self):
        for entree in (96.0, 95.0):
            with self.subTest(entree=entree), self.assertRaises(ValueError):
                calculer_cible(entree, 96.0, "0.01")

    def test_stop_non_positif_et_prix_invalides_refuses(self):
        with self.assertRaises(ValueError):
            calculer_stop(1.0, 10.0, "0.01")
        for plus_bas, atr in ((float("nan"), 4), (97, None), (-1, 4), (97, 0)):
            with self.subTest(plus_bas=plus_bas, atr=atr), self.assertRaises(ValueError):
                calculer_stop(plus_bas, atr, "0.01")

    def test_arrondi_au_pas_dans_les_deux_sens(self):
        self.assertEqual(float(arrondir_au_pas(10.001, "0.01")), 10.0)
        self.assertEqual(float(arrondir_au_pas(10.001, "0.01", vers_le_haut=True)), 10.01)
        self.assertEqual(float(arrondir_au_pas(10.0, "0.01", vers_le_haut=True)), 10.0)


class TestCouts(unittest.TestCase):
    FIXE = BAREMES_COMMISSIONS["ibkr_fixe"]

    def test_commission_minimum_puis_plafond(self):
        self.assertEqual(commission_usd(self.FIXE, 100, 50), 1.0)      # minimum 1 USD
        self.assertEqual(commission_usd(self.FIXE, 1000, 50), 5.0)     # 0,005 USD par action
        self.assertEqual(commission_usd(self.FIXE, 0.5, 100), 0.5)     # plafond : 1 % de 50 USD
        self.assertEqual(commission_usd(self.FIXE, 0, 100), 0.0)

    def test_conversion_proportionnelle_ou_minimum(self):
        # 100 USD convertis quand 1 USD vaut 0,90 EUR : 0,03 % de 90 EUR.
        self.assertAlmostEqual(cout_conversion_eur(MODES_CONVERSION["ibkr_auto"], 100, 0.9), 0.027)
        manuelle = MODES_CONVERSION["ibkr_manuelle"]
        self.assertAlmostEqual(cout_conversion_eur(manuelle, 100, 0.9), 1.8)   # minimum 2 USD
        self.assertAlmostEqual(cout_conversion_eur(manuelle, 1_000_000, 0.9), 18.0)   # 0,002 % au-delà

    def test_sans_conversion_aucun_cout_meme_avec_un_minimum(self):
        self.assertEqual(cout_conversion_eur(MODES_CONVERSION["ibkr_manuelle"], 0, 0.9), 0.0)

    def test_hypotheses_par_defaut_sans_cout_et_noms_inconnus_refuses(self):
        self.assertTrue(sans_couts(creer_hypotheses()))
        self.assertEqual(libelle_resultat(creer_hypotheses()), "Résultat brut théorique")
        for options in ({"commissions": "ibkr_fixe"}, {"conversion": "ibkr_auto"},
                        {"glissement_par_action": 0.01}):
            with self.subTest(options=options):
                hypotheses = creer_hypotheses(**options)
                self.assertFalse(sans_couts(hypotheses))
                self.assertEqual(libelle_resultat(hypotheses), "Résultat après coûts simulés")
        for options in ({"commissions": "inconnu"}, {"conversion": "inconnu"},
                        {"scenario_change": "inconnu"}, {"glissement_par_action": -0.01}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                creer_hypotheses(**options)

    def test_description_des_hypotheses_nomme_le_glissement(self):
        self.assertIn("hypothèse de glissement nul", decrire_hypotheses(creer_hypotheses()))
        self.assertIn("0,0200 USD par action", decrire_hypotheses(creer_hypotheses(glissement_par_action=0.02)))
        self.assertIn("5,0 point(s) de base", decrire_hypotheses(creer_hypotheses(glissement_bps=5)))
        self.assertEqual(set(SCENARIOS_CHANGE), {"usd_conserves", "retour_eur"})

    def test_fractions_plancher_d_un_centime(self):
        # Ordre de 0,001 action à 100 USD (0,10 USD) : le plafond de 1 % donnerait 0,001 USD ;
        # le barème public prévoit au moins 0,01 USD pour un ordre comportant une fraction.
        self.assertEqual(commission_usd(self.FIXE, 0.001, 100), 0.01)
        self.assertEqual(commission_usd(BAREMES_COMMISSIONS["ibkr_tiered"], 0.001, 100), 0.01 + 0.0032 * 0.001)
        # L'exemple du courtier : la moitié d'une action à 10 USD coûte 0,05 USD.
        self.assertAlmostEqual(commission_usd(self.FIXE, 0.5, 10), 0.05)

    def test_bareme_tiered_minimum_et_frais_externes(self):
        tiered = BAREMES_COMMISSIONS["ibkr_tiered"]
        # 1 action à 100 USD : minimum 0,35 USD, plus 0,0032 USD de frais de place et de compensation.
        self.assertAlmostEqual(commission_usd(tiered, 1, 100), 0.3532)
        # À la vente s'ajoutent les frais réglementaires : 20,60 USD par million, soit 0,00206 USD.
        self.assertAlmostEqual(commission_usd(tiered, 1, 100, vente=True), 0.3532 + 0.00206)
        # Le barème « Fixed » est tout compris : rien de plus à la vente.
        self.assertEqual(commission_usd(self.FIXE, 1, 100, vente=True), commission_usd(self.FIXE, 1, 100))

    def test_glissement_en_points_de_base_du_prix(self):
        hypotheses = creer_hypotheses(glissement_bps=10)   # 10 points de base = 0,1 % du prix
        achat = regler_achat(especes(), 2.0, 100.0, 1.0, hypotheses)
        self.assertAlmostEqual(achat["glissement_usd"], 0.2)
        self.assertFalse(sans_couts(hypotheses))
        limite = regler_vente(especes(), 2.0, 108.0, 1.0, hypotheses, au_marche=False)
        self.assertEqual(limite["glissement_usd"], 0.0)

    def test_configurations_nommees_memes_regles_seul_le_bareme_change(self):
        fixed, pas_fixed = configurer("IBKR_CASH_AUTO_FRACTIONS_FIXED")
        tiered, pas_tiered = configurer("IBKR_CASH_AUTO_FRACTIONS_TIERED")
        self.assertEqual((fixed["nom_commissions"], tiered["nom_commissions"]), ("ibkr_fixe", "ibkr_tiered"))
        for cle in ("nom_conversion", "scenario_change", "reglement", "glissement_par_action", "glissement_bps"):
            with self.subTest(cle=cle):
                self.assertEqual(fixed[cle], tiered[cle])
        # Compte au comptant, conversion automatique, USD conservés, fractions, délai de règlement en vigueur.
        self.assertEqual((fixed["nom_conversion"], fixed["scenario_change"], fixed["reglement"]),
                         ("ibkr_auto", "usd_conserves", "historique"))
        self.assertEqual((pas_fixed, pas_tiered), (PAS_FRACTION, PAS_FRACTION))
        self.assertEqual(set(SCENARIOS_DE_COUTS) - set(CONFIGURATIONS), set())
        self.assertTrue(sans_couts(configurer("THEORIQUE_SANS_COUTS")[0]))
        with self.assertRaises(ValueError):
            configurer("IBKR_INCONNU")
        with self.assertRaises(ValueError):
            configurer("IBKR_CASH_AUTO_FRACTIONS_FIXED", "inconnu")

    def test_scenarios_d_execution_principal_et_defavorable(self):
        # Validés le 16/11/2026 : 2 points de base, puis 10 avec un jour de règlement de plus.
        principal, _ = configurer("IBKR_CASH_AUTO_FRACTIONS_TIERED")
        defavorable, _ = configurer("IBKR_CASH_AUTO_FRACTIONS_TIERED", "defavorable")
        self.assertEqual((principal["glissement_bps"], principal["reglement"]), (2.0, "historique"))
        self.assertEqual((defavorable["glissement_bps"], defavorable["reglement"]), (10.0, "historique_plus_un"))
        self.assertEqual(principal["nom_commissions"], defavorable["nom_commissions"])
        # La configuration théorique n'a ni glissement ni délai, quel que soit le scénario.
        theorique, _ = configurer("THEORIQUE_SANS_COUTS", "defavorable")
        self.assertEqual((theorique["glissement_bps"], theorique["reglement"]), (0.0, "immediat"))

    def test_glissement_defavorable_distinct_des_autres_couts(self):
        # Achat de 2 actions à 100 USD, 10 points de base : payé 100,10 par action, soit 0,20 USD de plus.
        hypotheses = creer_hypotheses("ibkr_fixe", "ibkr_auto", glissement_bps=10)
        achat = regler_achat(especes(), 2.0, 100.0, 1.0, hypotheses)
        self.assertAlmostEqual(achat["glissement_usd"], 0.2)
        self.assertAlmostEqual(achat["commission_usd"], 1.0)
        self.assertAlmostEqual(achat["usd_achetes"], 200.0 + 1.0 + 0.2)          # chaque coût une seule fois
        self.assertAlmostEqual(achat["cout_change_eur"], 0.0003 * 201.2)
        self.assertAlmostEqual(achat["couts_eur"], 1.0 + 0.2 + 0.0003 * 201.2)
        # Vente au marché : produit diminué du glissement. Vente à cours limité : jamais sous la limite.
        marche = regler_vente(especes(0.0, 0.0), 2.0, 96.0, 1.0, hypotheses)
        limite = regler_vente(especes(0.0, 0.0), 2.0, 108.0, 1.0, hypotheses, au_marche=False)
        self.assertAlmostEqual(marche["USD"], 2 * 96.0 * (1 - 0.001) - 1.0)
        self.assertAlmostEqual(limite["USD"], 2 * 108.0 - 1.0)
        with self.assertRaises(ValueError):
            creer_hypotheses(reglement="inconnu")


class TestReglements(unittest.TestCase):
    """Deux soldes, EUR et USD : une conversion n'a lieu que s'il manque des USD."""

    MANUEL = creer_hypotheses(conversion="ibkr_manuelle")                       # minimum 2 USD par conversion
    FIXE_AUTO = creer_hypotheses("ibkr_fixe", "ibkr_auto", "retour_eur")

    def test_achat_avec_des_usd_disponibles_aucune_conversion(self):
        achat = regler_achat(especes(eur=500.0, usd=500.0), 1.0, 100.0, 0.9, self.MANUEL)
        self.assertEqual((achat["EUR"], achat["USD"]), (500.0, 400.0))   # les EUR ne bougent pas
        self.assertEqual((achat["usd_achetes"], achat["cout_change_eur"], achat["couts_eur"]), (0.0, 0.0, 0.0))

    def test_conversion_necessaire_pour_le_seul_manque(self):
        # 100 USD à payer, 30 USD disponibles : on achète 70 USD à 0,90 EUR, plus le minimum de 2 USD.
        achat = regler_achat(especes(eur=1000.0, usd=30.0), 1.0, 100.0, 0.9, self.MANUEL)
        self.assertAlmostEqual(achat["usd_achetes"], 70.0)
        self.assertAlmostEqual(achat["cout_change_eur"], 2 * 0.9)
        self.assertAlmostEqual(achat["EUR"], 1000.0 - 70 * 0.9 - 1.8)
        self.assertEqual(achat["USD"], 0.0)

    def test_sans_usd_tout_l_achat_est_converti_commission_comprise(self):
        achat = regler_achat(especes(), 1.0, 100.0, 1.0, self.FIXE_AUTO)
        # 100 USD d'actions + 1 USD de commission ; conversion automatique : 0,03 % de 101.
        self.assertAlmostEqual(achat["usd_achetes"], 101.0)
        self.assertAlmostEqual(achat["cout_change_eur"], 0.0303)
        self.assertAlmostEqual(achat["couts_eur"], 1.0303)
        self.assertAlmostEqual(achat["EUR"], 1000.0 - 101.0303)

    def test_vente_qui_conserve_les_usd(self):
        vente = regler_vente(especes(eur=900.0, usd=0.0), 1.0, 108.0, 0.9, self.MANUEL, au_marche=False)
        self.assertEqual((vente["EUR"], vente["USD"]), (900.0, 108.0))   # aucun retour forcé en EUR
        self.assertEqual((vente["usd_vendus"], vente["cout_change_eur"]), (0.0, 0.0))

    def test_vente_reconvertie_en_eur_dans_le_scenario_retour_eur(self):
        hypotheses = creer_hypotheses(conversion="ibkr_manuelle", scenario_change="retour_eur")
        vente = regler_vente(especes(eur=900.0, usd=0.0), 1.0, 108.0, 0.9, hypotheses)
        self.assertEqual((vente["USD"], vente["usd_vendus"]), (0.0, 108.0))
        self.assertAlmostEqual(vente["EUR"], 900.0 + 108 * 0.9 - 1.8)

    def test_retour_eur_ne_convertit_que_le_produit_de_la_vente(self):
        hypotheses = creer_hypotheses(scenario_change="retour_eur")
        vente = regler_vente(especes(eur=0.0, usd=50.0), 1.0, 100.0, 1.0, hypotheses)
        self.assertEqual((vente["EUR"], vente["USD"]), (100.0, 50.0))   # les 50 USD d'avant restent

    def test_aller_retour_au_stop_recoupe_avec_la_variation_d_equity(self):
        # Entrée 100, stop 96, 1 action, 1 USD = 1 EUR : prix −4 ; commissions 1 + 0,96 ;
        # conversions 0,03 % de 101 puis de 95,04.
        depart = especes()
        achat = regler_achat(depart, 1.0, 100.0, 1.0, self.FIXE_AUTO)
        vente = regler_vente(achat, 1.0, 96.0, 1.0, self.FIXE_AUTO)
        couts = achat["couts_eur"] + vente["couts_eur"]
        self.assertAlmostEqual(couts, 1 + 0.96 + 0.0303 + 0.028512)
        self.assertAlmostEqual(depart["EUR"] - vente["EUR"], 4.0 + couts)   # chaque coût compté une fois
        self.assertEqual(vente["USD"], 0.0)

    def test_glissement_sur_les_ordres_au_marche_seulement(self):
        hypotheses = creer_hypotheses(glissement_par_action=0.02)
        self.assertAlmostEqual(regler_achat(especes(), 10.0, 100.0, 1.0, hypotheses)["glissement_usd"], 0.2)
        self.assertAlmostEqual(regler_vente(especes(), 10.0, 96.0, 1.0, hypotheses)["glissement_usd"], 0.2)
        limite = regler_vente(especes(), 10.0, 108.0, 1.0, hypotheses, au_marche=False)
        self.assertEqual(limite["glissement_usd"], 0.0)   # l'objectif est un ordre à cours limité

    def test_frais_superieurs_au_produit_jamais_de_solde_usd_negatif(self):
        hypotheses = creer_hypotheses("synthetique")   # minimum 0,50 USD, sans plafond
        vente = regler_vente(especes(eur=10.0, usd=0.0), 0.001, 96.0, 1.0, hypotheses)
        self.assertEqual(vente["USD"], 0.0)
        self.assertAlmostEqual(vente["usd_achetes"], 0.5 - 0.096)
        self.assertAlmostEqual(vente["EUR"], 10.0 - (0.5 - 0.096))


class TestTaille(unittest.TestCase):
    FIXE_AUTO = creer_hypotheses("ibkr_fixe", "ibkr_auto", "retour_eur")

    def taille(self, hypotheses=AUCUN, pas=PAS_ENTIER, equity=1000.0, liquidites=None, usd=0.0, **options):
        return calculer_quantite(equity, especes(equity if liquidites is None else liquidites, usd),
                                 100.0, STOP, 1.0, hypotheses, pas, **options)

    def test_exemple_actions_entieres_et_fractions(self):
        entiere, fraction = self.taille(), self.taille(pas=PAS_FRACTION)
        self.assertEqual((entiere["quantite"], entiere["risque_prevu_eur"]), (1.0, 4.0))
        self.assertEqual(entiere["budget_eur"], 5.0)
        # 1,25 action risque exactement 5 EUR : l'égalité avec le budget est acceptée.
        self.assertEqual((fraction["quantite"], fraction["risque_prevu_eur"]), (1.25, 5.0))
        self.assertEqual(fraction["contrainte"], "BUDGET_RISQUE")

    def test_commission_minimale_actions_entieres_refus(self):
        taille = self.taille(self.FIXE_AUTO)
        self.assertEqual(taille["quantite"], 0.0)
        # Prix 4 ; commissions 1 + 0,96 ; conversions 0,0303 + 0,028512.
        self.assertAlmostEqual(taille["risque_minimal_eur"], 4 + 2.018812)
        self.assertIn("BUDGET_RISQUE", taille["contrainte"])

    def test_commission_resolue_avec_la_vraie_fonction_de_frais(self):
        taille = self.taille(self.FIXE_AUTO, PAS_FRACTION)
        # Sous 1 action, le plafond de 1 % s'applique : risque prévu = 6,018812 × q <= 5.
        self.assertEqual(taille["quantite"], 0.8307)
        self.assertLessEqual(taille["risque_prevu_eur"], 5.0)
        self.assertGreater(6.018812 * 0.8308, 5.0)   # un pas de plus dépasserait le budget
        self.assertAlmostEqual(taille["couts_change_stop_eur"], 0.058812 * 0.8307)

    def test_cout_de_change_estime_selon_le_scenario(self):
        # Conversion manuelle (minimum 2 USD), fractions. Le coût estimé dépend du scénario.
        retour = self.taille(creer_hypotheses(conversion="ibkr_manuelle", scenario_change="retour_eur"), PAS_FRACTION)
        conserves = self.taille(creer_hypotheses(conversion="ibkr_manuelle"), PAS_FRACTION)
        deja_en_usd = self.taille(creer_hypotheses(conversion="ibkr_manuelle"), PAS_FRACTION,
                                  liquidites=0.0, usd=1000.0)
        self.assertAlmostEqual(retour["couts_change_stop_eur"], 4.0)      # deux conversions
        self.assertAlmostEqual(conserves["couts_change_stop_eur"], 2.0)   # une seule, à l'achat
        self.assertEqual(deja_en_usd["couts_change_stop_eur"], 0.0)       # aucune : les USD sont déjà là
        self.assertEqual((retour["quantite"], conserves["quantite"], deja_en_usd["quantite"]), (0.25, 0.75, 1.25))
        for taille in (retour, conserves, deja_en_usd):
            self.assertLessEqual(taille["risque_prevu_eur"], 5.0 + 1e-9)

    def test_liquidites_insuffisantes(self):
        taille = self.taille(pas=PAS_FRACTION, liquidites=50.0)
        self.assertEqual(taille["quantite"], 0.5)
        self.assertEqual(taille["contrainte"], "LIQUIDITES")
        self.assertEqual(self.taille(liquidites=50.0)["quantite"], 0.0)

    def test_liquidites_en_eur_et_en_usd_s_additionnent_sans_emprunt(self):
        # 20 EUR + 30 USD, 1 USD = 1 EUR : 0,5 action à 100 USD, pas davantage.
        taille = self.taille(pas=PAS_FRACTION, liquidites=20.0, usd=30.0)
        self.assertEqual((taille["quantite"], taille["contrainte"]), (0.5, "LIQUIDITES"))
        self.assertAlmostEqual(taille["conversion_entree_usd"], 20.0)
        self.assertAlmostEqual(taille["eur_apres_achat"], 0.0)

    def test_exposition_plafonnee_a_l_equity(self):
        taille = self.taille(pas=PAS_FRACTION, exposition=950.0)
        self.assertEqual(taille["quantite"], 0.5)
        self.assertEqual(taille["contrainte"], "EXPOSITION")

    def test_risque_cumule_plafonne_a_un_pour_cent(self):
        taille = self.taille(pas=PAS_FRACTION, risque_reserve=7.0)   # il reste 3 EUR sur 10
        self.assertEqual(taille["quantite"], 0.75)
        self.assertEqual(taille["contrainte"], "RISQUE_CUMULE")
        self.assertEqual(self.taille(pas=PAS_FRACTION, risque_reserve=10.0)["quantite"], 0.0)

    def test_budget_suit_l_equity_sans_martingale(self):
        self.assertEqual(self.taille(pas=PAS_FRACTION, equity=2000.0)["quantite"], 2.5)
        self.assertEqual(self.taille(pas=PAS_FRACTION, equity=900.0)["quantite"], 1.125)

    def test_entree_sous_le_stop_refusee(self):
        with self.assertRaises(ValueError):
            calculer_quantite(1000, especes(), 96.0, 96.0, 1.0, AUCUN)


class TestSorties(unittest.TestCase):
    def setUp(self):
        self.marche = marche_fictif()
        self.entree = creneaux_de(self.marche, 1)[0]   # première bougie de la deuxième séance

    def bougie(self, rang_seance, numero=0):
        return self.marche["horaires"][creneaux_de(self.marche, rang_seance)[numero]["debut"]]

    def sortie(self):
        return simuler_sortie(self.marche, self.entree["debut"], STOP, CIBLE)

    def test_stop_touche_pendant_une_bougie(self):
        self.bougie(2, 3).update(low=95.5)
        issue = self.sortie()
        self.assertEqual((issue["statut"], issue["motif"], issue["sortie_prix"]), ("CLOTUREE", "STOP", STOP))
        self.assertEqual(issue["sortie_instant"], creneaux_de(self.marche, 2)[3]["fin"])
        self.assertEqual(issue["seance_detention"], 2)
        self.assertIs(issue["sortie_au_marche"], True)
        self.assertIs(issue["ambigu_intrabar"], False)

    def test_objectif_touche_ordre_a_cours_limite(self):
        self.bougie(3, 1).update(high=109.0)
        issue = self.sortie()
        self.assertEqual((issue["motif"], issue["sortie_prix"], issue["seance_detention"]), ("CIBLE", CIBLE, 3))
        self.assertIs(issue["sortie_au_marche"], False)

    def test_egalites_comptent(self):
        self.bougie(2).update(low=STOP)
        self.assertEqual(self.sortie()["motif"], "STOP")
        self.bougie(2).update(low=99.0, high=CIBLE)
        self.assertEqual(self.sortie()["motif"], "CIBLE")

    def test_gap_sous_le_stop_sortie_a_l_open(self):
        self.bougie(2).update(ouverture=90.0, high=91.0, low=89.0, cloture=90.0)
        issue = self.sortie()
        self.assertEqual((issue["motif"], issue["sortie_prix"]), ("STOP_GAP", 90.0))
        self.assertEqual(issue["sortie_instant"], creneaux_de(self.marche, 2)[0]["debut"])

    def test_open_egal_au_stop_est_un_gap(self):
        self.bougie(2).update(ouverture=STOP, low=95.0)
        self.assertEqual((self.sortie()["motif"], self.sortie()["sortie_prix"]), ("STOP_GAP", STOP))

    def test_gap_au_dessus_de_l_objectif_sans_amelioration_de_prix(self):
        self.bougie(2).update(ouverture=110.0, high=111.0, low=109.0, cloture=110.0)
        issue = self.sortie()
        self.assertEqual((issue["motif"], issue["sortie_prix"]), ("CIBLE_GAP", CIBLE))

    def test_stop_et_objectif_dans_la_meme_bougie(self):
        self.bougie(2, 2).update(low=95.0, high=109.0)
        issue = self.sortie()
        self.assertEqual((issue["motif"], issue["sortie_prix"]), ("STOP", STOP))
        self.assertIs(issue["ambigu_intrabar"], True)

    def test_stop_actif_des_la_bougie_d_entree(self):
        self.bougie(1, 0).update(low=95.0)
        issue = self.sortie()
        self.assertEqual((issue["motif"], issue["seance_detention"]), ("STOP", 1))

    def test_d10_liquidation_au_close_daily(self):
        issue = self.sortie()
        d10 = self.marche["sessions"][10]
        self.assertEqual((issue["motif"], issue["sortie_prix"]), ("DUREE_MAX_D10", 100.5))
        self.assertEqual(issue["sortie_instant"], self.marche["fins"][d10])
        self.assertEqual(issue["seance_detention"], 10)

    def test_evenement_de_prix_avant_la_liquidation_d10(self):
        self.bougie(10, 6).update(low=95.0)
        self.assertEqual(self.sortie()["motif"], "STOP")

    def test_d10_un_jour_de_cloture_anticipee(self):
        # D1 = 13/11/2026 ; D10 = 27/11/2026, séance qui ferme à 13:00 à New York.
        self.marche = marche_fictif(premier_jour=date(2026, 11, 12))
        self.entree = creneaux_de(self.marche, 1)[0]
        issue = self.sortie()
        self.assertEqual(self.marche["sessions"][10], date(2026, 11, 27))
        self.assertEqual(issue["motif"], "DUREE_MAX_D10")
        self.assertEqual(issue["sortie_instant"].astimezone(self.entree["debut"].tzinfo).hour, 18)   # 13:00 New York

    def test_bougie_manquante_suivie_de_donnees_non_evaluable(self):
        manquante = creneaux_de(self.marche, 3)[2]
        del self.marche["horaires"][manquante["debut"]]
        issue = self.sortie()
        self.assertEqual((issue["statut"], issue["motif"]), ("NON_EVALUABLE", "BOUGIE_HORAIRE_MANQUANTE"))
        self.assertEqual(issue["non_evaluable_depuis"], manquante["debut"])
        self.assertIsNone(issue["sortie_prix"])

    def test_bougie_incomplete_suivie_de_donnees_non_evaluable(self):
        self.bougie(3, 2).update(low=None)
        self.assertEqual(self.sortie()["motif"], "BOUGIE_HORAIRE_MANQUANTE")

    def test_fin_d_historique_position_ouverte(self):
        self.marche = marche_fictif(seances=4)
        issue = self.sortie()
        self.assertEqual((issue["statut"], issue["motif"]), ("OUVERTE", "POSITION_OUVERTE_FIN_DONNEES"))
        self.assertEqual((issue["seance_detention"], issue["dernier_prix"]), (3, 100.0))
        self.assertIsNone(issue["sortie_prix"])

    def test_bougie_d_entree_encore_en_cours(self):
        self.marche = marche_fictif(seances=2)
        for creneau in creneaux_de(self.marche, 1):
            self.marche["horaires"][creneau["debut"]].update(high=None, low=None, cloture=None)
        issue = self.sortie()
        self.assertEqual((issue["statut"], issue["seance_detention"]), ("OUVERTE", 1))

    def test_close_daily_d10_absent(self):
        d10 = self.marche["sessions"][10]
        del self.marche["daily"][d10]
        self.assertEqual(self.sortie()["motif"], "CLOTURE_D10_MANQUANTE")   # la séance suivante est connue
        del self.marche["daily"][self.marche["sessions"][11]]
        self.assertEqual(self.sortie()["statut"], "OUVERTE")                # rien après : on attend

    def test_le_futur_ne_reecrit_pas_une_sortie_passee(self):
        self.bougie(2, 3).update(low=95.5)
        attendu = self.sortie()
        for rang in range(3, 12):
            for numero in range(7):
                self.bougie(rang, numero).update(ouverture=50.0, high=200.0, low=1.0, cloture=150.0)
        self.assertEqual(self.sortie(), attendu)

    def test_dernier_prix_connu_prefere_l_ouverture_la_plus_recente(self):
        premiere, seconde = creneaux_de(self.marche, 1)[:2]
        self.marche["horaires"][seconde["debut"]]["ouverture"] = 100.7
        self.assertEqual(dernier_prix_connu(self.marche, premiere["debut"]), 100.0)
        self.assertEqual(dernier_prix_connu(self.marche, seconde["debut"]), 100.7)


class TestPortefeuille(unittest.TestCase):
    def setUp(self):
        self.marche = marche_fictif()

    def simuler(self, marches=None, taux=un_pour_un, hypotheses=None, pas=PAS_FRACTION, **options):
        return simuler_portefeuille(marches or [self.marche], taux, hypotheses=hypotheses,
                                    pas_quantite=pas, **options)

    def test_position_complete_objectif_atteint(self):
        ajouter_entree(self.marche, 1)
        creneau = creneaux_de(self.marche, 3)[1]
        self.marche["horaires"][creneau["debut"]]["high"] = 109.0
        resultat = self.simuler()
        position = resultat["positions"][0]
        self.assertEqual((position["statut"], position["motif"]), ("CLOTUREE", "CIBLE"))
        self.assertEqual((position["stop"], position["cible"], position["quantite"]), (STOP, CIBLE, 1.25))
        self.assertEqual((position["distance"], position["cible_brute"]), (4.0, 108.0))
        self.assertEqual((position["atr"], position["atr_seance"]), (4.0, self.marche["sessions"][0]))
        self.assertEqual((position["seance_d1"], position["seance_d10"]),
                         (self.marche["sessions"][1], self.marche["sessions"][10]))
        self.assertAlmostEqual(position["apres_couts_eur"], 10.0)
        self.assertAlmostEqual(position["multiple_r"], 2.0)
        self.assertIs(position["cible_a_l_egalite"], False)   # le plus haut (109) dépasse l'objectif (108)
        self.assertAlmostEqual(resultat["equity_eur"], 1010.0)
        self.assertAlmostEqual(position["equity_apres_eur"], 1010.0)
        self.assertEqual(set(CHAMPS_POSITION) - set(position), set())
        self.assertEqual(set(position) - set(CHAMPS_POSITION), set())   # aucun champ de travail ne reste

    def test_objectif_touche_sans_depassement_signale(self):
        ajouter_entree(self.marche, 1)
        creneau = creneaux_de(self.marche, 3)[1]
        self.marche["horaires"][creneau["debut"]]["high"] = CIBLE
        resultat = self.simuler()
        self.assertIs(resultat["positions"][0]["cible_a_l_egalite"], True)
        self.assertEqual(resultat["decompte"]["cibles_a_l_egalite"], 1)

    def test_une_seule_position_par_titre_puis_budget_recalcule(self):
        ajouter_entree(self.marche, 1)
        ajouter_entree(self.marche, 2)            # pendant que la première est ouverte
        stop = creneaux_de(self.marche, 3)[0]
        self.marche["horaires"][stop["debut"]]["low"] = 95.0
        ajouter_entree(self.marche, 4)            # après la sortie au stop
        positions = self.simuler()["positions"]
        self.assertEqual([position["motif"] for position in positions[:2]], ["STOP", "POSITION_DEJA_OUVERTE"])
        self.assertIsNone(positions[1]["quantite"])
        self.assertAlmostEqual(positions[0]["apres_couts_eur"], -5.0)
        # Après la perte, l'equity vaut 995 EUR : le budget baisse à 4,975 EUR, sans rattrapage.
        self.assertAlmostEqual(positions[2]["equity_eur"], 995.0)
        self.assertAlmostEqual(positions[2]["budget_eur"], 4.975)
        self.assertLess(positions[2]["quantite"], positions[0]["quantite"])

    def test_entree_au_meme_instant_que_la_sortie_precedente(self):
        ajouter_entree(self.marche, 1)
        gap = creneaux_de(self.marche, 2)[0]
        self.marche["horaires"][gap["debut"]].update(ouverture=90.0, high=91.0, low=89.0, cloture=90.0)
        ajouter_entree(self.marche, 2, prix=90.0, plus_bas=87.0)   # même ouverture que le gap
        positions = self.simuler()["positions"]
        self.assertEqual(positions[0]["motif"], "STOP_GAP")
        self.assertAlmostEqual(positions[0]["apres_couts_eur"], -12.5)     # 1,25 action × 10 USD : le stop n'a rien plafonné
        self.assertEqual(positions[1]["statut"] in ("CLOTUREE", "OUVERTE"), True)
        self.assertAlmostEqual(positions[1]["equity_eur"], 987.5)

    def test_taille_insuffisante_en_actions_entieres_avec_frais(self):
        ajouter_entree(self.marche, 1)
        resultat = self.simuler(hypotheses=creer_hypotheses("ibkr_fixe", "ibkr_auto"), pas=PAS_ENTIER)
        position = resultat["positions"][0]
        self.assertEqual((position["statut"], position["motif"]),
                         ("REFUSEE", "PAS_DE_POSITION_TAILLE_INSUFFISANTE"))
        self.assertIsNone(position["quantite"])
        self.assertGreater(position["risque_minimal_eur"], position["budget_eur"])
        self.assertIsNone(position["sortie_prix"])
        # Le refus reste dans le journal et dans les comptes ; aucune conversion n'a eu lieu.
        self.assertEqual(resultat["decompte"]["par_motif"], {"PAS_DE_POSITION_TAILLE_INSUFFISANTE": 1})
        self.assertEqual(resultat["conversions"], [])
        self.assertEqual((resultat["especes_eur"], resultat["especes_usd"]), (1000.0, 0.0))

    def test_entree_sous_le_stop_refusee_sans_deplacer_le_stop(self):
        ajouter_entree(self.marche, 1, prix=96.0)
        position = self.simuler()["positions"][0]
        self.assertEqual((position["statut"], position["motif"]), ("REFUSEE", "ENTREE_SOUS_STOP"))
        self.assertEqual(position["stop"], STOP)
        self.assertIsNone(position["cible"])

    def test_atr_inconnu_non_evaluable(self):
        ajouter_entree(self.marche, 1)
        self.marche["atr"][self.marche["sessions"][0]] = None
        position = self.simuler()["positions"][0]
        self.assertEqual((position["statut"], position["motif"]), ("NON_EVALUABLE", "ATR_INDISPONIBLE"))

    def test_atr_de_la_derniere_seance_terminee_jamais_de_la_seance_en_cours(self):
        ajouter_entree(self.marche, 3, numero_bougie=2)
        for rang, valeur in enumerate((1.0, 2.0, 4.0, 400.0)):
            self.marche["atr"][self.marche["sessions"][rang]] = valeur
        position = self.simuler()["positions"][0]
        self.assertEqual((position["atr"], position["atr_seance"]), (4.0, self.marche["sessions"][2]))

    def test_taux_de_change_indisponible(self):
        ajouter_entree(self.marche, 1)
        position = self.simuler(taux=lambda _instant: None)["positions"][0]
        self.assertEqual((position["statut"], position["motif"]),
                         ("NON_EVALUABLE", "TAUX_DE_CHANGE_INDISPONIBLE"))

    def test_taux_d_entree_indisponible_a_la_sortie_non_evaluable(self):
        entree = ajouter_entree(self.marche, 1)
        cible = creneaux_de(self.marche, 3)[1]
        self.marche["horaires"][cible["debut"]]["high"] = 109.0
        position = self.simuler(taux=lambda instant: un_pour_un(instant) if instant <= entree["debut"] else None
                                )["positions"][0]
        self.assertEqual((position["statut"], position["motif"]),
                         ("NON_EVALUABLE", "TAUX_DE_CHANGE_INDISPONIBLE"))
        self.assertIsNone(position["apres_couts_eur"])   # aucun résultat inventé

    def test_effet_de_change_separe_du_resultat_de_prix(self):
        entree = ajouter_entree(self.marche, 1)
        cible = creneaux_de(self.marche, 3)[1]
        self.marche["horaires"][cible["debut"]]["high"] = 109.0
        position = self.simuler(taux=taux_selon(0.90, 0.92, entree["debut"]))["positions"][0]
        quantite = position["quantite"]
        self.assertAlmostEqual(position["brut_usd"], quantite * 8.0)
        self.assertAlmostEqual(position["brut_eur"], quantite * 8.0 * 0.90)
        self.assertAlmostEqual(position["effet_change_eur"], quantite * 108.0 * 0.02)
        self.assertAlmostEqual(position["apres_couts_eur"], position["brut_eur"] + position["effet_change_eur"])
        self.assertEqual((position["taux_entree"], position["taux_sortie"]), (0.90, 0.92))

    def test_comptabilite_recoupee_avec_les_flux_et_les_couts(self):
        ajouter_entree(self.marche, 1)
        cible = creneaux_de(self.marche, 3)[1]
        self.marche["horaires"][cible["debut"]]["high"] = 109.0
        ajouter_entree(self.marche, 5)
        stop = creneaux_de(self.marche, 6)[4]
        self.marche["horaires"][stop["debut"]]["low"] = 95.0
        for scenario in SCENARIOS_CHANGE:
            with self.subTest(scenario=scenario):
                hypotheses = creer_hypotheses("synthetique", "synthetique", scenario, 0.02)
                resultat = self.simuler(hypotheses=hypotheses)
                positions = resultat["positions"]
                self.assertEqual([position["motif"] for position in positions], ["CIBLE", "STOP"])
                for position in positions:
                    self.assertGreater(position["couts_eur"], 0)
                    self.assertAlmostEqual(position["couts_eur"], position["commissions_eur"]
                                           + position["glissement_eur"] + position["couts_change_eur"])
                    self.assertAlmostEqual(position["apres_couts_eur"], position["brut_eur"]
                                           + position["effet_change_eur"] - position["couts_eur"])
                    # Le risque prévu, coûts compris, ne dépasse jamais le budget.
                    self.assertLessEqual(position["risque_prevu_eur"], position["budget_eur"] + 1e-9)
                # Chaque coût est compté une fois : l'equity finale se retrouve à partir des résultats.
                self.assertAlmostEqual(resultat["equity_eur"], 1000.0 + sum(
                    position["apres_couts_eur"] for position in positions))
                # Les frais de change des positions sont exactement ceux du journal des conversions.
                self.assertAlmostEqual(sum(position["couts_change_eur"] for position in positions),
                                       sum(conversion["cout_eur"] for conversion in resultat["conversions"]))
                # Une perte au stop, coûts compris, vaut le risque prévu au dimensionnement (aucun gap ici).
                self.assertAlmostEqual(-positions[1]["apres_couts_eur"], positions[1]["risque_prevu_eur"], places=6)
                self.assertAlmostEqual(positions[1]["couts_eur"], positions[1]["couts_stop_eur"], places=6)

    def test_position_non_evaluable_bloque_les_entrees_suivantes(self):
        ajouter_entree(self.marche, 1)
        del self.marche["horaires"][creneaux_de(self.marche, 2)[3]["debut"]]
        ajouter_entree(self.marche, 4)
        resultat = self.simuler()
        self.assertEqual([position["motif"] for position in resultat["positions"]],
                         ["BOUGIE_HORAIRE_MANQUANTE", "PORTEFEUILLE_NON_EVALUABLE"])
        self.assertIsNone(resultat["equity_eur"])   # le trade reste dans le journal, sans résultat inventé
        self.assertEqual(len(resultat["positions"]), 2)

    def test_position_ouverte_en_fin_d_historique(self):
        marche = marche_fictif(seances=4)
        ajouter_entree(marche, 1)
        marche["horaires"][creneaux_de(marche, 3)[6]["debut"]]["cloture"] = 102.0
        resultat = self.simuler([marche])
        position = resultat["positions"][0]
        self.assertEqual((position["statut"], position["motif"]), ("OUVERTE", "POSITION_OUVERTE_FIN_DONNEES"))
        self.assertIsNone(position["apres_couts_eur"])
        # Liquidités diminuées de l'achat ; equity valorisée au dernier prix connu (102).
        self.assertAlmostEqual(resultat["especes_eur"], 1000.0 - 125.0)
        self.assertEqual(resultat["especes_usd"], 0.0)
        self.assertAlmostEqual(resultat["equity_eur"], 875.0 + 1.25 * 102.0)
        self.assertEqual(resultat["decompte"]["par_statut"], {"OUVERTE": 1})

    def test_risque_cumule_entre_plusieurs_titres(self):
        marches = [marche_fictif(symbole) for symbole in ("AAA", "BBB", "CCC")]
        for marche in marches:
            ajouter_entree(marche, 1)
        positions = self.simuler(marches)["positions"]
        self.assertEqual([position["symbole"] for position in positions], ["AAA", "BBB", "CCC"])
        self.assertEqual([position["quantite"] for position in positions[:2]], [1.25, 1.25])
        self.assertAlmostEqual(positions[1]["risque_reserve_eur"], 5.0)
        # Deux positions réservent déjà 1 % de l'equity : la troisième est refusée.
        self.assertEqual(positions[2]["motif"], "PAS_DE_POSITION_TAILLE_INSUFFISANTE")
        self.assertIn("RISQUE_CUMULE", positions[2]["contrainte"])
        self.assertAlmostEqual(positions[2]["equity_eur"], 1000.0)   # liquidités + positions au dernier prix

    def test_tous_les_cas_restent_comptes(self):
        ajouter_entree(self.marche, 1, prix=96.0)                      # refusée : ouverture au stop
        ajouter_entree(self.marche, 2)
        del self.marche["horaires"][creneaux_de(self.marche, 3)[3]["debut"]]   # bougie manquante
        ajouter_entree(self.marche, 5)                                 # bloquée par la précédente
        decompte = self.simuler()["decompte"]
        self.assertEqual(decompte["entrees"], 3)
        self.assertEqual(decompte["par_statut"], {"REFUSEE": 1, "NON_EVALUABLE": 2})
        self.assertEqual(decompte["par_motif"], {"ENTREE_SOUS_STOP": 1, "BOUGIE_HORAIRE_MANQUANTE": 1,
                                                 "PORTEFEUILLE_NON_EVALUABLE": 1})


class TestScenariosDeChange(unittest.TestCase):
    """Valorisation en EUR d'un côté, conversions réellement simulées de l'autre."""

    MANUELLE = "ibkr_manuelle"   # 0,002 %, minimum 2 USD par conversion : un coût visible

    def marche_deux_positions(self):
        """Première position : objectif à 108. Seconde : stop à 96. Entrées à 100, prix fictifs."""
        marche = marche_fictif()
        ajouter_entree(marche, 1)
        marche["horaires"][creneaux_de(marche, 3)[1]["debut"]]["high"] = 109.0
        ajouter_entree(marche, 5)
        marche["horaires"][creneaux_de(marche, 6)[4]["debut"]]["low"] = 95.0
        return marche

    def simuler(self, scenario, taux=un_pour_un, conversion=MANUELLE, **options):
        hypotheses = creer_hypotheses(conversion=conversion, scenario_change=scenario)
        return simuler_portefeuille([self.marche_deux_positions()], taux, hypotheses=hypotheses,
                                    pas_quantite=PAS_FRACTION, **options)

    def test_usd_conserves_une_seule_conversion_puis_reutilisation(self):
        resultat = self.simuler("usd_conserves")
        premiere, seconde = resultat["positions"]
        # Budget 5 EUR = 4 × q + 2 EUR de conversion à l'achat : q = 0,75. Rien à la vente.
        self.assertEqual((premiere["quantite"], premiere["conversion_entree_usd"]), (0.75, 75.0))
        self.assertAlmostEqual(premiere["couts_change_eur"], 2.0)
        self.assertEqual(premiere["conversion_sortie_usd"], 0.0)
        self.assertAlmostEqual(premiere["apres_couts_eur"], 0.75 * 8 - 2.0)
        # La vente laisse 81 USD : ils paient la seconde position, sans nouvelle conversion.
        self.assertAlmostEqual(seconde["especes_usd_avant"], 81.0)
        self.assertEqual((seconde["conversion_entree_usd"], seconde["couts_change_eur"]), (0.0, 0.0))
        self.assertEqual(len(resultat["conversions"]), 1)
        conversion = resultat["conversions"][0]
        self.assertEqual((conversion["sens"], conversion["operation"], conversion["montant_usd"]),
                         ("EUR_VERS_USD", "ACHAT", 75.0))
        self.assertAlmostEqual(conversion["montant_eur"], 77.0)            # 75 EUR + 2 EUR de coût
        self.assertAlmostEqual(conversion["taux_execution"], 77.0 / 75.0)  # pire que la référence (1,0)
        self.assertEqual(conversion["taux_reference"], 1.0)
        # Budget 5,02 EUR. Avec 81 USD, on achète 0,81 action (risque 3,24 EUR). Aller au-delà
        # demanderait une conversion à 2 USD minimum : 4 × q + 2 dépasserait le budget.
        self.assertAlmostEqual(seconde["budget_eur"], 0.005 * 1004.0)
        self.assertEqual((seconde["quantite"], seconde["contrainte"]), (0.81, "BUDGET_RISQUE"))
        # Soldes finaux : les USD restent des USD.
        self.assertAlmostEqual(resultat["especes_eur"], 1000.0 - 77.0)
        self.assertAlmostEqual(resultat["especes_usd"], 0.81 * 96)

    def test_retour_eur_deux_conversions_par_position(self):
        resultat = self.simuler("retour_eur")
        premiere, seconde = resultat["positions"]
        # Budget 5 EUR = 4 × q + 2 EUR à l'achat + 2 EUR à la vente : q = 0,25.
        self.assertEqual(premiere["quantite"], 0.25)
        self.assertAlmostEqual(premiere["couts_change_eur"], 4.0)
        self.assertAlmostEqual(premiere["apres_couts_eur"], 0.25 * 8 - 4.0)
        self.assertEqual(seconde["especes_usd_avant"], 0.0)
        self.assertEqual([conversion["sens"] for conversion in resultat["conversions"]],
                         ["EUR_VERS_USD", "USD_VERS_EUR", "EUR_VERS_USD", "USD_VERS_EUR"])
        self.assertEqual(resultat["especes_usd"], 0.0)

    def test_usd_deja_detenus_aucune_conversion(self):
        resultat = self.simuler("usd_conserves", capital=0.0, usd_depart=1000.0)
        premiere, seconde = resultat["positions"]
        self.assertEqual((premiere["quantite"], premiere["conversion_entree_usd"]), (1.25, 0.0))
        self.assertEqual(resultat["conversions"], [])
        self.assertEqual(premiere["couts_eur"] + seconde["couts_eur"], 0.0)
        self.assertEqual(resultat["especes_eur"], 0.0)

    def test_aucun_double_comptage_des_frais_de_change(self):
        for scenario in SCENARIOS_CHANGE:
            with self.subTest(scenario=scenario):
                resultat = self.simuler(scenario)
                positions = resultat["positions"]
                frais_positions = sum(position["couts_change_eur"] for position in positions)
                frais_journal = sum(conversion["cout_eur"] for conversion in resultat["conversions"])
                self.assertAlmostEqual(frais_positions, frais_journal)
                self.assertAlmostEqual(frais_journal, 2.0 * len(resultat["conversions"]))
                # Identité comptable : départ + résultats + effet de change sur les USD détenus.
                self.assertAlmostEqual(resultat["equity_eur"], resultat["equity_depart_eur"]
                                       + sum(position["apres_couts_eur"] for position in positions)
                                       + resultat["effet_change_liquidites_eur"])

    def test_usd_detenus_revalorises_sans_conversion_ni_cout(self):
        # 1 USD passe de 0,90 à 0,80 EUR après la première vente : les USD gardés perdent de la valeur en EUR.
        marche = self.marche_deux_positions()
        vente = creneaux_de(marche, 3)[1]["fin"]
        resultat = self.simuler("usd_conserves", taux=taux_selon(0.90, 0.80, vente), conversion="sans_cout")
        positions = resultat["positions"]
        self.assertEqual(sum(position["couts_eur"] for position in positions), 0.0)
        # 1,3888 action vendue à 108 = 149,99 USD détenus ; × (0,80 − 0,90) = −15,00 EUR, sans conversion.
        usd_detenus = positions[0]["quantite"] * 108.0
        self.assertEqual(positions[0]["quantite"], 1.3888)
        self.assertAlmostEqual(positions[1]["especes_usd_avant"], usd_detenus)
        self.assertAlmostEqual(resultat["effet_change_liquidites_eur"], usd_detenus * (0.80 - 0.90))
        self.assertAlmostEqual(resultat["equity_eur"], resultat["equity_depart_eur"]
                               + sum(position["apres_couts_eur"] for position in positions)
                               + resultat["effet_change_liquidites_eur"])
        # La valorisation utilise le taux de référence ; aucune conversion n'a lieu à la vente.
        # (La seconde position coûte plus que les USD détenus : seul son manque est converti.)
        self.assertEqual({conversion["operation"] for conversion in resultat["conversions"]}, {"ACHAT"})
        self.assertLess(resultat["conversions"][1]["montant_usd"], positions[1]["montant_usd"])

    def test_retour_eur_sans_usd_detenus_aucun_effet_sur_les_liquidites(self):
        marche = self.marche_deux_positions()
        bascule = marche["journal"][1]["instant"]
        resultat = self.simuler("retour_eur", taux=taux_selon(0.90, 0.80, bascule), conversion="sans_cout")
        self.assertEqual(resultat["effet_change_liquidites_eur"], 0.0)
        self.assertAlmostEqual(resultat["equity_eur"], 1000.0 + sum(
            position["apres_couts_eur"] for position in resultat["positions"]))

    def test_taux_d_execution_distinct_du_taux_de_reference(self):
        resultat = self.simuler("retour_eur", taux=cotation_fixe(0.90), conversion="ibkr_auto")
        achat, vente = resultat["conversions"][:2]
        self.assertEqual((achat["taux_reference"], vente["taux_reference"]), (0.90, 0.90))
        self.assertAlmostEqual(achat["taux_execution"], 0.90 * 1.0003)   # acheter des USD coûte plus cher
        self.assertAlmostEqual(vente["taux_execution"], 0.90 * 0.9997)   # en vendre rapporte moins
        # La valorisation, elle, reste au taux de référence.
        self.assertEqual(resultat["positions"][0]["taux_entree"], 0.90)


class TestReglementDesVentes(unittest.TestCase):
    """Compte au comptant : le produit d'une vente ne paie un achat qu'une fois réglé."""

    PRUDENT = creer_hypotheses(reglement="j1_prudent")
    DEFAVORABLE = creer_hypotheses(reglement="j2_defavorable")

    def marche_vente_puis_achat(self, rang_achat, bougie_achat, premier_jour=date(2025, 7, 7)):
        """Achat le 2e jour, objectif atteint le 4e jour à 11:30, puis un nouvel achat."""
        marche = marche_fictif(premier_jour=premier_jour)
        ajouter_entree(marche, 1)
        marche["horaires"][creneaux_de(marche, 3)[1]["debut"]]["high"] = 109.0
        ajouter_entree(marche, rang_achat, numero_bougie=bougie_achat)
        return marche

    def seconde(self, marche, hypotheses):
        resultat = simuler_portefeuille([marche], un_pour_un, hypotheses=hypotheses, pas_quantite=PAS_FRACTION)
        return resultat["positions"][1], resultat

    def test_vente_puis_achat_le_meme_jour_usd_pas_encore_regles(self):
        # Jeudi 10/07 : vente à 11:30 (135 USD), nouvel achat à 12:30. Les USD ne sont pas réglés.
        marche = self.marche_vente_puis_achat(3, 3)
        position, resultat = self.seconde(marche, self.PRUDENT)
        self.assertAlmostEqual(position["attente_usd_avant"], 135.0)
        self.assertEqual(position["disponible_usd_avant"], 0.0)
        self.assertAlmostEqual(position["especes_usd_avant"], 135.0)       # le solde comptable les contient
        # L'achat est donc payé par une conversion d'EUR, comme si aucun USD n'était détenu.
        self.assertAlmostEqual(position["conversion_entree_usd"], position["montant_usd"])
        self.assertEqual([conversion["operation"] for conversion in resultat["conversions"]], ["ACHAT", "ACHAT"])

    def test_meme_cas_sans_delai_les_usd_paient_l_achat(self):
        position, resultat = self.seconde(self.marche_vente_puis_achat(3, 3), creer_hypotheses())
        self.assertEqual((position["attente_usd_avant"], position["conversion_entree_usd"]), (0.0, 0.0))
        self.assertEqual(len(resultat["conversions"]), 1)

    def test_le_lendemain_a_l_ouverture_les_usd_sont_disponibles(self):
        # Vendredi 11/07 à 09:30 : jour de règlement de la vente du jeudi.
        position, _ = self.seconde(self.marche_vente_puis_achat(4, 0), self.PRUDENT)
        self.assertEqual(position["attente_usd_avant"], 0.0)
        self.assertAlmostEqual(position["disponible_usd_avant"], 135.0)
        self.assertEqual(position["conversion_entree_usd"], 0.0)

    def test_convention_defavorable_un_jour_de_plus(self):
        # Avec J+2, la vente du jeudi n'est disponible que le lundi : le vendredi, il faut convertir.
        vendredi, _ = self.seconde(self.marche_vente_puis_achat(4, 0), self.DEFAVORABLE)
        lundi, _ = self.seconde(self.marche_vente_puis_achat(5, 0), self.DEFAVORABLE)
        self.assertAlmostEqual(vendredi["attente_usd_avant"], 135.0)
        self.assertGreater(vendredi["conversion_entree_usd"], 0.0)
        self.assertEqual((lundi["attente_usd_avant"], lundi["conversion_entree_usd"]), (0.0, 0.0))

    def test_week_end_et_jour_ferie_repoussent_le_reglement(self):
        # Semaine du 30/06/2025 : jeudi 3 (séance écourtée), vendredi 4 fermé, puis le week-end.
        marche = marche_fictif(premier_jour=date(2025, 6, 30))
        calendrier = calendrier_de_reglement([marche])
        jeudi = creneaux_de(marche, 3)[1]["fin"]
        self.assertEqual(marche["sessions"][3:5], [date(2025, 7, 3), date(2025, 7, 7)])
        self.assertEqual(instant_de_reglement(calendrier, jeudi, 1), creneaux_de(marche, 4)[0]["debut"])   # lundi 7
        self.assertEqual(instant_de_reglement(calendrier, jeudi, 0), jeudi)
        # Une vente du vendredi se règle le lundi suivant, à l'ouverture.
        normal = marche_fictif()
        vendredi = creneaux_de(normal, 4)[2]["fin"]
        self.assertEqual(instant_de_reglement(calendrier_de_reglement([normal]), vendredi, 1),
                         creneaux_de(normal, 5)[0]["debut"])

    def test_jour_ferie_bancaire_bourse_ouverte_pas_de_reglement(self):
        # Lundi 12/10/2026, Columbus Day : la Bourse ouvre, les banques non. Par prudence, pas de règlement.
        self.assertEqual(jours_feries_bancaires(2026), {date(2026, 10, 12), date(2026, 11, 11)})
        self.assertEqual(jours_feries_bancaires(2029), {date(2029, 10, 8), date(2029, 11, 12)})   # 11/11 un dimanche
        marche = marche_fictif(premier_jour=date(2026, 10, 5))
        calendrier = calendrier_de_reglement([marche])
        self.assertEqual(marche["sessions"][4:7], [date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13)])
        vendredi = creneaux_de(marche, 4)[2]["fin"]
        self.assertEqual(instant_de_reglement(calendrier, vendredi, 1), creneaux_de(marche, 6)[0]["debut"])   # mardi 13
        # Un achat le lundi férié ne peut donc pas utiliser la vente du vendredi.
        marche = self.marche_vente_puis_achat(4, 0, premier_jour=date(2026, 10, 6))   # vente le vendredi 9
        position, _ = self.seconde(marche, self.PRUDENT)
        self.assertEqual(position["seance_d1"], date(2026, 10, 12))
        self.assertAlmostEqual(position["attente_usd_avant"], 135.0)
        # Le mardi 13, premier jour de règlement, les USD sont disponibles.
        mardi, _ = self.seconde(self.marche_vente_puis_achat(5, 0, premier_jour=date(2026, 10, 6)), self.PRUDENT)
        self.assertEqual((mardi["seance_d1"], mardi["attente_usd_avant"]), (date(2026, 10, 13), 0.0))

    def test_achat_avec_conversion_automatique_pendant_qu_une_vente_attend(self):
        # Scénario de référence : conversion automatique du seul montant nécessaire, frais compris.
        hypotheses, pas = configurer("IBKR_CASH_AUTO_FRACTIONS_FIXED")
        marche = self.marche_vente_puis_achat(3, 3)
        resultat = simuler_portefeuille([marche], un_pour_un, hypotheses=hypotheses, pas_quantite=pas)
        premiere, seconde = resultat["positions"]
        self.assertGreater(seconde["attente_usd_avant"], 0.0)
        # La conversion couvre l'achat, sa commission et le glissement de 2 points de base, rien de plus ;
        # les USD en attente ne bougent pas.
        commission = commission_usd(BAREMES_COMMISSIONS["ibkr_fixe"], seconde["quantite"], 100.0)
        glissement = seconde["montant_usd"] * 0.0002
        self.assertAlmostEqual(seconde["conversion_entree_usd"], seconde["montant_usd"] + commission + glissement)
        self.assertAlmostEqual(seconde["entree_prix_execute"], 100.0 * 1.0002)   # prix d'achat plus élevé
        self.assertAlmostEqual(resultat["conversions"][1]["cout_eur"], 0.0003 * seconde["conversion_entree_usd"])
        self.assertLessEqual(seconde["risque_prevu_eur"], seconde["budget_eur"] + 1e-9)
        self.assertGreaterEqual(resultat["disponible_eur"], 0.0)   # jamais de solde négatif

    def test_entree_non_financable_refusee_avec_un_motif_explicite(self):
        # Un stop très proche fait investir tout le compte ; la vente du matin n'est pas encore réglée.
        marche = marche_fictif()
        marche["atr"] = {session: 0.4 for session in marche["atr"]}
        ajouter_entree(marche, 1, plus_bas=99.9)                      # stop 99,80 : touché dès la première bougie
        ajouter_entree(marche, 1, numero_bougie=3, plus_bas=99.9)     # le même jour, à 12:30
        ajouter_entree(marche, 2, plus_bas=99.9)                      # le lendemain à l'ouverture
        resultat = simuler_portefeuille([marche], un_pour_un, hypotheses=self.PRUDENT, pas_quantite=PAS_FRACTION)
        premiere, meme_jour, lendemain = resultat["positions"]
        self.assertEqual((premiere["quantite"], premiere["motif"]), (10.0, "STOP"))
        self.assertEqual((meme_jour["statut"], meme_jour["motif"]), ("REFUSEE", "FONDS_DISPONIBLES_INSUFFISANTS"))
        self.assertEqual(meme_jour["contrainte"], "LIQUIDITES")
        self.assertAlmostEqual(meme_jour["attente_usd_avant"], 998.0)
        self.assertEqual((meme_jour["disponible_eur_avant"], meme_jour["disponible_usd_avant"]), (0.0, 0.0))
        self.assertIsNone(meme_jour["quantite"])
        self.assertIsNotNone(lendemain["quantite"])                   # une fois la vente réglée, l'achat passe
        self.assertEqual(resultat["decompte"]["par_motif"]["FONDS_DISPONIBLES_INSUFFISANTS"], 1)
        self.assertIn("Achat non finançable", " ".join(decrire_position(meme_jour)))

    def test_soldes_comptable_disponible_et_en_attente_en_fin_de_simulation(self):
        # Les données s'arrêtent le jour de la vente : le produit attend encore son règlement.
        marche = marche_fictif(seances=4)
        ajouter_entree(marche, 1)
        marche["horaires"][creneaux_de(marche, 3)[1]["debut"]]["high"] = 109.0
        resultat = simuler_portefeuille([marche], un_pour_un, hypotheses=self.PRUDENT, pas_quantite=PAS_FRACTION)
        self.assertAlmostEqual(resultat["especes_usd"], 135.0)        # solde comptable
        self.assertEqual(resultat["disponible_usd"], 0.0)             # pas encore utilisable
        self.assertEqual(len(resultat["en_attente"]), 1)
        attente = resultat["en_attente"][0]
        self.assertEqual((attente["devise"], attente["symbole"]), ("USD", "FICTIF"))
        self.assertEqual(attente["disponible_a"], creneaux_de(marche, 4)[0]["debut"])
        self.assertAlmostEqual(resultat["equity_eur"], 1010.0)        # la valorisation compte tout

    def test_delai_de_reglement_selon_l_epoque(self):
        # J+3 jusqu'au 04/09/2017, J+2 jusqu'au 27/05/2024, J+1 ensuite.
        for jour, attendu in ((date(2016, 4, 1), 3), (date(2017, 9, 4), 3), (date(2017, 9, 5), 2),
                              (date(2024, 5, 27), 2), (date(2024, 5, 28), 1), (date(2026, 8, 31), 1)):
            with self.subTest(jour=jour):
                self.assertEqual(delai_de_reglement(jour), attendu)
                self.assertEqual(delais_de("historique", jour)["actions"], attendu)
                self.assertEqual(delais_de("historique_plus_un", jour)["actions"], attendu + 1)
        self.assertEqual(delais_de("immediat", date(2016, 4, 1)), {"actions": 0, "change": 0})

    def test_vente_de_2016_disponible_trois_jours_de_reglement_plus_tard(self):
        # Semaine du 04/04/2016 (J+3) : vente le jeudi 7, disponible le mardi 12 ; le lundi 11, pas encore.
        historique = creer_hypotheses(reglement="historique")
        lundi, _ = self.seconde(self.marche_vente_puis_achat(5, 0, premier_jour=date(2016, 4, 4)), historique)
        mardi, _ = self.seconde(self.marche_vente_puis_achat(6, 0, premier_jour=date(2016, 4, 4)), historique)
        self.assertEqual((lundi["seance_d1"], mardi["seance_d1"]), (date(2016, 4, 11), date(2016, 4, 12)))
        self.assertAlmostEqual(lundi["attente_usd_avant"], 135.0)
        self.assertEqual(mardi["attente_usd_avant"], 0.0)
        # Scénario défavorable : un jour ouvré de plus, donc encore en attente le mardi.
        plus_un = creer_hypotheses(reglement="historique_plus_un")
        mardi_defavorable, _ = self.seconde(self.marche_vente_puis_achat(6, 0, premier_jour=date(2016, 4, 4)), plus_un)
        self.assertAlmostEqual(mardi_defavorable["attente_usd_avant"], 135.0)

    def test_retour_eur_les_eur_d_une_conversion_attendent_deux_jours(self):
        hypotheses = creer_hypotheses(scenario_change="retour_eur", reglement="j1_prudent")
        vendredi, _ = self.seconde(self.marche_vente_puis_achat(4, 0), hypotheses)
        lundi, _ = self.seconde(self.marche_vente_puis_achat(5, 0), hypotheses)
        self.assertAlmostEqual(vendredi["attente_eur_avant"], 135.0)
        self.assertEqual(lundi["attente_eur_avant"], 0.0)


class TestDivisionsD_actions(unittest.TestCase):
    """Cours continus pour les signaux, cours réels de l'époque pour chaque position."""

    def position(self, divisions, hypotheses=None, rang_cible=3):
        marche = marche_fictif()
        marche["divisions"] = divisions
        ajouter_entree(marche, 1)
        marche["horaires"][creneaux_de(marche, rang_cible)[1]["debut"]]["high"] = 109.0
        resultat = simuler_portefeuille([marche], un_pour_un, hypotheses=hypotheses, pas_quantite=PAS_FRACTION)
        return resultat["positions"][0], resultat, marche

    def test_facteur_de_division(self):
        divisions = ((date(2021, 7, 20), 4), (date(2024, 6, 10), 10))
        self.assertEqual(facteur_de_division(divisions, date(2021, 7, 19)), 40)
        self.assertEqual(facteur_de_division(divisions, date(2021, 7, 20)), 10)   # le jour d'effet est déjà divisé
        self.assertEqual(facteur_de_division(divisions, date(2024, 6, 7)), 10)
        self.assertEqual(facteur_de_division(divisions, date(2024, 6, 10)), 1)
        self.assertEqual(facteur_de_division((), date(2020, 1, 1)), 1)

    def test_position_en_cours_reels_de_l_epoque_sans_gain_ni_perte_artificiels(self):
        # Division de 10 pour 1 bien après la position : le cours continu de 100 valait 1 000 à l'époque.
        sans, _, _ = self.position(())
        avec, _, marche = self.position(((marche_fictif()["sessions"][11], 10),))
        self.assertEqual((avec["facteur_division"], sans["facteur_division"]), (10, 1))
        self.assertEqual((avec["entree_prix"], avec["plus_bas"], avec["atr"]), (1000.0, 970.0, 40.0))
        self.assertEqual((avec["stop"], avec["cible"], avec["distance"]), (960.0, 1080.0, 40.0))
        self.assertEqual((avec["sortie_prix"], avec["motif"]), (1080.0, "CIBLE"))
        # Dix fois moins d'actions, dix fois plus chères : même risque, même résultat.
        self.assertEqual((sans["quantite"], avec["quantite"]), (1.25, 0.125))
        self.assertAlmostEqual(avec["montant_usd"], sans["montant_usd"])
        self.assertAlmostEqual(avec["risque_prevu_eur"], sans["risque_prevu_eur"])
        self.assertAlmostEqual(avec["apres_couts_eur"], sans["apres_couts_eur"])
        self.assertAlmostEqual(avec["multiple_r"], 2.0)

    def test_pas_de_prix_applique_au_cours_reel(self):
        # Cours continu 100, facteur 40 : plus bas réel 3 880,40 ; le stop est arrondi au centime réel.
        marche = marche_fictif()
        marche["divisions"] = ((marche["sessions"][11], 40),)
        marche["atr"] = {session: 0.33 for session in marche["atr"]}
        ajouter_entree(marche, 1, plus_bas=97.01)
        position = chercher_candidats(marche)[0]
        self.assertEqual((position["plus_bas"], position["entree_prix"]), (3880.4, 4000.0))
        self.assertAlmostEqual(position["stop_brut"], 3880.4 - 0.25 * 13.2)
        self.assertEqual(position["stop"], 3877.1)                 # 3 877,10 : un multiple de 0,01 USD réel
        self.assertEqual(position["cible"], 4245.8)

    def test_commissions_calculees_sur_les_actions_reelles(self):
        # Barème « Tiered » : 0,35 USD minimum par ordre. Avec le cours réel, 0,09 action coûte ce minimum ;
        # le cours continu aurait fait croire à dix fois plus d'actions.
        tiered = creer_hypotheses("ibkr_tiered")
        avec, _, _ = self.position(((marche_fictif()["sessions"][11], 10),), tiered)
        sans, _, _ = self.position((), tiered)
        self.assertAlmostEqual(avec["quantite"] * 10, sans["quantite"], places=2)
        self.assertLess(avec["commissions_eur"], sans["commissions_eur"])   # moins d'actions, moins de frais par action
        self.assertAlmostEqual(avec["commissions_eur"], 0.70 + 0.0032 * 2 * avec["quantite"]
                               + 0.0000206 * avec["quantite"] * 1080.0, places=6)

    def test_division_pendant_la_detention_valeur_inchangee(self):
        # La division prend effet entre l'achat (2e séance) et la vente (6e séance).
        division = ((marche_fictif()["sessions"][3], 10),)
        avec, resultat, _ = self.position(division, rang_cible=5)
        sans, reference, _ = self.position((), rang_cible=5)
        self.assertEqual((avec["facteur_division"], avec["seance_detention"]), (10, 5))
        self.assertAlmostEqual(avec["apres_couts_eur"], sans["apres_couts_eur"])
        self.assertAlmostEqual(resultat["equity_eur"], reference["equity_eur"])
        self.assertAlmostEqual(resultat["especes_usd"], reference["especes_usd"])

    def test_position_ouverte_valorisee_en_cours_reels(self):
        marche = marche_fictif(seances=4)
        marche["divisions"] = ((marche["sessions"][11], 10),)
        ajouter_entree(marche, 1)
        resultat = simuler_portefeuille([marche], un_pour_un, pas_quantite=PAS_FRACTION)
        position = resultat["positions"][0]
        self.assertEqual((position["statut"], position["dernier_prix"]), ("OUVERTE", 1000.0))
        self.assertAlmostEqual(resultat["equity_eur"], 1000.0)   # 875 EUR + 0,125 action à 1 000 USD


class TestAvecLeMoteurHoraire(unittest.TestCase):
    """Le plan part du vrai journal de l'étape 3, sur le scénario fictif 120 / 100 / 112."""

    def test_le_declencheur_reste_horaire_et_ancre_a_09h30(self):
        # Les barres de 30 minutes ne servent qu'à reconstruire ces bougies : sept créneaux par séance,
        # six d'une heure à partir de 09:30, puis la dernière tranche de 30 minutes.
        seance = construire_grille(date(2025, 7, 8), date(2025, 7, 8))
        heures = [creneau["debut"].astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") for creneau in seance]
        self.assertEqual(heures, ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"])
        self.assertEqual([(creneau["fin"] - creneau["debut"]).seconds // 60 for creneau in seance], [60] * 6 + [30])
        daily, horaires, instant = scenario_fictif_sortie()
        marche = preparer_marche("FICTIF", daily, horaires, instant)
        debuts = {creneau["debut"] for creneau in marche["grille"]}
        signaux = [ligne for ligne in marche["journal"] if ligne["signal_horaire"] is True]
        self.assertTrue(signaux)
        for ligne in signaux:
            self.assertIn(ligne["signal_debut"], debuts)   # jamais une demi-heure isolée

    def test_journal_horaire_expose_le_plus_bas_du_repli(self):
        daily, horaires, instant = scenario_fictif_sortie()
        journal = scanner_entrees(daily, horaires, instant)
        signal = next(ligne for ligne in journal if ligne["statut"] == "SIGNAL")
        self.assertEqual(signal["plus_bas_repli"], 112.0)
        self.assertIsNone(journal[0]["plus_bas_repli"])   # avant toute configuration

    def test_stop_fige_a_la_cloture_j2_avec_l_atr_de_j2(self):
        daily, horaires, instant = scenario_fictif_sortie()
        marche = preparer_marche("FICTIF", daily, horaires, instant)
        position = simuler_portefeuille([marche], un_pour_un, pas_quantite=PAS_FRACTION)["positions"][0]
        self.assertEqual(position["plus_bas"], 112.0)
        self.assertEqual(position["atr_seance"], daily[62]["date"])          # J2, clôturée au signal
        self.assertEqual(position["atr"], calculer_atr(daily[:63])[62])
        self.assertEqual(position["stop"], calculer_stop(112.0, position["atr"], "0.01")[1])
        self.assertEqual(position["entree_prix"], 114.2)
        self.assertEqual((position["statut"], position["motif"], position["seance_detention"]),
                         ("CLOTUREE", "CIBLE", 3))
        self.assertAlmostEqual(position["apres_couts_eur"], 2 * position["risque_prix_eur"], places=2)
        # La description écrite reprend les niveaux exacts et nomme le résultat sans le dire « net ».
        texte = " ".join(decrire_position(position))
        self.assertIn("Résultat brut théorique", texte)
        self.assertNotIn("net", texte.lower())

    def test_signal_en_seance_utilise_l_atr_de_la_veille(self):
        daily, horaires, ouverture_j3 = jeu_horaire()
        barres_j2 = [ligne for ligne in horaires if ligne["session"] == daily[62]["date"]]
        barres_j2[-1].update(high=113.5, cloture=113.0)
        daily[62]["cloture"] = 113.0
        premiere = next(ligne for ligne in horaires if ligne["debut"] == ouverture_j3)
        premiere["cloture"] = 114.2            # signal à 10:30 pendant J3
        marche = preparer_marche("FICTIF", daily, horaires, premiere["fin"])
        position = chercher_candidats(marche)[0]
        self.assertEqual(position["entree_instant"], premiere["fin"])
        self.assertEqual(position["atr_seance"], daily[62]["date"])   # J2 : J3 n'est pas terminée
        self.assertNotIn(daily[63]["date"], marche["atr"])

    def test_futur_de_la_bougie_d_entree_sans_effet_sur_le_plan_ni_la_taille(self):
        daily, horaires, instant = scenario_fictif_sortie()
        reference = simuler_portefeuille([preparer_marche("FICTIF", daily, horaires, instant)],
                                         un_pour_un, pas_quantite=PAS_FRACTION)["positions"][0]
        entree = next(ligne for ligne in horaires if ligne["debut"] == reference["entree_instant"])
        entree.update(low=111.0, cloture=113.0)   # le Low de la bougie d'entrée passe sous le stop
        modifie = simuler_portefeuille([preparer_marche("FICTIF", daily, horaires, instant)],
                                       un_pour_un, pas_quantite=PAS_FRACTION)["positions"][0]
        for champ in ("entree_prix", "stop", "cible", "quantite", "risque_prevu_eur", "equity_eur"):
            with self.subTest(champ=champ):
                self.assertEqual(modifie[champ], reference[champ])
        # L'achat reste acquis ; seule l'issue change : stop touché dès D1.
        self.assertEqual((modifie["motif"], modifie["seance_detention"]), ("STOP", 1))

    def test_ouverture_sous_le_stop_entree_etape_3_inchangee_position_refusee(self):
        daily, horaires, ouverture_j3 = jeu_horaire()
        premiere = next(ligne for ligne in horaires if ligne["debut"] == ouverture_j3)
        premiere.update(ouverture=111.0, low=111.0)   # au-dessus des 50 % (110), sous le stop
        marche = preparer_marche("FICTIF", daily, horaires, ouverture_j3)
        self.assertEqual(len([ligne for ligne in marche["journal"] if ligne["statut"] == "ENTREE_ACCEPTEE"]), 1)
        position = simuler_portefeuille([marche], un_pour_un)["positions"][0]
        self.assertEqual((position["statut"], position["motif"]), ("REFUSEE", "ENTREE_SOUS_STOP"))
        self.assertGreater(position["stop"], 111.0)

    def test_invalidation_du_signal_apres_l_entree_n_est_pas_une_sortie(self):
        daily, horaires, instant = scenario_fictif_sortie()
        # Une séance plus agitée avant le sommet augmente l'ATR : l'objectif passe au-dessus de 120.
        daily[55]["low"] = 97.0
        # À D2, un plus haut dépasse le sommet (120) sans atteindre l'objectif.
        jour_d2 = daily[64]["date"]
        [ligne for ligne in horaires if ligne["session"] == jour_d2][2]["high"] = 120.05
        daily[64]["high"] = 120.05
        marche = preparer_marche("FICTIF", daily, horaires, instant)
        position = chercher_candidats(marche)[0]
        self.assertGreater(position["cible"], 120.05)
        # Pour le scanner Daily, ce nouveau plus haut invalide bien la configuration…
        self.assertIn("NOUVEAU_HIGH", scanner_pullbacks(daily[:65])[64]["motif"])
        # … mais la position continue : elle sort à l'objectif à D3, pas à D2.
        self.assertEqual((position["_issue"]["motif"], position["_issue"]["seance_detention"]), ("CIBLE", 3))

    def test_horloges_j_et_d_distinctes(self):
        daily, horaires, instant = scenario_fictif_sortie()
        position = chercher_candidats(preparer_marche("FICTIF", daily, horaires, instant))[0]
        # Sommet J0 = séance 60 : l'entrée a lieu à J3, qui est D1 ; D10 tombe à J12, après la fenêtre J3–J10.
        self.assertEqual(position["seance_d1"], daily[63]["date"])
        self.assertGreater(position["seance_d10"], daily[70]["date"])

    def test_plan_en_attente_a_la_cloture_du_signal(self):
        daily, horaires, _ = scenario_fictif_sortie()
        fin_j2 = [ligne for ligne in horaires if ligne["session"] == daily[62]["date"]][-1]["fin"]
        marche = preparer_marche("FICTIF", daily, horaires, fin_j2)
        plan = plan_en_attente(marche)
        self.assertEqual(plan["plus_bas"], 112.0)
        self.assertEqual(plan["stop"], calculer_stop(112.0, plan["atr"], "0.01")[1])
        self.assertIsNone(plan["motif"])
        self.assertEqual(chercher_candidats(marche), [])   # pas encore d'entrée : aucune position
        apres = preparer_marche("FICTIF", daily, horaires, fin_j2 + timedelta(days=1))
        self.assertIsNone(plan_en_attente(apres))

    def test_historique_daily_insuffisant_stop_non_evaluable(self):
        marche = marche_fictif()
        ajouter_entree(marche, 1)
        marche["atr"] = {}
        position = deepcopy(chercher_candidats(marche)[0])
        self.assertEqual((position["statut"], position["motif"]), ("NON_EVALUABLE", "ATR_INDISPONIBLE"))


if __name__ == "__main__":
    unittest.main()
