"""Tableau de bord du playbook : cinq sections, une navigation à gauche.

Lancer depuis le dossier du projet :
    python -m streamlit run tableau_de_bord.py
ou double-cliquer sur ouvrir_tableau_de_bord.bat.

Cette page n'ajoute aucune règle : elle affiche ce que calculent etat_du_jour.py
(conditions d'entrée) et etape_04_sorties_risque.py (stop, objectif, taille, sortie).
Les explications longues sont regroupées dans la section « Hypothèses ».
"""

from datetime import datetime, time, timedelta, timezone
import time as horloge
from zoneinfo import ZoneInfo

import streamlit as st

from apparence import LOGO, html_du_logo
from configuration import bareme_connu, decrire_compte, lire_configuration
from etape_01_tendance import SYMBOLES
from etape_04_sorties_risque import (
    BAREMES_COMMISSIONS, CONFIGURATIONS, MODES_CONVERSION, PAS_ENTIER, PAS_FRACTION, REGLEMENTS,
    SCENARIOS_CHANGE, SCENARIOS_EXECUTION, configurer, cotation_fixe, creer_hypotheses,
    decrire_hypotheses, libelle_resultat, reference_fr, scenario_fictif_sortie, simuler_portefeuille,
)
from etat_du_jour import (
    EN_ATTENTE, INCONNUE, NEW_YORK, NON_REMPLIE, REMPLIE, SANS_OBJET, VERDICTS,
    date_fr, etat_du_titre, expliquer_motif, heure_new_york, nombre_fr, prix_fr, resumer,
)
from graphiques import configuration_recente, figure_daily, figure_horaire, figure_intervalles
from source_bce import convertisseur, telecharger_taux


PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
ACTUALISATION = 300   # secondes entre deux rafraîchissements automatiques
PERIODES = {"3 mois": 63, "6 mois": 126, "1 an": 252}   # en séances de Bourse
HEURES_REJEU = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00", "17:00"]
MODES = ["En direct", "Rejeu", "Démo"]
SECTIONS = {
    "Vue d'ensemble": ":material/space_dashboard:",
    "Analyse d'un titre": ":material/candlestick_chart:",
    "Positions simulées": ":material/account_balance_wallet:",
    "Backtest": ":material/query_stats:",
    "Hypothèses": ":material/tune:",
}
QUANTITES = {"Actions entières": PAS_ENTIER, "Fractions": PAS_FRACTION}
MOMENTS_DEMO = {
    "Signal à la clôture de J2": "signal",
    "Deux heures après l'entrée": "entree",
    "Objectif atteint (D3)": "sortie",
}
PERSONNALISEE = "PERSONNALISEE"
LIBELLES_CONFIGURATION = {
    "IBKR_CASH_AUTO_FRACTIONS_TIERED": "IBKR · Tiered",
    "IBKR_CASH_AUTO_FRACTIONS_FIXED": "IBKR · Fixed",
    "THEORIQUE_SANS_COUTS": "Sans coûts",
    PERSONNALISEE: "Personnalisée",
}
LIBELLES_EXECUTION = {"principal": "Principale · 2 pb", "defavorable": "Défavorable · 10 pb, +1 jour"}
# Les valeurs « synthetique » sont réservées aux tests : elles ne sont pas proposées ici.
COMMISSIONS_PROPOSEES = [nom for nom in BAREMES_COMMISSIONS if nom != "synthetique"]
CONVERSIONS_PROPOSEES = [nom for nom in MODES_CONVERSION if nom != "synthetique"]
# Capital de l'expérience et scénarios de coûts : lus dans le fichier de configuration.
CONFIGURATION = lire_configuration()
CHOIX_CONFIGURATION = list(dict.fromkeys(CONFIGURATION["scenarios"] + list(CONFIGURATIONS) + [PERSONNALISEE]))

# Une icône et un libellé accompagnent toujours la couleur : jamais la couleur seule.
STYLE_VERDICT = {
    "CONDITIONS_REMPLIES": ("green", ":material/check_circle:"),
    "ENTREE_SIMULEE": ("primary", ":material/login:"),
    "EN_ATTENTE": ("blue", ":material/hourglass_top:"),
    "NON_REMPLIES": ("gray", ":material/cancel:"),
    "NON_EVALUABLE": ("orange", ":material/help:"),
}
STYLE_ETAT = {
    REMPLIE: ("green", ":material/check_circle:", "Remplie"),
    NON_REMPLIE: ("gray", ":material/cancel:", "Non remplie"),
    EN_ATTENTE: ("blue", ":material/hourglass_top:", "En attente"),
    INCONNUE: ("orange", ":material/help:", "Inconnue"),
    SANS_OBJET: ("gray", ":material/remove:", "Sans objet"),
}
STYLE_POSITION = {
    "OUVERTE": ("blue", ":material/hourglass_top:", "Ouverte"),
    "CLOTUREE": ("gray", ":material/flag:", "Clôturée"),
    "REFUSEE": ("gray", ":material/block:", "Refusée"),
    "NON_EVALUABLE": ("orange", ":material/help:", "Non évaluable"),
}
NOMS_COURTS = {"Tendance Daily": "Tendance", "Pullback Daily": "Pullback", "Déclencheur 1 h": "Déclencheur"}
STATUTS_FR = {"CLOTUREE": "clôturée(s)", "OUVERTE": "ouverte(s)", "REFUSEE": "refusée(s)",
              "NON_EVALUABLE": "non évaluable(s)"}
EXPLICATIONS = {
    "CONDITIONS_REMPLIES": "Tendance, pullback et déclencheur 1 h réunis ; entrée simulée à l'ouverture horaire suivante.",
    "ENTREE_SIMULEE": "Une entrée a été simulée ; stop, taille et issue dans la position.",
    "EN_ATTENTE": "Une configuration est suivie, il manque une étape.",
    "NON_REMPLIES": "Aucune configuration valide en ce moment.",
    "NON_EVALUABLE": "Une donnée indispensable manque ; aucune décision n'est inventée.",
}
# Résultats du protocole figé (SPEC_SORTIES_RISQUE.md, section 15), lus le 17/11/2026.
# Par simulation : positions clôturées, espérance, bas et haut de l'intervalle, total, drawdown EUR et %.
RESULTATS_BACKTEST = {
    "Développement": {
        "dates": "01/04/2016 – 28/06/2024",
        "lignes": {
            "Tiered · principal": (112, -0.02, -1.19, 1.15, -2.24, 71.47, 6.9),
            "Tiered · défavorable": (112, -0.35, -1.42, 0.72, -39.08, 81.59, 7.9),
            "Fixed · principal": (112, -1.27, -2.05, -0.48, -142.01, 160.44, 15.8),
            "Fixed · défavorable": (112, -1.48, -2.20, -0.75, -165.21, 179.31, 17.7),
            "Sans coûts": (114, 0.80, -0.58, 2.19, 91.71, 69.30, 6.5),
        },
    },
    "Validation": {
        "dates": "01/08/2024 – 31/08/2026",
        "lignes": {
            "Tiered · principal": (27, 0.40, -1.94, 2.74, 10.82, 32.09, 3.2),
            "Tiered · défavorable": (27, 0.13, -2.08, 2.34, 3.46, 32.13, 3.2),
            "Fixed · principal": (27, -0.92, -2.64, 0.81, -24.72, 35.73, 3.6),
            "Fixed · défavorable": (27, -1.11, -2.75, 0.54, -29.84, 37.98, 3.8),
            "Sans coûts": (27, 1.27, -1.46, 4.01, 34.41, 32.02, 3.1),
        },
    },
}
SCENARIO_JUGE = "Tiered · principal"

