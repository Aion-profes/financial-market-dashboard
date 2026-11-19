"""Graphiques du tableau de bord : un graphique Daily et un graphique horaire.

Chaque fonction reçoit un « état du jour » (voir etat_du_jour.py) et renvoie une
figure Plotly. Aucune règle n'est calculée ici : on dessine ce qui a été décidé.
"""

import plotly.graph_objects as go

from etape_02_pullback import DERNIERE_SEANCE_ADMISSIBLE
from etat_du_jour import EN_ATTENTE, NEW_YORK, REMPLIE, nombre_fr, prix_fr


# Couleurs par rôle, en clair et en sombre. Les bougies restent neutres (creuse =
# hausse, pleine = baisse) pour que la couleur serve seulement aux moyennes et à l'entrée.
JETONS = {
    "light": {
        "surface": "#fcfcfb", "encre": "#0b0b0b", "encre2": "#52514e", "discret": "#898781",
        "grille": "#e1e0d9", "axe": "#c3c2b7",
        "sma20": "#2a78d6", "sma50": "#eb6834", "entree": "#1baf7a", "sortie": "#eb6834",
    },
    "dark": {
        "surface": "#1a1a19", "encre": "#f0efec", "encre2": "#c3c2b7", "discret": "#898781",
        "grille": "#2c2c2a", "axe": "#383835",
        "sma20": "#3987e5", "sma50": "#d95926", "entree": "#199e70", "sortie": "#d95926",
    },
}
POLICE = 'system-ui, -apple-system, "Segoe UI", sans-serif'
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc."]
HAUTEUR = 430
MARGES = {"l": 56, "r": 150, "t": 40, "b": 40}
ECART_ETIQUETTES = 17   # pixels minimum entre deux étiquettes de la marge droite


def configuration_recente(etat):
    """La configuration n'est dessinée que tant qu'elle date de dix séances au plus."""
    configuration = etat["configuration"]
    if configuration is None or configuration["age_seances"] is None:
        return None
    if configuration["limite_50"] is None or configuration["age_seances"] > DERNIERE_SEANCE_ADMISSIBLE:
        return None
    return configuration


def fenetre_ouverte(etat):
    """La fenêtre J3–J10 n'est montrée que si le pullback est rempli ou en attente."""
    conditions = etat["conditions"]
    return (configuration_recente(etat) is not None and len(conditions) > 1
            and conditions[1]["etat"] in (REMPLIE, EN_ATTENTE))


def _mettre_en_page(figure, jetons, categories, graduations, bas, haut):
    """Mise en page commune : axes discrets, grille fine, légende en haut."""
    figure.update_layout(
        height=HAUTEUR, margin=MARGES, showlegend=True, dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": POLICE, "size": 12, "color": jetons["encre2"]},
        separators=", ", hovermode="x unified",
        hoverlabel={"bgcolor": jetons["surface"], "bordercolor": jetons["axe"],
                    "font": {"family": POLICE, "color": jetons["encre"]}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0},
    )
    figure.update_xaxes(
        type="category", categoryorder="array", categoryarray=categories,
        range=[-0.5, len(categories) - 0.5], tickmode="array",
        tickvals=[valeur for valeur, _ in graduations], ticktext=[texte for _, texte in graduations],
        showgrid=False, showline=True, linecolor=jetons["axe"], ticks="outside",
        tickcolor=jetons["axe"], tickfont={"color": jetons["discret"]},
        fixedrange=True, rangeslider={"visible": False},
    )
    figure.update_yaxes(
        range=[bas, haut], gridcolor=jetons["grille"], gridwidth=1, zeroline=False,
        showline=False, tickfont={"color": jetons["discret"]}, fixedrange=True,
        tickformat=",.0f" if haut - bas > 20 else ",.1f",
    )


def _etendue(valeurs):
    """Bornes de l'axe vertical, avec un peu d'air au-dessus et en dessous."""
    valeurs = [valeur for valeur in valeurs if valeur is not None]
    bas, haut = min(valeurs), max(valeurs)
    marge = 0.07 * (haut - bas or 1.0)
    return bas - marge, haut + marge


