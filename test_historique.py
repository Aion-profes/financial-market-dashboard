"""Tests de l'historique long : barres fictives, dossiers temporaires, aucun réseau."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from etape_03_entree_1h import construire_grille
from historique import (
    ARCHIVE_DEBUT, ARCHIVE_FIN, DIVISIONS, PERIODES, controler_coherence, corriger_daily,
    detecter_divisions, figer_archive, lire_archive, lire_manifeste, preparer_historique,
    rapport_de_couverture, rendre_continu, verifier_divisions,
)
from source_alpaca import DEMI_HEURE


UTC = timezone.utc


def daily(jour, cloture, haut=None, bas=None):
    """Barre Daily fictive, horodatée à minuit à New York comme celles de la source."""
    return {"t": f"{jour.isoformat()}T04:00:00Z", "o": cloture, "h": cloture if haut is None else haut,
            "l": cloture if bas is None else bas, "c": cloture}


def demi_heures(jour, prix):
    """Toutes les demi-heures de la séance régulière de ce jour, à prix constant."""
    barres = []
    for creneau in construire_grille(jour, jour):
        instant = creneau["debut"]
        while instant < creneau["fin"]:
            barres.append({"t": instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "o": prix, "h": prix, "l": prix, "c": prix})
            instant += DEMI_HEURE
    return barres


class TestDivisions(unittest.TestCase):
    AVANT, EFFET = date(2024, 7, 12), date(2024, 7, 15)   # division AVGO de 10 pour 1

    def test_cours_continus_sans_saut_ni_arrondi(self):
        brutes = [daily(self.AVANT, 1700.0), daily(self.EFFET, 170.0)]
        continues = rendre_continu(brutes, DIVISIONS["AVGO"])
        self.assertEqual([barre["c"] for barre in continues], [170.0, 170.0])   # aucun faux gap
        # Aucun arrondi : 1 246,12 / 10 garde ses trois décimales.
        self.assertAlmostEqual(rendre_continu([daily(self.AVANT, 1246.12)], DIVISIONS["AVGO"])[0]["c"], 124.612)
        self.assertEqual(rendre_continu(brutes, ())[0]["c"], 1700.0)

    def test_divisions_lues_dans_les_donnees(self):
        brutes = [daily(self.AVANT, 1700.0), daily(self.EFFET, 170.0)]
        ajustees = [daily(self.AVANT, 170.0), daily(self.EFFET, 170.0)]
        self.assertEqual(detecter_divisions(brutes, ajustees), ((self.EFFET, 10),))
        self.assertEqual(verifier_divisions("AVGO", brutes, ajustees, date(2024, 7, 1), date(2024, 7, 31)),
                         DIVISIONS["AVGO"])
        # L'arrondi des cours ajustés de la source ne crée pas de fausse division.
        self.assertEqual(detecter_divisions([daily(self.AVANT, 157.32)], [daily(self.AVANT, 15.73)]), ())

    def test_table_et_donnees_en_desaccord_arret(self):
        brutes = [daily(self.AVANT, 1700.0), daily(self.EFFET, 170.0)]
        sans_division = [daily(self.AVANT, 1700.0), daily(self.EFFET, 170.0)]
        with self.assertRaises(ValueError):
            verifier_divisions("AVGO", brutes, sans_division, date(2024, 7, 1), date(2024, 7, 31))
        with self.assertRaises(ValueError):   # une division que la table ne connaît pas
            verifier_divisions("AAPL", brutes, [daily(self.AVANT, 170.0), daily(self.EFFET, 170.0)],
                               date(2024, 7, 1), date(2024, 7, 31))


class TestProtocole(unittest.TestCase):
    def test_periodes_disjointes_dans_l_ordre_et_couvertes_par_l_archive(self):
        bornes = [PERIODES[nom] for nom in ("mise_en_route", "developpement", "tampon", "validation")]
        for (_, fin), (debut, _) in zip(bornes, bornes[1:]):
            self.assertLess(fin, debut)
        self.assertEqual(PERIODES["developpement"], (date(2016, 4, 1), date(2024, 6, 28)))
        self.assertEqual(PERIODES["validation"], (date(2024, 8, 1), date(2026, 8, 31)))
        self.assertEqual(bornes[0][0], ARCHIVE_DEBUT)
        self.assertGreater(ARCHIVE_FIN, PERIODES["validation"][1])   # de quoi dénouer une position de fin août

    def test_validation_posterieure_a_toute_division(self):
        dernieres = [jour for divisions in DIVISIONS.values() for jour, _ in divisions]
        self.assertLess(max(dernieres), PERIODES["validation"][0])
        self.assertEqual(max(dernieres), date(2024, 7, 15))


class TestArchive(unittest.TestCase):
    JOURS = (date(2024, 7, 12), date(2024, 7, 15))

    def donnees(self):
        barres_daily = [daily(self.JOURS[0], 1700.0), daily(self.JOURS[1], 170.0)]
        barres_30 = demi_heures(self.JOURS[0], 1700.0) + demi_heures(self.JOURS[1], 170.0)
        return {"AVGO": (barres_daily, barres_30)}

    def test_archive_relue_a_l_identique_et_jamais_reecrite(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            manifeste = figer_archive(self.donnees(), dossier, cree_le=datetime(2026, 11, 16, tzinfo=UTC))
            relues_daily, relues_30 = lire_archive("AVGO", dossier)
            self.assertEqual(relues_daily, self.donnees()["AVGO"][0])
            self.assertEqual(len(relues_30), 26)   # deux séances de treize demi-heures
            self.assertEqual(lire_manifeste(dossier)["fichiers"], manifeste["fichiers"])
            self.assertEqual(manifeste["periodes"]["validation"], ["2024-08-01", "2026-08-31"])
            with self.assertRaises(ValueError):    # une archive figée ne se réécrit pas
                figer_archive(self.donnees(), dossier)

    def test_archive_modifiee_detectee_par_son_empreinte(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            figer_archive(self.donnees(), dossier)
            fichier = dossier / "avgo_1day_brut.csv"
            fichier.write_text(fichier.read_text(encoding="utf-8-sig").replace("1700.0", "1701.0"), encoding="utf-8-sig")
            with self.assertRaises(ValueError):
                lire_archive("AVGO", dossier)
            with self.assertRaises(ValueError):
                lire_archive("NVDA", dossier)       # titre absent de l'archive

    def test_series_continues_pretes_pour_le_moteur(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            figer_archive(self.donnees(), dossier)
            fin = construire_grille(self.JOURS[1], self.JOURS[1])[-1]["fin"]
            historique = preparer_historique("AVGO", fin, dossier)
        self.assertEqual(historique["divisions"], DIVISIONS["AVGO"])
        self.assertEqual([(bougie["date"], bougie["cloture"]) for bougie in historique["daily"]],
                         [(self.JOURS[0], 170.0), (self.JOURS[1], 170.0)])
        # Quatorze bougies horaires (sept par séance), toutes à 170 : aucun saut le jour de la division.
        self.assertEqual(len(historique["horaires"]), 14)
        self.assertEqual({bougie["cloture"] for bougie in historique["horaires"]}, {170.0})


class TestQualite(unittest.TestCase):
    JOUR = date(2024, 6, 10)

    def test_valeur_aberrante_de_la_bougie_daily_reperee(self):
        grille = construire_grille(self.JOUR, self.JOUR)
        barres = demi_heures(self.JOUR, 121.0)
        aberrante = daily(self.JOUR, 121.79, haut=195.95, bas=117.01)
        ecarts = controler_coherence([aberrante], barres, grille)
        self.assertEqual([ecart["date"] for ecart in ecarts], [self.JOUR])
        self.assertGreater(ecarts[0]["ecart"], 0.5)
        # Un écart de quelques centimes n'est pas signalé.
        self.assertEqual(controler_coherence([daily(self.JOUR, 121.0, haut=121.2, bas=120.9)], barres, grille), [])

    def test_regle_de_nettoyage_remplace_le_seul_extreme_fautif(self):
        grille = construire_grille(self.JOUR, self.JOUR)
        barres = demi_heures(self.JOUR, 121.0)
        barres[3].update(h=123.1, l=117.01)   # fourchette réelle de la séance : 117,01 – 123,10
        aberrante = daily(self.JOUR, 121.79, haut=195.95, bas=117.01)
        corrigees, corrections = corriger_daily([aberrante], controler_coherence([aberrante], barres, grille))
        # Le plus haut aberrant est remplacé ; le plus bas, l'ouverture et la clôture ne bougent pas.
        self.assertEqual((corrigees[0]["h"], corrigees[0]["l"], corrigees[0]["c"]), (123.1, 117.01, 121.79))
        self.assertEqual(corrections, [{"date": self.JOUR, "champ": "plus haut", "avant": 195.95, "apres": 123.1}])
        self.assertEqual(aberrante["h"], 195.95)   # la barre d'origine, celle de l'archive, reste intacte
        # Une bougie Daily conforme aux barres de 30 minutes n'est pas modifiée.
        saine = daily(self.JOUR, 121.0, haut=123.1, bas=117.01)
        self.assertEqual(corriger_daily([saine], controler_coherence([saine], barres, grille)), ([saine], []))

    def test_cloture_hors_de_la_fourchette_corrigee_cas_refuse(self):
        grille = construire_grille(self.JOUR, self.JOUR)
        barres = demi_heures(self.JOUR, 121.0)
        douteuse = daily(self.JOUR, 190.0, haut=195.95, bas=117.01)   # la clôture elle-même est aberrante
        with self.assertRaises(ValueError):
            corriger_daily([douteuse], controler_coherence([douteuse], barres, grille))

    def test_rapport_de_couverture_par_periode(self):
        jours = (date(2024, 8, 1), date(2024, 8, 2))
        barres_daily = [daily(jour, 100.0) for jour in jours]
        barres_30 = demi_heures(jours[0], 100.0) + demi_heures(jours[1], 100.0)[:-1]   # une demi-heure manque
        rapport = rapport_de_couverture("AAPL", barres_daily, barres_30, jours[0], jours[1] + timedelta(days=3))
        validation = rapport["periodes"]["validation"]
        self.assertEqual(validation["seances"], 3)                       # jeudi 1er, vendredi 2, lundi 5
        self.assertEqual(validation["daily_manquantes"], [date(2024, 8, 5)])
        self.assertEqual(validation["horaires_trouees"], [jours[1], date(2024, 8, 5)])
        self.assertEqual(rapport["periodes"]["developpement"]["seances"], 0)


if __name__ == "__main__":
    unittest.main()