# Couleurs de la page : fond neutre, cartes claires, une seule couleur d'accent.
SURFACES = {
    "light": {"carte": "#ffffff", "survol": "rgba(255,255,255,0.07)", "actif": "rgba(255,255,255,0.12)"},
    "dark": {"carte": "#1c1c1b", "survol": "rgba(255,255,255,0.05)", "actif": "rgba(255,255,255,0.10)"},
}

st.set_page_config(page_title="Playbook · pullbacks en tendance", page_icon=":material/candlestick_chart:",
                   layout="wide")


# ---------------------------------------------------------------- données

@st.cache_data(ttl=ACTUALISATION - 60, show_spinner=False)
def charger_direct(symbole):
    """Données du moment ; gardées quatre minutes pour ne pas solliciter Alpaca à chaque clic."""
    return etat_du_titre(symbole)


@st.cache_data(show_spinner=False)
def charger_rejeu(symbole, instant_iso):
    """État d'un titre à un instant passé : rien de postérieur n'est utilisé."""
    return etat_du_titre(symbole, datetime.fromisoformat(instant_iso))


@st.cache_data(show_spinner=False)
def charger_demonstration(moment):
    """Prix inventés : sommet 120, creux 100, repli 112, entrée à J3, objectif atteint à D3."""
    daily, horaires, fin_d3 = scenario_fictif_sortie()
    precedente = daily[0]["cloture"]
    for bougie in daily:
        bougie["ouverture"] = min(max(precedente, bougie["low"]), bougie["high"])
        precedente = bougie["cloture"]
    bougies_j2 = [bougie for bougie in horaires if bougie["session"] == daily[62]["date"]]
    bougies_j3 = [bougie for bougie in horaires if bougie["session"] == daily[63]["date"]]
    instants = {
        "signal": bougies_j2[-1]["fin"],                          # clôture de J2 : le signal vient d'apparaître
        "entree": bougies_j3[0]["debut"] + timedelta(hours=2),    # deux heures après l'achat
        "sortie": fin_d3,                                         # l'objectif a été atteint
    }
    return resumer("FICTIF", daily, horaires, instants[moment])


@st.cache_data(ttl=3600, show_spinner=False)
def charger_taux():
    """Taux de référence EUR/USD de la BCE ; un téléchargement par heure suffit."""
    return telecharger_taux()


def taux_de_change_reels():
    """Fonction « instant -> taux de référence » ; sans taux, les positions restent non évaluables."""
    try:
        return convertisseur(charger_taux())
    except ValueError as erreur:
        st.warning(f"Taux de change indisponibles : les positions ne peuvent pas être chiffrées en EUR. {erreur}")
        return lambda _instant: None


def charger_tous(charger):
    """Charge chaque titre ; une panne sur l'un n'empêche pas d'afficher les autres."""
    etats, erreurs = {}, {}
    with st.spinner("Téléchargement des cours…"):
        for symbole in SYMBOLES:
            try:
                etats[symbole] = charger(symbole)
            except (ValueError, OSError) as erreur:
                erreurs[symbole] = str(erreur)
    return etats, erreurs


def donnees_jusqu_a(etats):
    if not etats:
        return ""
    jusqu_a = max(etat["donnees_jusqu_a"] for etat in etats.values())
    return (f"Cours connus jusqu'au {heure_new_york(jusqu_a)} à New York "
            f"({jusqu_a.astimezone(PARIS).strftime('%H:%M')} à Paris)")


def charger_selon_le_mode():
    """Renvoie (états, erreurs, sous-titre, taux de change) selon le mode choisi à gauche."""
    mode = st.session_state["mode"]
    if mode == "Démo":
        moment = st.session_state["moment_demo"]
        return ({"FICTIF": charger_demonstration(MOMENTS_DEMO[moment])}, {},
                f"Démonstration · {moment} · prix inventés, 1 USD = 1 EUR", cotation_fixe(1.0))
    if mode == "Rejeu":
        instant = datetime.combine(st.session_state["jour_rejeu"],
                                   time.fromisoformat(st.session_state["heure_rejeu"]), NEW_YORK)
        if instant > datetime.now(UTC) - timedelta(minutes=16):
            st.warning("Choisis un instant passé depuis au moins 16 minutes : la source ne montre pas les cours plus récents.")
            return {}, {}, "", None
        etats, erreurs = charger_tous(lambda symbole: charger_rejeu(symbole, instant.isoformat()))
        return etats, erreurs, f"Rejeu du {heure_new_york(instant)} à New York · rien de postérieur n'est utilisé", \
            taux_de_change_reels()
    etats, erreurs = charger_tous(charger_direct)
    st.session_state["dernier_chargement"] = horloge.time()
    return etats, erreurs, f"En direct · {donnees_jusqu_a(etats)} · retard imposé de 16 minutes", taux_de_change_reels()


@st.fragment(run_every=ACTUALISATION)
def minuteur():
    """En direct : relance toute la page toutes les cinq minutes."""
    dernier = st.session_state.get("dernier_chargement")
    if st.session_state.get("mode") == "En direct" and dernier and horloge.time() - dernier >= ACTUALISATION - 5:
        st.rerun()


# ---------------------------------------------------------------- simulations

def reglages_choisis():
    """Renvoie (hypothèses, pas de quantité, EUR de départ, USD de départ) selon les réglages."""
    nom = st.session_state["configuration"]
    if nom != PERSONNALISEE:
        hypotheses, pas = configurer(nom, st.session_state["execution"])
        return hypotheses, pas, CONFIGURATION["capital_eur"], CONFIGURATION["usd_depart"]
    hypotheses = creer_hypotheses(
        st.session_state["commissions"], st.session_state["conversion"], st.session_state["scenario_change"],
        st.session_state["glissement"], st.session_state["reglement"], st.session_state["glissement_bps"])
    return (hypotheses, QUANTITES[st.session_state["quantites"]],
            st.session_state["capital"], st.session_state["usd_depart"])


def simuler(etats, taux_change, hypotheses, pas_quantite, capital, usd_depart):
    """Étape 4 : un seul portefeuille pour tous les titres."""
    marches = [etat["marche"] for etat in etats.values() if etat["marche"] is not None]
    if not marches or taux_change is None or capital + usd_depart <= 0:
        return None
    return simuler_portefeuille(marches, taux_change, capital, hypotheses, pas_quantite, usd_depart)