def _etiqueter_a_droite(figure, etiquettes, bas, haut, jetons):
    """Écrit des étiquettes dans la marge droite, sans qu'elles se chevauchent.

    etiquettes : liste de (valeur, texte). Une étiquette déplacée reste reliée à
    sa vraie hauteur par un petit trait.
    """
    hauteur_trace = HAUTEUR - MARGES["t"] - MARGES["b"]
    pixels_par_unite = hauteur_trace / (haut - bas)
    triees = sorted(etiquettes)
    positions = []
    for valeur, _ in triees:
        position = (valeur - bas) * pixels_par_unite
        if positions and position - positions[-1] < ECART_ETIQUETTES:
            position = positions[-1] + ECART_ETIQUETTES
        positions.append(position)
    for indice in reversed(range(len(positions))):
        plafond = hauteur_trace if indice == len(positions) - 1 else positions[indice + 1] - ECART_ETIQUETTES
        positions[indice] = min(positions[indice], plafond)
    for (valeur, texte), position in zip(triees, positions):
        decalage = position - (valeur - bas) * pixels_par_unite
        figure.add_annotation(
            xref="paper", x=1.0, yref="y", y=valeur, text=texte, showarrow=True,
            ax=12, ay=-decalage, xanchor="left", arrowhead=0, arrowwidth=1,
            arrowcolor=jetons["axe"], font={"size": 12, "color": jetons["encre2"]},
        )


def _trait(figure, x0, x1, y, jetons, pointille=False):
    figure.add_shape(type="line", xref="x", yref="y", x0=x0, x1=x1, y0=y, y1=y,
                     line={"color": jetons["encre2"], "width": 1,
                           "dash": "dot" if pointille else "solid"})


def _bougies(categories, bougies, nom, jetons):
    """Chandeliers neutres : creux quand la clôture dépasse l'ouverture, pleins sinon."""
    textes = [
        f"Ouverture {nombre_fr(bougie['ouverture'])}<br>Plus haut {nombre_fr(bougie['high'])}"
        f"<br>Plus bas {nombre_fr(bougie['low'])}<br>Clôture {nombre_fr(bougie['cloture'])}"
        for bougie in bougies
    ]
    return go.Candlestick(
        x=categories, name=nom,
        open=[bougie["ouverture"] for bougie in bougies], high=[bougie["high"] for bougie in bougies],
        low=[bougie["low"] for bougie in bougies], close=[bougie["cloture"] for bougie in bougies],
        increasing={"line": {"color": jetons["encre2"], "width": 1}, "fillcolor": jetons["surface"]},
        decreasing={"line": {"color": jetons["encre2"], "width": 1}, "fillcolor": jetons["encre2"]},
        hovertext=textes, hoverinfo="text",
    )


def _marqueur(x, y, nom, symbole, couleur, jetons, texte, legende=True):
    """Un repère d'au moins 10 px, entouré d'un anneau de la couleur du fond."""
    return go.Scatter(
        x=[x], y=[y], mode="markers", name=nom, showlegend=legende,
        marker={"symbol": symbole, "size": 12, "color": couleur,
                "line": {"color": jetons["surface"], "width": 2}},
        hovertemplate=texte + "<extra></extra>",
    )


