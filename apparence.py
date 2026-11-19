"""Logo animé facultatif du tableau de bord.

Déposer dans personnalisation/logo_anime.png une bande d'images carrées, posées
côte à côte de gauche à droite : la page les fait défiler en boucle, en haut du
menu. Sans ce fichier, le menu affiche seulement son titre. Le dossier
personnalisation/ est exclu de Git : une image personnelle n'est jamais publiée.
"""

import base64
import struct

from etape_01_tendance import DOSSIER_PROJET


LOGO = DOSSIER_PROJET / "personnalisation" / "logo_anime.png"
TAILLE = 84                 # pixels à l'écran
DUREE_PAR_IMAGE = 0.9       # secondes


def dimensions_png(contenu):
    """Largeur et hauteur d'un fichier PNG, lues dans son en-tête ; None si ce n'est pas un PNG."""
    if len(contenu) < 24 or contenu[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", contenu[16:24])


def html_du_logo(chemin=LOGO, taille=TAILLE):
    """Code HTML du logo animé, ou None si le fichier manque ou n'est pas une bande d'images carrées.

    L'animation passe d'une image à la suivante sans fondu (« steps »), comme un dessin
    animé. Elle s'arrête si l'ordinateur demande de réduire les animations.
    """
    if not chemin.exists():
        return None
    contenu = chemin.read_bytes()
    dimensions = dimensions_png(contenu)
    if dimensions is None:
        return None
    largeur, hauteur = dimensions
    if hauteur == 0 or largeur % hauteur:
        return None
    images = largeur // hauteur
    donnees = base64.b64encode(contenu).decode("ascii")
    return f"""<style>
    .logo-anime {{
        width: {taille}px; height: {taille}px; background-repeat: no-repeat;
        background-image: url(data:image/png;base64,{donnees});
        background-size: {images * taille}px {taille}px;
        animation: logo-tete {images * DUREE_PAR_IMAGE:.1f}s steps({images}) infinite; }}
    @keyframes logo-tete {{
        from {{ background-position: 0 0; }} to {{ background-position: -{images * taille}px 0; }} }}
    @media (prefers-reduced-motion: reduce) {{ .logo-anime {{ animation: none; }} }}
    </style><div class="logo-anime" role="img" aria-label="Logo animé"></div>"""