def bilan(portefeuille):
    """Quelques sommes sur les positions clôturées d'un portefeuille simulé."""
    positions = portefeuille["positions"]
    cloturees = [position for position in positions if position["statut"] == "CLOTUREE"]
    return {
        "entrees": len(positions), "prises": sum(position["quantite"] is not None for position in positions),
        "refusees": portefeuille["decompte"]["par_statut"].get("REFUSEE", 0),
        "couts": sum(position["couts_eur"] for position in cloturees),
        "resultat": sum(position["apres_couts_eur"] for position in cloturees),
    }


def comparer_les_baremes(etats, taux_change):
    """Les scénarios de coûts du fichier de configuration, mêmes règles et mêmes données."""
    lignes = []
    for nom in CONFIGURATION["scenarios"]:
        hypotheses, pas = configurer(nom, st.session_state["execution"])
        portefeuille = simuler(etats, taux_change, hypotheses, pas,
                               CONFIGURATION["capital_eur"], CONFIGURATION["usd_depart"])
        if portefeuille is None:
            continue
        sommes = bilan(portefeuille)
        lignes.append({
            "Barème": LIBELLES_CONFIGURATION.get(nom, nom), "Prises": sommes["prises"],
            "Refusées": sommes["refusees"], "Coûts": round(sommes["couts"], 2),
            "Résultat": round(sommes["resultat"], 2),
        })
    return lignes


def tableau_des_baremes(comparaison):
    tableau(comparaison, euros=("Coûts", "Résultat"))
    st.caption("Mêmes règles et mêmes données : seuls les coûts changent. Résultat après coûts simulés, "
               "positions clôturées.")


# ---------------------------------------------------------------- petits éléments

def avec_signe(valeur, unite=" EUR"):
    return "ND" if valeur is None else f"{valeur:+.2f}".replace(".", ",") + unite


def usd_par_eur(taux):
    """Écrit un taux dans le sens de la BCE : combien de USD pour 1 EUR."""
    return "ND" if taux is None else nombre_fr(1 / taux, 4)


def carte(cle, hauteur="content"):
    """Une carte : un conteneur bordé, fond clair, coins arrondis (style injecté plus bas)."""
    return st.container(border=True, key=f"carte-{cle}", height=hauteur)


def titre_de_carte(titre, badge=None):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"**{titre}**")
        if badge is not None:
            libelle, icone, couleur = badge
            st.badge(libelle, icon=icone, color=couleur)


def badge_verdict(verdict):
    couleur, icone = STYLE_VERDICT[verdict]
    return VERDICTS[verdict], icone, couleur


def afficher_cases(cases, colonnes=4):
    """Petites cases libellé / valeur / précision."""
    grille = st.columns(colonnes)
    for indice, (libelle, valeur, precision) in enumerate(cases):
        # Deux espaces puis un retour à la ligne : saut de ligne en Markdown.
        grille[indice % colonnes].markdown(f":gray[{libelle}]  \n**{valeur}**  \n:gray[{precision}]")


def chiffres_en_ligne(chiffres):
    """Une rangée de cartes chiffrées de même hauteur : (libellé, valeur, variation, aide)."""
    for colonne, (libelle, valeur, variation, aide) in zip(st.columns(len(chiffres)), chiffres):
        colonne.metric(libelle, valeur, variation, help=aide, border=True, height="stretch")


def tableau(lignes, euros=(), dollars=(), decimales=()):
    """Un tableau sans index ; montants en euros ou en dollars, écrits selon la langue du navigateur."""
    formats = {**{nom: st.column_config.NumberColumn(format="euro") for nom in euros},
               **{nom: st.column_config.NumberColumn(format="dollar") for nom in dollars},
               **{nom: st.column_config.NumberColumn(format="%.4f") for nom in decimales}}
    st.dataframe(lignes, hide_index=True, column_config=formats)


def ligne_de_conditions(etat):
    """« ✓ Tendance · ✓ Pullback · … Déclencheur » : l'essentiel en une ligne."""
    morceaux = []
    for condition in etat["conditions"]:
        couleur, icone, _ = STYLE_ETAT[condition["etat"]]
        morceaux.append(f":{couleur}[{icone}] {NOMS_COURTS.get(condition['nom'], condition['nom'])}")
    return "   ".join(morceaux) or ":gray[Conditions non calculables]"


def entete(titre, sous_titre):
    st.title(titre, anchor=False)
    if sous_titre:
        st.caption(sous_titre)


def injecter_le_style(sombre):
    """Cartes claires sur fond neutre, menu de gauche sans pastilles radio, titres resserrés."""
    couleurs = SURFACES["dark" if sombre else "light"]
    st.html(f"""<style>
    [data-testid="stMainBlockContainer"] {{ padding-top: 2.4rem; max-width: 1380px; }}
    div[class*="st-key-carte-"], div[data-testid="stMetric"] {{
        background: {couleurs['carte']}; border-radius: 14px; }}
    div[class*="st-key-carte-"] div[data-testid="stMetric"] {{ background: transparent; }}
    .st-key-section [data-testid="stRadioGroup"] {{ gap: 2px; flex-direction: column; align-items: stretch; width: 100%; }}
    .st-key-section [data-testid="stRadio"], .st-key-section [data-testid="stRadio"] > div {{ width: 100%; }}
    .st-key-section [data-testid="stRadioOption"] {{
        width: 100%; max-width: none; margin: 0; padding: 0.55rem 0.8rem; border-radius: 8px; }}
    .st-key-section [data-testid="stRadioOption"] > div > div:first-child {{ display: none; }}
    .st-key-section [data-testid="stRadioOption"]:hover {{ background: {couleurs['survol']}; }}
    .st-key-section [data-testid="stRadioOption"]:has(input:checked) {{ background: {couleurs['actif']}; }}
    .st-key-section [data-testid="stRadioOption"]:has(input:checked) p {{ font-weight: 600; }}
    h1 {{ font-size: 2.1rem !important; letter-spacing: -0.015em; padding-bottom: 0.1rem !important; }}
    [data-testid="stMain"] h3 {{ font-size: 1.3rem !important; padding-top: 0.8rem !important; }}
    </style>""")


# ---------------------------------------------------------------- section : vue d'ensemble

def aller_a(symbole):
    """Bouton « Analyser » d'une carte : ouvre l'analyse de ce titre."""
    st.session_state["section"] = "Analyse d'un titre"
    st.session_state["titre"] = symbole