def figure_daily(etat, mode="light", nombre_seances=126):
    """Chandeliers Daily, SMA20 et SMA50, puis les niveaux de la configuration récente."""
    jetons = JETONS[mode]
    daily = etat["daily"][-nombre_seances:]
    if not daily:
        return None
    # Sans Open (archive Date,High,Low,Close), la clôture précédente sert de repère visuel.
    bougies, precedente = [], daily[0]["cloture"]
    for bougie in daily:
        bougies.append(dict(bougie, ouverture=bougie.get("ouverture", precedente)))
        precedente = bougie["cloture"]
    jours = [bougie["date"] for bougie in bougies]
    configuration = configuration_recente(etat)
    ouverte = fenetre_ouverte(etat)
    futurs = [jour for jour in configuration["seances"] if jour > jours[-1]] if ouverte else []
    tous = jours + futurs
    categories = [jour.strftime("%d/%m/%Y") for jour in tous]
    rang = {jour: indice for indice, jour in enumerate(tous)}
    # Une graduation au début de chaque mois ; l'année figure sur la première et en janvier.
    debuts = [indice for indice, jour in enumerate(tous)
              if indice == 0 or jour.month != tous[indice - 1].month]
    if len(debuts) > 1 and debuts[1] < 8:
        debuts = debuts[1:]   # évite deux mois collés au bord gauche
    graduations = [
        (categories[indice], MOIS[tous[indice].month - 1]
         + (f" {tous[indice].year}" if indice == debuts[0] or tous[indice].month == 1 else ""))
        for indice in debuts
    ]

    tendances = {ligne["date"]: ligne for ligne in etat["tendances"]}
    sma20 = [tendances[jour]["sma20"] if jour in tendances else None for jour in jours]
    sma50 = [tendances[jour]["sma50"] if jour in tendances else None for jour in jours]
    etiquettes = []
    for nom, serie in (("SMA20", sma20), ("SMA50", sma50)):
        if serie[-1] is not None:
            etiquettes.append((serie[-1], f"{nom} {nombre_fr(serie[-1])}"))
    niveaux = []
    if configuration is not None:
        niveaux = [configuration["sommet"], configuration["limite_50"], configuration["creux_reference"]]
        etiquettes += [
            (configuration["sommet"], f"Sommet {nombre_fr(configuration['sommet'])}"),
            (configuration["limite_50"], f"Limite 50 % {nombre_fr(configuration['limite_50'])}"),
            (configuration["creux_reference"], f"Creux {nombre_fr(configuration['creux_reference'])}"),
        ]
    bas, haut = _etendue([bougie["low"] for bougie in bougies] + [bougie["high"] for bougie in bougies]
                         + sma20 + sma50 + niveaux)
    recul = 0.022 * (haut - bas)

    figure = go.Figure()
    figure.add_trace(_bougies(categories[:len(jours)], bougies, "Bougies Daily", jetons))
    for nom, serie, couleur in (("SMA20", sma20, jetons["sma20"]), ("SMA50", sma50, jetons["sma50"])):
        figure.add_trace(go.Scatter(
            x=categories[:len(jours)], y=serie, mode="lines", name=nom,
            line={"color": couleur, "width": 2}, hovertemplate=nom + " %{y:.2f}<extra></extra>"))
    if configuration is not None:
        bord_droit = len(tous) - 0.5
        depart_sommet = rang.get(configuration["date_sommet"], -0.5)
        depart_creux = rang.get(configuration["date_creux"], -0.5)
        _trait(figure, depart_sommet, bord_droit, configuration["sommet"], jetons)
        _trait(figure, depart_sommet, bord_droit, configuration["limite_50"], jetons, pointille=True)
        _trait(figure, depart_creux, bord_droit, configuration["creux_reference"], jetons)
        if configuration["date_sommet"] in rang:
            figure.add_trace(_marqueur(
                categories[rang[configuration["date_sommet"]]], configuration["sommet"] + recul,
                "Sommet de référence", "triangle-down", jetons["encre"], jetons,
                f"Sommet de référence {nombre_fr(configuration['sommet'])}", legende=False))
        if configuration["date_creux"] in rang:
            figure.add_trace(_marqueur(
                categories[rang[configuration["date_creux"]]], configuration["creux_reference"] - recul,
                "Creux de référence", "triangle-up", jetons["encre"], jetons,
                f"Creux de référence {nombre_fr(configuration['creux_reference'])}", legende=False))
    if ouverte and configuration["fenetre_debut"] in rang:
        gauche = rang[configuration["fenetre_debut"]] - 0.5
        droite = rang.get(configuration["fenetre_fin"], len(tous) - 1) + 0.5
        figure.add_shape(type="rect", xref="x", yref="paper", x0=gauche, x1=droite, y0=0, y1=1,
                         fillcolor=jetons["encre"], opacity=0.06, line={"width": 0}, layer="below")
        figure.add_annotation(xref="x", x=droite, xanchor="right", xshift=-4, yref="paper", y=0.02,
                              yanchor="bottom", text="Fenêtre J3–J10", showarrow=False,
                              font={"size": 11, "color": jetons["discret"]})
    entree = etat["entree"]
    if entree is not None and entree["session"] in rang:
        figure.add_trace(_marqueur(
            categories[rang[entree["session"]]], entree["prix"], "Entrée simulée", "circle",
            jetons["entree"], jetons, f"Entrée simulée {prix_fr(entree['prix'])}"))
    _mettre_en_page(figure, jetons, categories, graduations, bas, haut)
    _etiqueter_a_droite(figure, etiquettes, bas, haut, jetons)
    return figure


