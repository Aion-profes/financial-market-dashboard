"""Tests du logo animé facultatif : fichiers fictifs dans un dossier temporaire."""

from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from apparence import dimensions_png, html_du_logo


def png_vide(largeur, hauteur):
    """Un vrai fichier PNG minimal, transparent, de la taille demandée."""
    def bloc(nature, donnees):
        return (struct.pack(">I", len(donnees)) + nature + donnees
                + struct.pack(">I", zlib.crc32(nature + donnees) & 0xFFFFFFFF))
    lignes = b"".join(b"\x00" + b"\x00" * 4 * largeur for _ in range(hauteur))
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 6, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(lignes)) + bloc(b"IEND", b""))


class TestLogo(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = Path(self.dossier.name) / "logo_anime.png"

    def tearDown(self):
        self.dossier.cleanup()

    def test_sans_fichier_aucun_logo(self):
        self.assertIsNone(html_du_logo(self.chemin))

    def test_bande_de_six_images_carrees_animee_par_etapes(self):
        self.chemin.write_bytes(png_vide(60, 10))
        html = html_du_logo(self.chemin, taille=80)
        self.assertIn("steps(6)", html)
        self.assertIn("background-size: 480px 80px", html)
        self.assertIn("to { background-position: -480px 0; }", html)
        self.assertIn("prefers-reduced-motion", html)   # l'animation s'arrête si l'ordinateur le demande
        self.assertIn("data:image/png;base64,", html)

    def test_image_qui_n_est_pas_une_bande_refusee(self):
        self.chemin.write_bytes(png_vide(25, 10))         # 2,5 images : pas une bande d'images carrées
        self.assertIsNone(html_du_logo(self.chemin))
        self.chemin.write_bytes(b"pas une image")
        self.assertIsNone(html_du_logo(self.chemin))

    def test_dimensions_lues_dans_l_en_tete(self):
        self.assertEqual(dimensions_png(png_vide(864, 144)), (864, 144))
        self.assertIsNone(dimensions_png(b"GIF89a"))


if __name__ == "__main__":
    unittest.main()