def carte_titre(symbole, etat, erreur):
    with carte(f"titre-{symbole}", hauteur="stretch"):
        if erreur is not None:
            titre_de_carte(symbole, ("Données indisponibles", ":material/error:", "red"))
            st.caption(erreur[:180] + ("…" if len(erreur) > 180 else ""), help=erreur)
            return
        titre_de_carte(symbole, badge_verdict(etat["verdict"]))
        prix = etat["prix"]
        if prix is None:
            st.metric("Dernier prix", "ND")
        else:
            variation = None if prix["variation"] is None else f"{100 * prix['variation']:+.2f} %".replace(".", ",")
            st.metric("Dernier prix", f"{nombre_fr(prix['valeur'])} $", variation,
                      chart_data=[bougie["cloture"] for bougie in etat["daily"][-40:]] or None,
                      help=f"{heure_new_york(prix['instant'])} à New York ; variation depuis la clôture "
                           "précédente ; courbe : 40 dernières clôtures.")
        st.markdown(ligne_de_conditions(etat))
        st.caption(etat["phrase"])
        st.button("Analyser", icon=":material/arrow_forward:", type="tertiary", key=f"ouvrir-{symbole}",
                  on_click=aller_a, args=(symbole,))


def section_vue_ensemble(contexte):
    etats, erreurs = contexte["etats"], contexte["erreurs"]
    symboles = list(etats) + list(erreurs)
    for colonne, symbole in zip(st.columns(max(len(symboles), 3)), symboles):
        with colonne:
            carte_titre(symbole, etats.get(symbole), erreurs.get(symbole))
    portefeuille = contexte["portefeuille"]
    if portefeuille is None:
        return
    sommes, hypotheses = bilan(portefeuille), contexte["hypotheses"]
    st.subheader("Portefeuille simulé", anchor=False)
    st.caption(f"{LIBELLES_CONFIGURATION[st.session_state['configuration']]} · capital de l'expérience "
               f"{nombre_fr(portefeuille['capital_depart'], 0)} EUR · scénario de coûts simulés, pas un résultat net")
    depart = portefeuille["equity_depart_eur"] or portefeuille["capital_depart"]
    chiffres_en_ligne([
        ("Valorisation", f"{nombre_fr(portefeuille['equity_eur'])} EUR",
         None if portefeuille["equity_eur"] is None else avec_signe(portefeuille["equity_eur"] - depart),
         "Liquidités et positions ouvertes, valorisées en EUR ; variation depuis le départ."),
        ("Positions prises", f"{sommes['prises']} / {sommes['entrees']}", None,
         "Positions prises sur les entrées acceptées par l'étape 3 pendant la période chargée."),
        (libelle_resultat(hypotheses), avec_signe(sommes["resultat"]), None, "Somme des positions clôturées."),
        ("Coûts simulés", f"{nombre_fr(sommes['couts'])} EUR", None,
         "Commissions, change et glissement des positions clôturées."),
    ])
    gauche, droite = st.columns(2)
    with gauche, carte("baremes", hauteur="stretch"):
        titre_de_carte("Barèmes comparés")
        tableau_des_baremes(contexte["comparaison"])
    with droite, carte("recentes", hauteur="stretch"):
        titre_de_carte("Dernières entrées")
        recentes = list(reversed(portefeuille["positions"]))[:5]
        if not recentes:
            st.caption("Aucune entrée acceptée par l'étape 3 sur la période chargée.")
        else:
            tableau([{
                "Titre": position["symbole"], "Entrée": heure_new_york(position["entree_instant"]),
                "Statut": STYLE_POSITION[position["statut"]][2],
                "Résultat": None if position["apres_couts_eur"] is None else round(position["apres_couts_eur"], 2),
            } for position in recentes], euros=("Résultat",))


# ---------------------------------------------------------------- section : analyse d'un titre

def carte_condition(condition, cle):
    couleur, icone, libelle = STYLE_ETAT[condition["etat"]]
    with carte(f"condition-{cle}", hauteur="stretch"):
        titre_de_carte(condition["nom"], (libelle, icone, couleur))
        st.caption(condition["detail"])
        comparaisons = condition.get("comparaisons", [])
        if comparaisons:
            vraies = sum(comparaison["ok"] is True for comparaison in comparaisons)
            with st.popover(f"{vraies} sur {len(comparaisons)} comparaisons", type="tertiary"):
                for comparaison in comparaisons:
                    if comparaison["ok"] is None:
                        st.markdown(f":material/help: {comparaison['nom']} — non calculable")
                        continue
                    icone_ligne = ":green[:material/check:]" if comparaison["ok"] else ":gray[:material/close:]"
                    signe = ">" if comparaison["ok"] else "≤"
                    st.markdown(f"{icone_ligne} {comparaison['nom']} : {nombre_fr(comparaison['gauche'])} "
                                f"{signe} {nombre_fr(comparaison['droite'])}")


def chiffres_de_configuration(etat):
    configuration = etat["configuration"]
    if configuration is None:
        return
    chiffres = [("Sommet de référence", f"{nombre_fr(configuration['sommet'])} $", date_fr(configuration["date_sommet"])),
                ("Plus bas du repli", f"{nombre_fr(configuration['plus_bas_repli'])} $", "depuis J1")]
    if configuration["retracement"] is not None:
        chiffres.append(("Repli", f"{nombre_fr(100 * configuration['retracement'], 1)} %",
                         f"limite 50 % à {nombre_fr(configuration['limite_50'])} $"))
    chiffres.append(("Âge", f"J{configuration['age_seances']}",
                     f"fenêtre {date_fr(configuration['fenetre_debut'])} – {date_fr(configuration['fenetre_fin'])}"))
    chiffres_en_ligne([(libelle, valeur, None, aide) for libelle, valeur, aide in chiffres])