def figure_horaire(etat, mode="light", nombre_seances=10, position=None):
    """Chandeliers 1 h des dernières séances, avec le signal, l'entrée et la position.

    position : ligne du journal des positions (étape 4). Si elle a été prise et que
    son entrée est visible, son stop et son objectif remplacent les niveaux du signal.
    """
    jetons = JETONS[mode]
    completes = [bougie for bougie in etat["horaires"]
                 if all(bougie[champ] is not None for champ in ("ouverture", "high", "low", "cloture"))]
    if not completes:
        return None
    seances = sorted({bougie["session"] for bougie in completes})[-nombre_seances:]
    bougies = [bougie for bougie in completes if bougie["session"] in seances]
    categories = [bougie["debut"].astimezone(NEW_YORK).strftime("%d/%m %H:%M") for bougie in bougies]
    rang = {bougie["debut"]: indice for indice, bougie in enumerate(bougies)}
    premieres = [indice for indice, bougie in enumerate(bougies)
                 if indice == 0 or bougie["session"] != bougies[indice - 1]["session"]]
    graduations = [(categories[indice], bougies[indice]["session"].strftime("%d/%m")) for indice in premieres]

    configuration = configuration_recente(etat)
    signal, entree = etat["signal"], etat["entree"]
    etiquettes, niveaux = [], []
    suivie = (position is not None and position["statut"] in ("OUVERTE", "CLOTUREE")
              and position["entree_instant"] in rang)
    if suivie:
        # Après l'achat, ce sont le stop et l'objectif qui comptent, plus les niveaux du signal.
        entree = {"instant": position["entree_instant"], "prix": position["entree_prix"]}
        niveaux = [position["stop"], position["cible"]]
        etiquettes += [(position["stop"], f"Stop {nombre_fr(position['stop'])}"),
                       (position["cible"], f"Objectif {nombre_fr(position['cible'])}")]
    depart = None
    if configuration is not None and not suivie:
        depart = next((indice for indice, bougie in enumerate(bougies)
                       if bougie["session"] >= configuration["date_sommet"]), None)
    if depart is not None:
        niveaux = [configuration["sommet"], configuration["limite_50"]]
        etiquettes += [
            (configuration["sommet"], f"Sommet {nombre_fr(configuration['sommet'])}"),
            (configuration["limite_50"], f"Limite 50 % {nombre_fr(configuration['limite_50'])}"),
        ]
    entree_visible = entree is not None and entree["instant"] in rang
    if entree_visible:
        # Le prix exact : une ouverture peut tomber sur un demi-centime (344,285).
        etiquettes.append((entree["prix"], f"Entrée {prix_fr(entree['prix'])}"))
    bas, haut = _etendue([bougie["low"] for bougie in bougies] + [bougie["high"] for bougie in bougies] + niveaux)
    recul = 0.03 * (haut - bas)

    figure = go.Figure()
    figure.add_trace(_bougies(categories, bougies, "Bougies 1 h", jetons))
    for indice in premieres[1:]:
        # Un trait fin sépare deux séances : la nuit n'est pas une bougie manquante.
        figure.add_shape(type="line", xref="x", yref="paper", x0=indice - 0.5, x1=indice - 0.5,
                         y0=0, y1=1, line={"color": jetons["grille"], "width": 1}, layer="below")
    if depart is not None:
        bord_droit = len(bougies) - 0.5
        _trait(figure, depart - 0.5, bord_droit, configuration["sommet"], jetons)
        _trait(figure, depart - 0.5, bord_droit, configuration["limite_50"], jetons, pointille=True)
    if signal is not None and signal["debut"] in rang:
        indice = rang[signal["debut"]]
        if indice > 0:
            _trait(figure, indice - 1, indice, signal["high_precedent"], jetons, pointille=True)
        figure.add_trace(_marqueur(
            categories[indice], bougies[indice]["high"] + recul, "Signal 1 h", "triangle-down",
            jetons["sma20"], jetons,
            f"Signal : clôture {nombre_fr(signal['cloture'])} > plus haut précédent "
            f"{nombre_fr(signal['high_precedent'])}"))
    if entree_visible:
        figure.add_trace(_marqueur(
            categories[rang[entree["instant"]]], entree["prix"], "Entrée simulée", "circle",
            jetons["entree"], jetons, f"Entrée simulée {prix_fr(entree['prix'])}"))
    if suivie:
        # Stop et objectif sont tracés de l'achat jusqu'à la sortie, ou jusqu'au bord si elle est ouverte.
        debut_position = rang[position["entree_instant"]]
        fin_position = rang.get(position["sortie_bougie"], len(bougies) - 1) + 0.5
        _trait(figure, debut_position - 0.5, fin_position, position["stop"], jetons, pointille=True)
        _trait(figure, debut_position - 0.5, fin_position, position["cible"], jetons, pointille=True)
        if position["statut"] == "CLOTUREE" and position["sortie_bougie"] in rang:
            figure.add_trace(_marqueur(
                categories[rang[position["sortie_bougie"]]], position["sortie_prix"], "Sortie simulée",
                "x", jetons["sortie"], jetons,
                f"Sortie simulée {prix_fr(position['sortie_prix'])} ({position['motif']})"))
    _mettre_en_page(figure, jetons, categories, graduations, bas, haut)
    _etiqueter_a_droite(figure, etiquettes, bas, haut, jetons)
    return figure