def cases_de_la_position(position, hypotheses):
    """Le détail d'une position : calcul des niveaux, paiement, sortie, coûts et change."""
    cases = []
    if position["stop"] is not None:
        cases.append(("Stop", f"{prix_fr(position['stop'])} $",
                      f"plus bas {prix_fr(position['plus_bas'])} − 0,25 × ATR14 {nombre_fr(position['atr'])}"))
    if position["cible"] is not None:
        cases.append(("Objectif", f"{prix_fr(position['cible'])} $",
                      f"{prix_fr(position['entree_prix'])} + 2 × {prix_fr(position['distance'])}, arrondi au centime supérieur"))
    if position["quantite"] is not None:
        cases.append(("Montant investi", f"{nombre_fr(position['montant_usd'])} USD",
                      f"valorisés {nombre_fr(position['montant_eur'])} EUR"))
        cases.append(("Risque prévu", f"{nombre_fr(position['risque_prevu_eur'])} EUR",
                      f"budget {nombre_fr(position['budget_eur'])} EUR ; dont coûts estimés {nombre_fr(position['couts_stop_eur'])} EUR"))
        if position["conversion_entree_usd"] > 0:
            cases.append(("Paiement de l'achat", f"{nombre_fr(position['conversion_entree_usd'])} USD convertis",
                          "depuis les EUR : il manquait des USD"))
        else:
            cases.append(("Paiement de l'achat", "Aucune conversion", "payé avec les USD déjà détenus"))
    elif position["motif"] == "FONDS_DISPONIBLES_INSUFFISANTS":
        cases.append(("Fonds disponibles", f"{nombre_fr(position['disponible_eur_avant'])} EUR + "
                      f"{nombre_fr(position['disponible_usd_avant'])} USD", "utilisables pour un achat"))
        cases.append(("En attente de règlement", f"{nombre_fr(position['attente_usd_avant'])} USD",
                      "produit d'une vente pas encore réglé"))
    elif position["risque_minimal_eur"] is not None:
        cases.append(("Budget de risque", f"{nombre_fr(position['budget_eur'])} EUR", "0,5 % de l'equity"))
        cases.append(("Plus petite quantité", f"{nombre_fr(position['risque_minimal_eur'])} EUR de risque",
                      f"limite dépassée : {expliquer_motif(position['contrainte'])}"))
    if position["statut"] == "CLOTUREE":
        cases.append(("Sortie théorique", f"{prix_fr(position['sortie_prix'])} $",
                      f"{heure_new_york(position['sortie_instant'])} · séance D{position['seance_detention']}"))
        cases.append(("Résultat de prix", avec_signe(position["brut_eur"]),
                      f"{avec_signe(position['multiple_r'], ' R')}, avant change et coûts"))
        cases.append(("Effet de change", avec_signe(position["effet_change_eur"]),
                      f"1 EUR = {usd_par_eur(position['taux_entree'])} puis {usd_par_eur(position['taux_sortie'])} USD"))
        cases.append(("Coûts simulés", f"{nombre_fr(position['couts_eur'])} EUR",
                      f"commissions {nombre_fr(position['commissions_eur'])} ; change "
                      f"{nombre_fr(position['couts_change_eur'])} ; glissement {nombre_fr(position['glissement_eur'])}"))
        cases.append((libelle_resultat(hypotheses), avec_signe(position["apres_couts_eur"]),
                      f"equity après : {nombre_fr(position['equity_apres_eur'])} EUR"))
    elif position["statut"] == "OUVERTE":
        cases.append(("Détention", f"D{position['seance_detention']} sur 10",
                      f"sortie au plus tard à la clôture du {date_fr(position['seance_d10'])}"))
        cases.append(("Dernier prix", f"{prix_fr(position['dernier_prix'])} $", "dernière bougie 1 h complète"))
    return cases


def carte_position(position, hypotheses):
    couleur, icone, libelle = STYLE_POSITION[position["statut"]]
    with carte("position"):
        titre_de_carte("Position simulée", (libelle, icone, couleur))
        st.caption(f"Entrée du {heure_new_york(position['entree_instant'])} (New York) à "
                   f"{prix_fr(position['entree_prix'])} $ · {expliquer_motif(position['motif'])}")
        chiffres = []
        if position["stop"] is not None:
            chiffres.append(("Stop", f"{prix_fr(position['stop'])} $"))
        if position["cible"] is not None:
            chiffres.append(("Objectif", f"{prix_fr(position['cible'])} $"))
        if position["quantite"] is not None:
            chiffres.append(("Quantité", nombre_fr(position["quantite"], 4)))
            chiffres.append(("Risque prévu", f"{nombre_fr(position['risque_prevu_eur'])} EUR"))
        if position["statut"] == "CLOTUREE":
            chiffres.append((libelle_resultat(hypotheses), avec_signe(position["apres_couts_eur"])))
        elif position["statut"] == "OUVERTE":
            chiffres.append(("Détention", f"D{position['seance_detention']} sur 10"))
        for colonne, (etiquette, valeur) in zip(st.columns(max(len(chiffres), 1)), chiffres):
            colonne.metric(etiquette, valeur)
        with st.expander("Détail : calcul, paiement, coûts et change", icon=":material/receipt_long:"):
            afficher_cases(cases_de_la_position(position, hypotheses))
            notes = []
            if position["ambigu_intrabar"]:
                notes.append("Stop et objectif touchés dans la même bougie : ordre inconnu, stop retenu.")
            if position["cible_a_l_egalite"]:
                notes.append("Objectif touché sans être dépassé : un ordre limite réel n'aurait pas forcément été servi.")
            if position["motif"] == "DUREE_MAX_D10":
                notes.append("Sortie au cours de clôture de D10 : convention de simulation, exécution non garantie.")
            if position["quantite"] is not None and position["attente_usd_avant"]:
                notes.append(f"{nombre_fr(position['attente_usd_avant'])} USD d'une vente attendaient leur règlement : "
                             "ils ne pouvaient pas payer cet achat.")
            if position["taux_entree_jour"] is not None:
                notes.append(f"Valorisation au {reference_fr(position['taux_entree_jour'])} : taux d'information, "
                             "pas d'exécution.")
            notes.append(f"Hypothèses : {decrire_hypotheses(hypotheses)}.")
            notes.append("Barème du compte et exécution non garantis : ce n'est pas un résultat net réaliste.")
            for note in notes:
                st.caption(note)


def carte_plan_en_attente(plan):
    with carte("position"):
        titre_de_carte("Position simulée", ("Signal en attente de son ouverture", ":material/schedule:", "blue"))
        if plan["stop"] is None:
            st.caption(f"Stop non calculable : {expliquer_motif(plan['motif'])}.")
            return
        stop, ouverture = st.columns(2)
        stop.metric("Stop, figé à la clôture du signal", f"{prix_fr(plan['stop'])} $",
                    help=f"plus bas {prix_fr(plan['plus_bas'])} − 0,25 × ATR14 {nombre_fr(plan['atr'])}")
        ouverture.metric("Ouverture attendue", heure_new_york(plan["ouverture_attendue"]), help="heure de New York")
        st.caption("Objectif et quantité seront calculés sur le prix d'ouverture. "
                   "Une ouverture au niveau du stop ou en dessous sera refusée.")