def figure_intervalles(lignes, mode="light", etendue=None, juge=None):
    """Espérance par position et son intervalle approximatif, une ligne par simulation.

    lignes : liste de (libellé, espérance, borne basse, borne haute), en EUR.
    etendue : (min, max) de l'axe, pour comparer deux figures sur la même échelle.
    juge : libellé du scénario jugé, écrit en gras. Une seule série : pas de légende,
    le titre de la carte la nomme. Le trait vertical marque zéro.
    """
    jetons = JETONS[mode]
    noms = [libelle for libelle, *_ in lignes]
    figure = go.Figure()
    for libelle, _, bas, haut in lignes:
        figure.add_trace(go.Scatter(
            x=[bas, haut], y=[libelle, libelle], mode="lines", showlegend=False,
            line={"color": jetons["axe"], "width": 2},
            hovertemplate=f"{libelle}<br>intervalle {nombre_fr(bas)} à {nombre_fr(haut)} EUR<extra></extra>"))
    figure.add_trace(go.Scatter(
        x=[esperance for _, esperance, _, _ in lignes], y=noms, mode="markers", showlegend=False,
        marker={"size": 11, "color": jetons["sma20"], "line": {"color": jetons["surface"], "width": 2}},
        hovertemplate="%{y}<br>espérance %{x:.2f} EUR par position<extra></extra>"))
    figure.add_vline(x=0, line={"color": jetons["encre2"], "width": 1, "dash": "dot"})
    texte = [f"<b>{nom}</b>" if nom == juge else nom for nom in noms]
    figure.update_layout(
        height=70 + 46 * len(lignes), margin={"l": 150, "r": 16, "t": 10, "b": 36}, dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", separators=", ",
        font={"family": POLICE, "size": 12, "color": jetons["encre2"]},
        hoverlabel={"bgcolor": jetons["surface"], "bordercolor": jetons["axe"],
                    "font": {"family": POLICE, "color": jetons["encre"]}},
    )
    figure.update_yaxes(type="category", categoryorder="array", categoryarray=list(reversed(noms)),
                        tickvals=noms, ticktext=texte, showgrid=False, fixedrange=True,
                        tickfont={"color": jetons["encre2"]}, ticksuffix="  ")
    figure.update_xaxes(gridcolor=jetons["grille"], zeroline=False, fixedrange=True, ticksuffix=" €",
                        tickfont={"color": jetons["discret"]}, range=list(etendue) if etendue else None)
    return figure