def section_analyse(contexte, mode_theme):
    etats, positions = contexte["etats"], contexte["positions"]
    if not etats:
        st.info("Aucun titre chargé.")
        return
    options = list(etats)
    if st.session_state.get("titre") not in options:
        st.session_state["titre"] = options[0]
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.segmented_control("Titre", options, required=True, key="titre")
        st.segmented_control("Période Daily", list(PERIODES), required=True, key="periode")
    etat = etats[st.session_state["titre"]]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(f"### {etat['symbole']}", width="content")
        libelle, icone, couleur = badge_verdict(etat["verdict"])
        st.badge(libelle, icon=icone, color=couleur)
    st.caption(etat["phrase"])
    chiffres_de_configuration(etat)
    if etat["conditions"]:
        for indice, (colonne, condition) in enumerate(zip(st.columns(len(etat["conditions"])), etat["conditions"])):
            with colonne:
                carte_condition(condition, indice)
    du_titre = [position for position in positions if position["symbole"] == etat["symbole"]]
    position = du_titre[-1] if du_titre else None
    if etat["plan_en_attente"] is not None:
        carte_plan_en_attente(etat["plan_en_attente"])
    elif position is not None:
        carte_position(position, contexte["hypotheses"])
    with carte("graphiques"):
        daily, horaire = st.tabs(["Bougies Daily", "Bougies 1 h"])
        reglages = {"displayModeBar": False}
        with daily:
            figure = figure_daily(etat, mode_theme, PERIODES[st.session_state["periode"]])
            if figure is None:
                st.caption("Aucune bougie Daily à afficher.")
            else:
                st.plotly_chart(figure, theme=None, config=reglages, key=f"daily-{etat['symbole']}")
                st.caption("Bougie creuse : hausse ; pleine : baisse. Niveaux tracés pour une configuration de dix séances au plus.")
        with horaire:
            figure = figure_horaire(etat, mode_theme, position=position)
            if figure is None:
                st.caption("Aucune bougie horaire complète à afficher.")
            else:
                st.plotly_chart(figure, theme=None, config=reglages, key=f"horaire-{etat['symbole']}")
                st.caption("Heures de New York. Triangle : signal. Rond : entrée. Croix : sortie. Pointillés : stop et objectif.")
    with st.expander("Journal des décisions horaires", icon=":material/list:"):
        st.dataframe([{
            "Heure (New York)": heure_new_york(ligne["instant"]), "Événement": ligne["evenement"].capitalize(),
            "J": ligne["age_seances"], "Décision": ligne["statut"], "Explication": expliquer_motif(ligne["motif"]),
            "Prix d'entrée": ligne["prix_entree"],
        } for ligne in reversed(etat["journal"][-60:])], hide_index=True)
    with st.expander("Bougies Daily et moyennes", icon=":material/table:"):
        tendances = {ligne["date"]: ligne for ligne in etat["tendances"]}
        st.dataframe([{
            "Date": date_fr(bougie["date"]), "Ouverture": bougie.get("ouverture"), "Plus haut": bougie["high"],
            "Plus bas": bougie["low"], "Clôture": bougie["cloture"],
            "SMA20": tendances.get(bougie["date"], {}).get("sma20"), "SMA50": tendances.get(bougie["date"], {}).get("sma50"),
        } for bougie in reversed(etat["daily"][-PERIODES[st.session_state["periode"]]:])], hide_index=True)


# ---------------------------------------------------------------- section : positions simulées

def phrase_decompte(decompte):
    """Tous les cas restent comptés, avec leur motif."""
    statuts = ", ".join(f"{nombre} {STATUTS_FR.get(statut, statut)}"
                        for statut, nombre in sorted(decompte["par_statut"].items()))
    motifs = " ; ".join(f"{expliquer_motif(motif)} × {nombre}"
                        for motif, nombre in sorted(decompte["par_motif"].items()))
    return (f"{decompte['entrees']} entrée(s) acceptée(s) par l'étape 3 : {statuts}. Motifs : {motifs}. "
            f"Cas ambigus : {decompte['ambigus']} ; objectifs touchés sans dépassement : {decompte['cibles_a_l_egalite']}.")


def section_positions(contexte):
    portefeuille = contexte["portefeuille"]
    if portefeuille is None:
        st.info("Aucun portefeuille simulé : pas de données ou pas de taux de change.")
        return
    attendus = {devise: sum(attente["montant"] for attente in portefeuille["en_attente"] if attente["devise"] == devise)
                for devise in ("EUR", "USD")}
    echeances = sorted(attente["disponible_a"] for attente in portefeuille["en_attente"] if attente["disponible_a"])
    reference = ("aucun taux disponible" if portefeuille["taux_final"] is None else
                 f"{reference_fr(portefeuille['taux_final_jour'])}, 1 EUR = {usd_par_eur(portefeuille['taux_final'])} USD")
    attente = (f"{nombre_fr(attendus['USD'])} USD" if not attendus["EUR"]
               else f"{nombre_fr(attendus['USD'])} USD, {nombre_fr(attendus['EUR'])} EUR")
    chiffres_en_ligne([
        ("Liquidités en EUR", f"{nombre_fr(portefeuille['especes_eur'])} EUR", None,
         f"Solde comptable. Disponible pour un achat : {nombre_fr(portefeuille['disponible_eur'])} EUR."),
        ("Liquidités en USD", f"{nombre_fr(portefeuille['especes_usd'])} USD", None,
         f"Solde comptable, fonds non réglés compris. Disponible pour un achat : "
         f"{nombre_fr(portefeuille['disponible_usd'])} USD."),
        ("En attente de règlement", attente, None,
         f"Disponible le {heure_new_york(echeances[0])} (New York)." if echeances else "Aucune vente à régler."),
        ("Valorisation en EUR", f"{nombre_fr(portefeuille['equity_eur'])} EUR", None, reference),
    ])
    st.caption(f"Disponible pour un achat : {nombre_fr(portefeuille['disponible_eur'])} EUR et "
               f"{nombre_fr(portefeuille['disponible_usd'])} USD, fonds réglés seulement. Effet de change sur les "
               f"USD détenus : {avec_signe(portefeuille['effet_change_liquidites_eur'])}, sans conversion ni coût. "
               "Rien n'est réservé par un ordre : un achat simulé est payé à l'instant où il est décidé.")
    hypotheses = contexte["hypotheses"]
    with carte("journal"):
        titre_de_carte("Journal des positions, tous titres")
        if not portefeuille["positions"]:
            st.caption("Aucune entrée acceptée par l'étape 3 sur la période chargée.")
        else:
            resultat = libelle_resultat(hypotheses)
            tableau([{
                "Titre": position["symbole"], "Entrée (New York)": heure_new_york(position["entree_instant"]),
                "Prix d'entrée": position["entree_prix"], "Statut": STYLE_POSITION[position["statut"]][2],
                "Explication": expliquer_motif(position["motif"]), "Stop": position["stop"],
                "Objectif": position["cible"], "Quantité": position["quantite"],
                "Prix de sortie": position["sortie_prix"], resultat: position["apres_couts_eur"],
            } for position in reversed(portefeuille["positions"])],
                euros=(resultat,), dollars=("Prix d'entrée", "Stop", "Objectif", "Prix de sortie"),
                decimales=("Quantité",))
            st.caption(phrase_decompte(portefeuille["decompte"]))
            st.caption("Chaque entrée garde sa ligne, même refusée ou non évaluable : aucun cas n'est retiré.")
    gauche, droite = st.columns(2)
    with gauche, carte("conversions", hauteur="stretch"):
        titre_de_carte("Conversions EUR/USD simulées")
        if not portefeuille["conversions"]:
            st.caption("Aucune conversion simulée sur la période.")
        else:
            tableau([{
                "Heure (New York)": heure_new_york(conversion["instant"]), "Titre": conversion["symbole"],
                "Sens": "EUR → USD" if conversion["sens"] == "EUR_VERS_USD" else "USD → EUR",
                "USD": round(conversion["montant_usd"], 2), "EUR": round(conversion["montant_eur"], 2),
                "Coût": round(conversion["cout_eur"], 2),
            } for conversion in reversed(portefeuille["conversions"])],
                euros=("EUR", "Coût"), dollars=("USD",))
        st.caption("Conversion du seul montant manquant ; valorisation au taux de référence BCE, "
                   "taux d'exécution simulé = ce taux, coût compris.")
    with droite, carte("baremes-detail", hauteur="stretch"):
        titre_de_carte("Barèmes comparés")
        tableau_des_baremes(contexte["comparaison"])


# ---------------------------------------------------------------- section : backtest

def section_backtest(mode_theme):
    with carte("verdict"):
        titre_de_carte("Pas d'avantage démontré après coûts", ("Protocole figé", ":material/lock:", "gray"))
        st.caption("Capital de 1 000 EUR, archive figée, règles inchangées, validation lue une seule fois le "
                   "17/11/2026. Sur les deux périodes, l'intervalle de l'espérance du scénario jugé contient zéro.")
    for nom, periode in RESULTATS_BACKTEST.items():
        positions, esperance, bas, haut, total, perte_eur, perte_pct = periode["lignes"][SCENARIO_JUGE]
        st.subheader(f"{nom} · {periode['dates']}", anchor=False)
        chiffres_en_ligne([
            ("Positions clôturées", str(positions), None, None),
            ("Résultat · Tiered", avec_signe(total), None, "Barème « Tiered », exécution principale : le scénario jugé."),
            ("Espérance par position", avec_signe(esperance), None,
             f"Intervalle approximatif : {nombre_fr(bas)} à {nombre_fr(haut)} EUR."),
            ("Drawdown maximal", f"{nombre_fr(perte_eur)} EUR", None, f"{nombre_fr(perte_pct, 1)} % du capital."),
        ])
    toutes = [ligne for periode in RESULTATS_BACKTEST.values() for ligne in periode["lignes"].values()]
    etendue = (min(ligne[2] for ligne in toutes) - 0.4, max(ligne[3] for ligne in toutes) + 0.4)
    colonnes = st.columns(2)
    for colonne, (nom, periode) in zip(colonnes, RESULTATS_BACKTEST.items()):
        with colonne, carte(f"intervalles-{nom}"):
            titre_de_carte(f"Espérance par position · {nom.lower()}")
            lignes = [(libelle, valeurs[1], valeurs[2], valeurs[3]) for libelle, valeurs in periode["lignes"].items()]
            st.plotly_chart(figure_intervalles(lignes, mode_theme, etendue, SCENARIO_JUGE), theme=None,
                            config={"displayModeBar": False}, key=f"intervalles-{nom}")
            st.caption("Point : espérance ; trait : intervalle approximatif ; pointillé : zéro.")
    with st.expander("Tableau complet", icon=":material/table:"):
        tableau([{
            "Période": nom, "Simulation": libelle, "Positions": valeurs[0], "Espérance": valeurs[1],
            "Intervalle bas": valeurs[2], "Intervalle haut": valeurs[3], "Résultat": valeurs[4],
            "Drawdown": valeurs[5], "Drawdown (%)": valeurs[6],
        } for nom, periode in RESULTATS_BACKTEST.items() for libelle, valeurs in periode["lignes"].items()],
            euros=("Espérance", "Intervalle bas", "Intervalle haut", "Résultat", "Drawdown"))
        st.caption("« Principal » : glissement de 2 points de base, règlement au délai en vigueur. « Défavorable » : "
                   "10 points de base, un jour de règlement de plus. Détail : SPEC_SORTIES_RISQUE.md, section 15.")


# ---------------------------------------------------------------- section : hypothèses

def section_hypotheses(contexte):
    hypotheses = contexte["hypotheses"]
    nom = st.session_state["configuration"]
    gauche, droite = st.columns([3, 2])
    with gauche, carte("reglages", hauteur="stretch"):
        titre_de_carte("Hypothèses en vigueur", (LIBELLES_CONFIGURATION[nom], ":material/tune:", "gray"))
        if nom != PERSONNALISEE:
            st.segmented_control("Exécution", list(SCENARIOS_EXECUTION), format_func=LIBELLES_EXECUTION.get,
                                 required=True, key="execution",
                                 help="Glissement en points de base du prix et délai de règlement des ventes.")
        else:
            un, deux = st.columns(2)
            un.number_input("Liquidités de départ (EUR)", min_value=0.0, step=100.0, key="capital")
            deux.number_input("USD détenus au départ", min_value=0.0, step=100.0, key="usd_depart")
            un.radio("Quantités", list(QUANTITES), key="quantites", horizontal=True)
            deux.selectbox("Commissions", COMMISSIONS_PROPOSEES,
                           format_func=lambda cle: BAREMES_COMMISSIONS[cle]["libelle"], key="commissions")
            un.selectbox("Conversion EUR/USD", CONVERSIONS_PROPOSEES,
                         format_func=lambda cle: MODES_CONVERSION[cle]["libelle"], key="conversion")
            deux.selectbox("USD reçus d'une vente", list(SCENARIOS_CHANGE),
                           format_func=SCENARIOS_CHANGE.get, key="scenario_change")
            un.selectbox("Règlement des ventes", list(REGLEMENTS),
                         format_func=lambda cle: REGLEMENTS[cle]["libelle"], key="reglement")
            deux.number_input("Glissement (USD par action)", min_value=0.0, step=0.01, format="%.2f", key="glissement")
            un.number_input("Glissement (points de base)", min_value=0.0, step=1.0, format="%.1f", key="glissement_bps")
        capital = (CONFIGURATION["capital_eur"], CONFIGURATION["usd_depart"]) if nom != PERSONNALISEE else (
            st.session_state["capital"], st.session_state["usd_depart"])
        glissement = ("nul" if not hypotheses["glissement_par_action"] and not hypotheses["glissement_bps"] else
                      f"{nombre_fr(hypotheses['glissement_bps'], 1)} point(s) de base"
                      + (f" + {nombre_fr(hypotheses['glissement_par_action'])} USD par action"
                         if hypotheses["glissement_par_action"] else ""))
        lignes = [
            ("Capital de l'expérience", f"{nombre_fr(capital[0], 0)} EUR et {nombre_fr(capital[1], 0)} USD"),
            ("Risque", "0,5 % de l'equity par position, 1 % au total"),
            ("Commissions", hypotheses["commissions"]["libelle"]),
            ("Conversion EUR/USD", hypotheses["conversion"]["libelle"]),
            ("USD après une vente", SCENARIOS_CHANGE[hypotheses["scenario_change"]]),
            ("Règlement des ventes", REGLEMENTS[hypotheses["reglement"]]["libelle"]),
            ("Glissement", f"{glissement}, sur les ordres au marché"),
        ]
        st.markdown("| Hypothèse | Valeur |\n| --- | --- |\n" + "\n".join(f"| {cle} | {valeur} |" for cle, valeur in lignes))
        st.caption(f"{decrire_compte(CONFIGURATION['compte'])} Source : {CONFIGURATION['fichier']}.")
    with droite, carte("etiquettes", hauteur="stretch"):
        titre_de_carte("Lire les étiquettes")
        for verdict, libelle in VERDICTS.items():
            couleur, icone = STYLE_VERDICT[verdict]
            st.badge(libelle, icon=icone, color=couleur)
            st.caption(EXPLICATIONS[verdict])
    with carte("a-savoir"):
        titre_de_carte("À savoir")
        bareme = bareme_connu(CONFIGURATION["compte"])
        st.markdown(
            "- **Simulation uniquement** : aucun ordre n'est passé, « conditions remplies » n'est pas un conseil d'achat.\n"
            "- **Scénarios de coûts simulés** : "
            + ("le barème du compte est inconnu" if bareme is None else f"barème indiqué : « {bareme.capitalize()} »")
            + " ; aucun résultat affiché n'est un résultat net réaliste.\n"
            "- **Exécution théorique** : chaque sortie est supposée faite au prix de la règle, "
            "ce qu'un ordre réel ne garantit pas.\n"
            "- **Retard de 16 minutes** : une entrée réelle se ferait plus tard et à un autre prix que l'entrée simulée.")


# ---------------------------------------------------------------- réglages et page

CLES_PERSISTANTES = ("section", "mode", "jour_rejeu", "heure_rejeu", "moment_demo", "configuration", "execution",
                     "capital", "usd_depart", "quantites", "commissions", "conversion", "scenario_change",
                     "reglement", "glissement", "glissement_bps", "titre", "periode")


def initialiser_les_reglages():
    """Valeurs de départ ; l'adresse peut contenir ?mode=demo ou ?rejeu=2026-10-16T11:30."""
    # Streamlit relance ce fichier à chaque clic : setdefault ne remplace jamais un choix déjà fait.
    defauts = {
        "section": list(SECTIONS)[0], "mode": MODES[0],
        "jour_rejeu": datetime.now(NEW_YORK).date() - timedelta(days=1), "heure_rejeu": HEURES_REJEU[-1],
        "moment_demo": list(MOMENTS_DEMO)[-1],
        # Le détail suit le premier scénario de coûts de la configuration ; tous restent comparés.
        "configuration": CONFIGURATION["scenarios"][0], "execution": "principal",
        "capital": CONFIGURATION["capital_eur"], "usd_depart": CONFIGURATION["usd_depart"],
        "quantites": list(QUANTITES)[0], "commissions": "aucun", "conversion": "sans_cout",
        "scenario_change": "usd_conserves", "reglement": "immediat", "glissement": 0.0, "glissement_bps": 0.0,
        "titre": None, "periode": "6 mois",
    }
    for cle, valeur in defauts.items():
        st.session_state.setdefault(cle, valeur)
    # Un widget absent de la section affichée perdrait sa valeur : on la garde explicitement.
    for cle in CLES_PERSISTANTES:
        st.session_state[cle] = st.session_state[cle]
    if st.session_state.get("adresse_lue"):
        return
    st.session_state["adresse_lue"] = True
    # ?section=analyse (ou accueil, positions, backtest, hypotheses) ouvre directement une section.
    for section, code in zip(SECTIONS, ("accueil", "analyse", "positions", "backtest", "hypotheses")):
        if st.query_params.get("section") == code:
            st.session_state["section"] = section
    if st.query_params.get("mode") == "demo":
        st.session_state["mode"] = "Démo"
        # ?mode=demo&moment=signal (ou entree, sortie) ouvre directement ce moment.
        for libelle, code in MOMENTS_DEMO.items():
            if st.query_params.get("moment") == code:
                st.session_state["moment_demo"] = libelle
    try:
        instant = datetime.fromisoformat(st.query_params.get("rejeu", ""))
    except ValueError:
        return
    if instant.strftime("%H:%M") in HEURES_REJEU:
        st.session_state["mode"] = "Rejeu"
        st.session_state["jour_rejeu"] = instant.date()
        st.session_state["heure_rejeu"] = instant.strftime("%H:%M")


@st.cache_data(show_spinner=False)
def logo_en_cache(chemin, modifie_le):
    """Le logo n'est relu que si son fichier change (modifie_le sert seulement de clé)."""
    del modifie_le
    return html_du_logo(chemin)


def barre_laterale():
    with st.sidebar:
        if LOGO.exists():
            logo = logo_en_cache(LOGO, LOGO.stat().st_mtime)
            if logo is not None:
                st.html(logo)
        st.markdown("### Playbook")
        st.caption("Pullbacks en tendance · AAPL, NVDA, AVGO")
        st.radio("Navigation", list(SECTIONS), key="section", label_visibility="collapsed", width="stretch",
                 format_func=lambda section: f"{SECTIONS[section]}  {section}")
        st.space("medium")
        st.markdown("**Données**")
        st.segmented_control("Mode", MODES, required=True, key="mode", label_visibility="collapsed")
        if st.session_state["mode"] == "Rejeu":
            st.date_input("Date (New York)", max_value=datetime.now(NEW_YORK).date(), format="DD/MM/YYYY",
                          key="jour_rejeu")
            st.selectbox("Heure (New York)", HEURES_REJEU, key="heure_rejeu")
        elif st.session_state["mode"] == "Démo":
            st.radio("Moment montré", list(MOMENTS_DEMO), key="moment_demo")
        elif st.button("Actualiser", icon=":material/refresh:", type="tertiary"):
            charger_direct.clear()
        st.selectbox("Barème simulé", CHOIX_CONFIGURATION, format_func=LIBELLES_CONFIGURATION.get,
                     key="configuration", help="Détail affiché dans la page. Les barèmes du fichier de "
                                               "configuration restent comparés. Tout se règle dans « Hypothèses ».")
        st.space("medium")
        st.caption("Simulation uniquement · pas un conseil financier.")


initialiser_les_reglages()
barre_laterale()
minuteur()
SOMBRE = st.context.theme.type == "dark"
injecter_le_style(SOMBRE)
MODE_THEME = "dark" if SOMBRE else "light"
SECTION = st.session_state["section"]

if SECTION == "Backtest":
    entete("Backtest", "Dix ans d'historique, deux périodes fixées à l'avance, barèmes IBKR simulés")
    section_backtest(MODE_THEME)
else:
    etats, erreurs, sous_titre, taux_change = charger_selon_le_mode()
    hypotheses, pas_quantite, capital, usd_depart = reglages_choisis()
    portefeuille = simuler(etats, taux_change, hypotheses, pas_quantite, capital, usd_depart)
    contexte = {
        "etats": etats, "erreurs": erreurs, "hypotheses": hypotheses, "portefeuille": portefeuille,
        "positions": [] if portefeuille is None else portefeuille["positions"],
        "comparaison": comparer_les_baremes(etats, taux_change) if taux_change is not None else [],
    }
    entete(SECTION if SECTION != "Vue d'ensemble" else "Tableau de bord", sous_titre)
    if SECTION == "Vue d'ensemble":
        section_vue_ensemble(contexte)
    elif SECTION == "Analyse d'un titre":
        section_analyse(contexte, MODE_THEME)
    elif SECTION == "Positions simulées":
        section_positions(contexte)
    else:
        section_hypotheses(contexte)
