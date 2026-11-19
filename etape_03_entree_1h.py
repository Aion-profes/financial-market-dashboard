"""Entrée horaire AAPL selon SPEC_ENTREE_1H.md, en simulation uniquement."""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from etape_01_tendance import (
    DOSSIER_PROJET, CONVENTION_PRIX, NOMS_SOURCES, SYMBOLES, ecrire_csv, valider_clotures,
)
from etape_02_pullback import (
    DERNIERE_SEANCE_ADMISSIBLE, FACTEUR_SEUIL_SMA20,
    PREMIERE_SEANCE_ADMISSIBLE, RETRACEMENT_MAXIMUM,
    normaliser_bougies, scanner_pullbacks, telecharger_aapl_pullback, telecharger_bougies,
)


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def instant_utc(valeur):
    """Exige un instant avec fuseau, puis le convertit en UTC."""
    if isinstance(valeur, str):
        valeur = datetime.fromisoformat(valeur.strip())
    if not isinstance(valeur, datetime) or valeur.utcoffset() is None:
        raise ValueError("Horodatage avec fuseau obligatoire (exemple 2025-04-09T09:30:00-04:00).")
    return valeur.astimezone(UTC)


def construire_grille(debut, fin):
    """Créneaux NASDAQ réels, avec fermeture anticipée et dernière tranche courte."""
    import pandas_market_calendars as calendriers

    calendrier = calendriers.get_calendar("NASDAQ")
    grille = []
    for jour, seance in calendrier.schedule(start_date=debut, end_date=fin).iterrows():
        ouverture = seance["market_open"].to_pydatetime().astimezone(UTC)
        fermeture = seance["market_close"].to_pydatetime().astimezone(UTC)
        while ouverture < fermeture:
            borne = min(ouverture + timedelta(hours=1), fermeture)
            grille.append({
                "debut": ouverture, "fin": borne, "session": jour.date(),
                "duree_minutes": int((borne - ouverture).total_seconds() / 60),
            })
            ouverture = borne
    return grille


def normaliser_horaires(bougies, instant_evaluation, grille):
    """Valide seulement les champs déjà connaissables à l'instant évalué."""
    limite = instant_utc(instant_evaluation)
    attendus = {creneau["debut"]: creneau for creneau in grille}
    resultat = []
    presents = set()
    for bougie in bougies:
        debut = instant_utc(bougie["debut"])
        if debut > limite:
            continue
        if debut not in attendus:
            raise ValueError(f"Bougie hors grille NASDAQ régulière à {debut.isoformat()}.")
        if debut in presents:
            raise ValueError(f"Bougie en double à {debut.isoformat()}.")
        presents.add(debut)
        creneau = attendus[debut]
        fin = creneau["fin"]
        if "fin" in bougie and instant_utc(bougie["fin"]) != fin:
            raise ValueError("La fin fournie ne correspond pas au créneau NASDAQ.")
        disponible = instant_utc(bougie.get("disponible_a", fin))
        open_disponible = instant_utc(bougie.get("ouverture_disponible_a", debut))
        if disponible < fin or open_disponible < debut:
            raise ValueError("Une donnée ne peut pas être disponible avant son observation.")
        ligne = dict(creneau, disponible_a=disponible,
                     ouverture_disponible_a=open_disponible)
        for champ in ("ouverture", "high", "low", "cloture"):
            connu = (open_disponible <= limite if champ == "ouverture"
                     else disponible <= limite)
            valeur = bougie.get(champ) if connu else None
            ligne[champ] = None if valeur is None else valider_clotures([valeur])[0]
        high, low = ligne["high"], ligne["low"]
        if high is not None and low is not None:
            if low > high:
                raise ValueError("OHLC incohérents, Low supérieur à High.")
            for champ in ("ouverture", "cloture"):
                prix = ligne[champ]
                if prix is not None and not low <= prix <= high:
                    raise ValueError(f"OHLC incohérents, {champ} hors de Low/High.")
        resultat.append(ligne)
    return sorted(resultat, key=lambda ligne: ligne["debut"])


def _preparer_daily(daily, grille, limite):
    """Snapshots causaux existants ; un trou empêche les calculs qui en dépendent."""
    fins = {ligne["session"]: ligne["fin"] for ligne in grille}
    disponibles = {}
    retenues = []
    for ligne in daily:
        jour = ligne["date"]
        if jour > limite.astimezone(NEW_YORK).date():
            continue
        if jour not in fins:
            raise ValueError(f"Date Daily hors séance NASDAQ, {jour}.")
        if fins[jour] > limite:
            continue
        disponibles[jour] = instant_utc(ligne.get("disponible_a", fins[jour]))
        if disponibles[jour] < fins[jour]:
            raise ValueError("Daily disponible avant sa clôture officielle.")
        if disponibles[jour] > limite:
            continue
        retenues.append(ligne)
    retenues = normaliser_bougies(retenues)
    if not retenues:
        return {}, disponibles
    par_date = {ligne["date"]: ligne for ligne in retenues}
    prefixe = []
    for jour in sorted(fins):
        if jour < retenues[0]["date"]:
            continue
        if jour not in par_date:
            break
        prefixe.append(par_date[jour])
    if len(prefixe) < 55:
        return {}, disponibles
    tableaux = scanner_pullbacks(prefixe)
    # Un snapshot exige aussi la disponibilité de tous ses antécédents.
    derniere_reception = datetime.min.replace(tzinfo=UTC)
    for ligne in tableaux:
        jour = ligne["date"]
        derniere_reception = max(derniere_reception, disponibles[jour])
        disponibles[jour] = derniere_reception
    return {ligne["date"]: ligne for ligne in tableaux}, disponibles


def _controler_prix(configuration, high, low, sma20):
    """Les prix reçus peuvent invalider définitivement, même si le Close remonte."""
    motifs = []
    h = Decimal(str(configuration["sommet"]))
    reference = configuration["creux_reference"]
    if high is not None and Decimal(str(high)) > h:
        motifs.append("NOUVEAU_HIGH")
    if low is not None:
        configuration["plus_bas_repli"] = min(configuration["plus_bas_repli"], low)
        if reference is not None and reference < configuration["sommet"]:
            montant = h - Decimal(str(configuration["plus_bas_repli"]))
            hausse = h - Decimal(str(reference))
            if montant > Decimal(str(RETRACEMENT_MAXIMUM)) * hausse:
                motifs.append("RETRACEMENT_SUPERIEUR_50")
        if sma20 is not None and Decimal(str(low)) < (
            Decimal(str(FACTEUR_SEUIL_SMA20)) * Decimal(str(sma20))
        ):
            motifs.append("LOW_SOUS_SMA20_PRECEDENTE")
    if motifs:
        configuration["invalidation"] = ",".join(motifs)
    return configuration["invalidation"]


class _Chronologie:
    """État de simulation, séparé des lignes déjà écrites dans le journal."""

    def __init__(self, grille, bilans, receptions, horaires, debut_analyse):
        self.grille = grille
        self.bilans = bilans
        self.receptions = receptions
        self.horaires = {ligne["debut"]: ligne for ligne in horaires}
        self.indices = {ligne["debut"]: i for i, ligne in enumerate(grille)}
        self.sessions = list(dict.fromkeys(ligne["session"] for ligne in grille))
        self.rangs = {jour: i for i, jour in enumerate(self.sessions)}
        self.fins = {ligne["session"]: ligne["fin"] for ligne in grille}
        self.configuration = None
        self.dernier_daily = None
        self.journal = []
        self.debut_analyse = debut_analyse

    def publier_daily(self, jour):
        ligne = self.bilans[jour]
        self.dernier_daily = ligne
        if ligne["date_sommet"] is None:
            return
        if self.configuration is None or self.configuration["date_sommet"] != ligne["date_sommet"]:
            self.configuration = dict(ligne, invalidation=None, lacune=None,
                                      signal=None, entree=False, tentative=False)
            if ligne["date_confirmation_sommet"] < self.debut_analyse:
                self.configuration["lacune"] = "HISTORIQUE_HORAIRE_INCOMPLET_DEPUIS_J2"
        config = self.configuration
        config["plus_bas_repli"] = min(config["plus_bas_repli"], ligne["plus_bas_repli"])
        config["statut"] = ligne["statut"]
        config["motif"] = ligne["motif"]
        if ligne["statut"] == "INVALIDE":
            config["invalidation"] = ligne["motif"]

    def contexte(self, creneau, instant, cloture=False):
        config = self.configuration
        rang = self.rangs[creneau["session"]]
        precedente = self.sessions[rang - 1] if rang else None
        daily_requis = creneau["session"] if cloture and creneau["fin"] == self.fins[creneau["session"]] else precedente
        bilan = self.bilans.get(daily_requis)
        daily_absent = bilan is None or self.receptions[daily_requis] > instant
        if config is None:
            # Sans le Daily requis, on ignore s'il existe un sommet confirmé.
            if daily_absent:
                return None, None, "NON_EVALUABLE", "DAILY_REQUIS_INDISPONIBLE"
            return None, None, "AUCUNE_CONFIGURATION", "AUCUN_SOMMET_CONFIRME"
        age = rang - self.rangs[config["date_sommet"]]
        indicateurs = self.bilans.get(precedente)
        sma = None
        if indicateurs is not None and self.receptions[precedente] <= instant:
            sma = indicateurs["sma20"]
        if age > DERNIERE_SEANCE_ADMISSIBLE:
            return age, sma, "EXPIREE", "OUVERTURE_APRES_J10"
        if config["invalidation"]:
            return age, sma, "INVALIDE", config["invalidation"]
        if daily_absent:
            return age, sma, "NON_EVALUABLE", "DAILY_REQUIS_INDISPONIBLE"
        if sma is None or config["statut"] == "NON_EVALUABLE":
            return age, sma, "NON_EVALUABLE", config["motif"]
        if config["lacune"]:
            return age, sma, "NON_EVALUABLE", config["lacune"]
        if age < PREMIERE_SEANCE_ADMISSIBLE:
            if age == 2 and cloture and creneau["fin"] == self.fins[creneau["session"]]:
                return age, sma, "PRET", "SIGNAL_FIN_J2_AUTORISE"
            return age, sma, "ATTENTE_J3", "ENTREE_AVANT_J3_INTERDITE"
        return age, sma, "PRET", "CRITERES_RESPECTES"

    def ecrire(self, creneau, instant, evenement, statut, motif, **champs):
        config = self.configuration
        daily = self.dernier_daily
        signal = config["signal"] if config else None
        age = None if config is None else self.rangs[creneau["session"]] - self.rangs[config["date_sommet"]]
        ligne = {
            "instant": instant, "evenement": evenement, "session": creneau["session"],
            "debut": creneau["debut"], "fin": creneau["fin"],
            "duree_minutes": creneau["duree_minutes"],
            "date_sommet": config["date_sommet"] if config else None,
            "confirmation_sommet": config["date_confirmation_sommet"] if config else None,
            "age_seances": age, "date_daily": daily["date"] if daily else None,
            "statut_daily": daily["statut"] if daily else "NON_EVALUABLE",
            "reference_debut": signal["reference_debut"] if signal else None,
            "high_precedent": signal["high_precedent"] if signal else None,
            "signal_debut": signal["debut"] if signal else None,
            "signal_fin": signal["fin"] if signal else None,
            "signal_disponible_a": signal["disponible_a"] if signal else None,
            "cloture_signal": signal["cloture"] if signal else None,
            "ouverture_attendue": signal["ouverture_attendue"] if signal else None,
            "signal_horaire": None, "entree_simulee": None, "prix_entree": None,
            "sma20_reference": None, "statut": statut, "motif": motif,
            # Plus bas du repli connu à cet instant : sert au stop (SPEC_SORTIES_RISQUE.md).
            "plus_bas_repli": config["plus_bas_repli"] if config else None,
        }
        ligne.update(champs)
        self.journal.append(ligne)

    def ouvrir(self, creneau):
        instant = creneau["debut"]
        config = self.configuration
        age, sma, statut, motif = self.contexte(creneau, instant)
        bougie = self.horaires.get(instant)
        prix = None if bougie is None or bougie["ouverture_disponible_a"] > instant else bougie["ouverture"]
        if config is not None:
            invalidation = _controler_prix(config, prix, prix, sma)
            if invalidation and statut != "EXPIREE":
                statut, motif = "INVALIDE", invalidation
            signal = config["signal"]
            if signal and not config["tentative"] and signal["ouverture_attendue"] == instant:
                config["tentative"] = True
                if statut in ("INVALIDE", "EXPIREE", "ATTENTE_J3"):
                    statut = "ENTREE_ANNULEE"
                elif prix is None:
                    statut, motif = "NON_EVALUABLE", "OPEN_SUIVANT_INDISPONIBLE"
                    config["lacune"] = motif
                elif statut == "PRET":
                    config["entree"] = True
                    self.ecrire(creneau, instant, "OUVERTURE", "ENTREE_ACCEPTEE",
                                "OPEN_SUIVANT_VALIDE", entree_simulee=True,
                                prix_entree=prix, sma20_reference=sma)
                    return
                if statut != "NON_EVALUABLE":
                    statut = "ENTREE_ANNULEE"
                self.ecrire(creneau, instant, "OUVERTURE", statut, motif,
                            entree_simulee=None if statut == "NON_EVALUABLE" else False,
                            sma20_reference=sma)
                return
            if config["entree"]:
                statut, motif = "DEJA_ENTREE", "ENTREE_PASSEE_CONSERVEE"
            elif config["tentative"] and statut == "PRET":
                # Une seule tentative par configuration : aucun second signal.
                statut, motif = "SANS_REARMEMENT", "TENTATIVE_UNIQUE_DEJA_UTILISEE"
            elif statut == "PRET":
                statut, motif = "ATTENTE_SIGNAL", "AUCUN_SIGNAL_EN_ATTENTE"
        self.ecrire(creneau, instant, "OUVERTURE", statut, motif, sma20_reference=sma)

    def couverture(self, indice, instant):
        """Une lacune depuis le premier signal possible cache peut-être ce signal."""
        confirmation = self.configuration["date_confirmation_sommet"]
        debut = next(i for i, ligne in enumerate(self.grille)
                     if ligne["session"] == confirmation and ligne["fin"] == self.fins[confirmation])
        if indice < debut:
            return "SOMMET_PAS_ENCORE_CONFIRME"
        reference = self.horaires.get(self.grille[debut - 1]["debut"])
        if reference is None or reference["high"] is None:
            return "REFERENCE_FIN_J2_MANQUANTE"
        if reference["disponible_a"] > instant:
            return "REFERENCE_HORAIRE_PAS_ENCORE_DISPONIBLE"
        for position in range(debut, indice + 1):
            bougie = self.horaires.get(self.grille[position]["debut"])
            if bougie is None:
                return "HISTORIQUE_HORAIRE_INCOMPLET_DEPUIS_J2"
            if bougie["disponible_a"] > instant:
                return "BOUGIE_HORAIRE_PAS_ENCORE_DISPONIBLE"
            if any(bougie[champ] is None for champ in ("high", "low", "cloture")):
                return "OHLC_HORAIRE_INCOMPLET"
        return None

    def cloturer(self, creneau, instant):
        config = self.configuration
        age, sma, statut, motif = self.contexte(creneau, instant, cloture=True)
        bougie = self.horaires.get(creneau["debut"])
        if config is None:
            self.ecrire(creneau, instant, "CLOTURE", statut, motif)
            return
        indice = self.indices[creneau["debut"]]
        if creneau["session"] < config["date_confirmation_sommet"]:
            return
        precedent = self.horaires.get(self.grille[indice - 1]["debut"]) if indice else None
        high_precedent = None
        if precedent is not None and precedent["disponible_a"] <= instant:
            high_precedent = precedent["high"]
        complet = bougie is not None and bougie["disponible_a"] <= instant and all(
            bougie[champ] is not None for champ in ("high", "low", "cloture")
        )
        if bougie is not None and bougie["disponible_a"] <= instant:
            invalidation = _controler_prix(config, bougie["high"], bougie["low"], sma)
            if invalidation and statut != "EXPIREE":
                statut, motif = "INVALIDE", invalidation
        if config["entree"]:
            self.ecrire(creneau, instant, "CLOTURE", "DEJA_ENTREE", "ENTREE_PASSEE_CONSERVEE")
            return
        if statut == "PRET" and config["signal"] is None:
            # À J2, la référence doit être le vrai créneau précédent, même s'il manque.
            manque = self.couverture(indice, instant)
            if manque or not complet or high_precedent is None:
                statut, motif = "NON_EVALUABLE", manque or "BOUGIE_OU_REFERENCE_HORAIRE_MANQUANTE"
            else:
                comparaison = declencheur_horaire(bougie["cloture"], high_precedent)
                if comparaison:
                    suivant = self.grille[indice + 1]
                    config["signal"] = dict(
                        bougie, reference_debut=precedent["debut"],
                        high_precedent=high_precedent, disponible_a=instant,
                        ouverture_attendue=suivant["debut"],
                    )
                    statut, motif = "SIGNAL", "CLOSE_STRICTEMENT_SUPERIEUR_HIGH_PRECEDENT"
                    if suivant["debut"] < instant:
                        config["tentative"] = True
                        statut, motif = "NON_EVALUABLE", "SIGNAL_DISPONIBLE_APRES_OUVERTURE"
                else:
                    statut, motif = "PAS_DE_SIGNAL", "CLOSE_INSUFFISANTE"
                self.ecrire(creneau, instant, "CLOTURE", statut, motif,
                            signal_horaire=comparaison, high_precedent=high_precedent,
                            cloture_signal=bougie["cloture"], sma20_reference=sma)
                return
        elif config["tentative"] and statut == "PRET":
            statut, motif = "SANS_REARMEMENT", "TENTATIVE_UNIQUE_DEJA_UTILISEE"
        elif config["signal"] is not None and statut == "PRET":
            statut, motif = "ATTENTE_OUVERTURE", "PREMIER_SIGNAL_DEJA_RETENU"
        self.ecrire(creneau, instant, "CLOTURE", statut, motif, sma20_reference=sma)


def scanner_entrees(daily, horaires, instant_evaluation, debut=None):
    """Rejoue ouverture et clôture séparément, à partir d'archives horodatées."""
    limite = instant_utc(instant_evaluation)
    if not daily:
        raise ValueError("NON_EVALUABLE, historique Daily absent.")
    debut_historique = min(ligne["date"] for ligne in daily)
    fin = limite.astimezone(NEW_YORK).date()
    grille = construire_grille(debut_historique, fin + timedelta(days=10))
    horaires = normaliser_horaires(horaires, limite, grille)
    if debut is None:
        debut = min((ligne["session"] for ligne in horaires), default=fin)
    if debut > fin:
        raise ValueError("Le début doit précéder l'instant d'évaluation.")
    bilans, receptions = _preparer_daily(daily, grille, limite)
    moteur = _Chronologie(grille, bilans, receptions, horaires, debut)
    evenements = {}
    for jour in bilans:
        reception = receptions[jour]
        if reception <= limite:
            evenements.setdefault(reception, {"daily": [], "clotures": [], "ouvertures": []})["daily"].append(jour)
    for creneau in grille:
        if creneau["session"] < debut or creneau["debut"] > limite:
            continue
        evenements.setdefault(creneau["debut"], {"daily": [], "clotures": [], "ouvertures": []})["ouvertures"].append(creneau)
        if creneau["fin"] <= limite:
            # On garde l'échéance officielle même si une ligne manque ou arrive tard.
            evenements.setdefault(creneau["fin"], {"daily": [], "clotures": [], "ouvertures": []})["clotures"].append(creneau)
            # En particulier, Daily J2 peut arriver quelques minutes après 16 h.
            # La fin J2 est réexaminée à sa réception, jamais antidatée.
            jour = creneau["session"]
            if creneau["fin"] == moteur.fins[jour] and jour in receptions:
                reception = receptions[jour]
                if creneau["fin"] < reception <= limite:
                    evenements.setdefault(reception, {"daily": [], "clotures": [], "ouvertures": []})["clotures"].append(creneau)
    # Une réception tardive peut encore préparer une ouverture future. Le maximum
    # cumulé évite de sauter une barre antérieure qui cache le premier signal.
    for bilan in bilans.values():
        if bilan["date_confirmation_sommet"] != bilan["date"]:
            continue
        confirmation = bilan["date"]
        premier = next(i for i, ligne in enumerate(grille)
                       if ligne["session"] == confirmation and ligne["fin"] == moteur.fins[confirmation])
        reception = grille[premier]["fin"]
        # La bougie de référence (premier - 1) compte pour la date de réception,
        # mais sa propre clôture n'est pas rejouée : elle précède la confirmation.
        for position, creneau in enumerate(grille[premier - 1:], premier - 1):
            age = moteur.rangs[creneau["session"]] - moteur.rangs[bilan["date_sommet"]]
            if age > DERNIERE_SEANCE_ADMISSIBLE or creneau["fin"] > limite:
                break
            bougie = moteur.horaires.get(creneau["debut"])
            if bougie is not None:
                reception = max(reception, bougie["disponible_a"])
            requis = creneau["session"] if creneau["fin"] == moteur.fins[creneau["session"]] else moteur.sessions[moteur.rangs[creneau["session"]] - 1]
            reception = max(reception, receptions.get(requis, creneau["fin"]))
            if (position >= premier and creneau["session"] >= debut
                    and creneau["fin"] < reception <= limite):
                groupe = evenements.setdefault(reception, {"daily": [], "clotures": [], "ouvertures": []})
                if creneau not in groupe["clotures"]:
                    groupe["clotures"].append(creneau)
    for instant, groupe in sorted(evenements.items()):
        for jour in sorted(groupe["daily"]):
            moteur.publier_daily(jour)
        for creneau in sorted(groupe["clotures"], key=lambda ligne: ligne["fin"]):
            moteur.cloturer(creneau, instant)
        for creneau in groupe["ouvertures"]:
            moteur.ouvrir(creneau)
    return moteur.journal


def _lignes_csv(chemin, colonnes):
    with Path(chemin).open(encoding="utf-8-sig", newline="") as fichier:
        entete = fichier.readline()
        fichier.seek(0)
        lecteur = csv.DictReader(fichier, delimiter=";" if ";" in entete else ",")
        noms = lecteur.fieldnames or []
        if not set(colonnes).issubset(noms) or len(noms) != len(set(noms)):
            raise ValueError("CSV, colonnes uniques requises " + ", ".join(colonnes))
        return list(lecteur)


def lire_csv_horaire(chemin, instant_evaluation, grille, symbole="AAPL"):
    """Datetime avec fuseau et vrais OHLC ; les cellules vides restent absentes."""
    limite = instant_utc(instant_evaluation)
    bougies = []
    for numero, ligne in enumerate(_lignes_csv(chemin, ("Datetime", "Open", "High", "Low", "Close")), 2):
        try:
            debut = instant_utc(ligne["Datetime"])
            if debut > limite:
                continue
            if "Symbol" in ligne and ligne["Symbol"] != symbole:
                raise ValueError(f"Le CSV doit concerner {symbole}.")
            bougie = {"debut": debut}
            for source, cible in (("Open", "ouverture"), ("High", "high"),
                                  ("Low", "low"), ("Close", "cloture")):
                texte = ligne[source]
                bougie[cible] = texte.replace(",", ".") if texte and texte.strip() else None
            for source, cible in (("End", "fin"), ("AvailableAt", "disponible_a"),
                                  ("OpenAvailableAt", "ouverture_disponible_a")):
                if ligne.get(source):
                    bougie[cible] = instant_utc(ligne[source])
            bougies.append(bougie)
        except (ValueError, TypeError, AttributeError) as erreur:
            raise ValueError(f"CSV horaire ligne {numero}, {erreur}") from erreur
    return normaliser_horaires(bougies, limite, grille)


def lire_csv_daily_horaire(chemin, instant_evaluation, grille, symbole="AAPL"):
    """Même HLC que le pullback, avec disponibilité facultative pour ce module."""
    limite = instant_utc(instant_evaluation)
    fins = {ligne["session"]: ligne["fin"] for ligne in grille}
    bougies = []
    for numero, ligne in enumerate(_lignes_csv(chemin, ("Date", "High", "Low", "Close")), 2):
        try:
            jour = date.fromisoformat(ligne["Date"].strip())
            if jour > limite.astimezone(NEW_YORK).date():
                continue
            if jour not in fins:
                raise ValueError(f"Date Daily hors séance NASDAQ, {jour}.")
            reception = instant_utc(ligne.get("AvailableAt") or fins[jour])
            if fins[jour] > limite or reception > limite:
                continue
            if "Symbol" in ligne and ligne["Symbol"] != symbole:
                raise ValueError(f"Le CSV doit concerner {symbole}.")
            bougies.append({
                "date": jour, "disponible_a": reception,
                "high": ligne["High"].replace(",", "."),
                "low": ligne["Low"].replace(",", "."),
                "cloture": ligne["Close"].replace(",", "."),
            })
        except (ValueError, TypeError, AttributeError) as erreur:
            raise ValueError(f"CSV Daily ligne {numero}, {erreur}") from erreur
    return bougies


def telecharger_aapl_horaire(debut, instant_evaluation, grille, symbole="AAPL"):
    """Source Yahoo, gardée pour contrôle ; masque les champs pas encore terminés."""
    import pandas as pd
    import yfinance as yf

    limite = instant_utc(instant_evaluation)
    try:
        donnees = yf.download(
            symbole, start=debut.isoformat(),
            end=(limite.astimezone(NEW_YORK).date() + timedelta(days=1)).isoformat(),
            interval="1h", auto_adjust=False, back_adjust=False, repair=False,
            rounding=False, keepna=True, prepost=False, ignore_tz=False,
            multi_level_index=False, threads=False, progress=False, timeout=20,
        )
        if donnees is None or donnees.empty:
            raise ValueError("Yahoo n'a renvoyé aucune bougie horaire.")
        if not {"Open", "High", "Low", "Close"}.issubset(donnees.columns):
            raise ValueError("Open, High, Low et Close obligatoires dans la réponse.")
        bougies = []
        for instant, ligne in donnees.iterrows():
            bougie = {"debut": instant.to_pydatetime()}
            for source, cible in (("Open", "ouverture"), ("High", "high"),
                                  ("Low", "low"), ("Close", "cloture")):
                bougie[cible] = None if pd.isna(ligne[source]) else ligne[source]
            bougies.append(bougie)
        return normaliser_horaires(bougies, limite, grille)
    except Exception as erreur:
        raise ValueError(
            f"Téléchargement horaire indisponible, {erreur}. "
            "Secours hors ligne avec --csv-horaire et --csv-daily."
        ) from erreur


def telecharger_marche(debut, instant_evaluation, grille, symbole="AAPL", source="alpaca"):
    """Daily puis horaire depuis la même source : Alpaca par défaut, Yahoo en contrôle."""
    limite = instant_utc(instant_evaluation)
    dernier_jour = max(ligne["session"] for ligne in grille if ligne["fin"] <= limite)
    if source == "yahoo":
        return (telecharger_aapl_pullback(dernier_jour, symbole),
                telecharger_aapl_horaire(debut, limite, grille, symbole))
    # Import tardif : source_alpaca utilise lui-même les fonctions de ce fichier.
    from source_alpaca import telecharger_horaire
    daily = telecharger_bougies(dernier_jour, symbole, "alpaca")
    creneaux = [ligne for ligne in grille
                if ligne["session"] >= debut and ligne["debut"] <= limite]
    if not creneaux:
        raise ValueError("Aucun créneau NASDAQ entre le début et l'instant évalué.")
    try:
        # On demande jusqu'à la fin du créneau en cours ; les prix postérieurs à
        # l'instant évalué sont masqués, et Alpaca retient les 15 dernières minutes.
        horaires, incomplets, _, _ = telecharger_horaire(
            creneaux[0]["debut"], creneaux[-1]["fin"], grille,
            symbole=symbole, instant_evaluation=limite)
    except ValueError as erreur:
        raise ValueError(
            f"{erreur}\nSolutions de secours : --source yahoo, ou --csv-daily avec --csv-horaire."
        ) from None
    if incomplets:
        print(f"Attention : {len(incomplets)} créneau(x) horaire(s) sans bougie complète chez Alpaca.")
    return daily, horaires


def afficher_journal(journal, derniers=15):
    print("\nHeure New York | Événement | J | Daily | Décision | Prix | Motif")
    for ligne in journal if derniers == 0 else journal[-derniers:]:
        instant = ligne["instant"].astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M")
        prix = "ND" if ligne["prix_entree"] is None else f"{ligne['prix_entree']:.2f}"
        age = "ND" if ligne["age_seances"] is None else str(ligne["age_seances"])
        print(f"{instant} | {ligne['evenement']} | {age} | {ligne['statut_daily']} | "
              f"{ligne['statut']} | {prix} | {ligne['motif']}")
    signaux = sum(ligne["signal_horaire"] is True for ligne in journal)
    entrees = sum(ligne["entree_simulee"] is True for ligne in journal)
    refus = sum(ligne["statut"] == "ENTREE_ANNULEE" for ligne in journal)
    print(f"\nBilan du journal complet, {signaux} signal(aux), {entrees} entrée(s), {refus} entrée(s) annulée(s).")


def scenario_fictif(gap=False):
    """Prix inventés sur de vraies séances, pour comprendre la frontière J2/J3."""
    grille = construire_grille(date(2025, 1, 6), date(2025, 6, 30))
    jours = list(dict.fromkeys(ligne["session"] for ligne in grille))[:72]
    daily = []
    for position, jour in enumerate(jours):
        cloture = 80 + 0.5 * position
        high, low = cloture + 0.5, cloture - 0.5
        if position == 58:
            low = 100.0
        if position == 60:
            high = 120.0
        if position > 60:
            cloture = 114 + 0.1 * (position - 61)
            high = 117.0 if position == 61 else (116.0 if position == 62 else 118.0)
            low = 112.0
        daily.append({"date": jour, "high": high, "low": low, "cloture": cloture})
    horaires = []
    for jour in jours[62:]:
        creneaux = [ligne for ligne in grille if ligne["session"] == jour]
        for i, creneau in enumerate(creneaux):
            cloture = 112.8
            high, low = 113.0, 112.0
            ouverture = 112.5
            if i == 0:
                high = daily[jours.index(jour)]["high"]
            if i == len(creneaux) - 1:
                cloture = daily[jours.index(jour)]["cloture"]
                high = max(115.0, cloture)
            if jour == jours[63] and i == 0:
                ouverture = 109.0 if gap else 114.2
                low = min(low, ouverture)
            horaires.append(dict(creneau, ouverture=ouverture, high=high,
                                 low=low, cloture=cloture))
    if gap:
        daily[63]["low"] = 109.0
    ouverture_j3 = next(ligne["debut"] for ligne in grille if ligne["session"] == jours[63])
    return daily, horaires, ouverture_j3


def demonstration_chronologie():
    for gap in (False, True):
        daily, horaires, limite = scenario_fictif(gap)
        journal = scanner_entrees(daily, horaires, limite)
        print("\nSCENARIO FICTIF — " + ("gap à 109" if gap else "ouverture J3 à 114,20"))
        for ligne in journal:
            if ligne["statut"] in ("SIGNAL", "ENTREE_ACCEPTEE", "ENTREE_ANNULEE"):
                print(ligne["instant"].astimezone(NEW_YORK).isoformat(),
                      "Daily", ligne["statut_daily"], ligne["statut"],
                      ligne["prix_entree"], ligne["motif"])


def main():
    analyseur = argparse.ArgumentParser(description="Entrées horaires simulées selon SPEC_ENTREE_1H.md, AAPL par défaut.")
    analyseur.add_argument("--demo", action="store_true", help="Comparaisons et scénarios fictifs.")
    analyseur.add_argument("--symbole", choices=SYMBOLES, default="AAPL", help="Titre analysé.")
    analyseur.add_argument("--source", choices=sorted(NOMS_SOURCES), default="alpaca",
                           help="Téléchargement : alpaca par défaut, yahoo pour contrôler.")
    analyseur.add_argument("--csv-daily", type=Path, help="Archive Date,High,Low,Close.")
    analyseur.add_argument("--csv-horaire", type=Path, help="Archive Datetime,Open,High,Low,Close avec fuseau.")
    analyseur.add_argument("--instant", type=instant_utc, help="Instant inclus ISO avec fuseau, par défaut maintenant.")
    analyseur.add_argument("--debut", type=date.fromisoformat, help="Début d'analyse, par défaut 30 jours avant ou première séance CSV.")
    analyseur.add_argument("--derniers", type=int, default=15, help="Lignes affichées, 0 pour toutes.")
    analyseur.add_argument("--sortie", type=Path, help="Nouveau CSV du journal complet.")
    options = analyseur.parse_args()
    if bool(options.csv_daily) != bool(options.csv_horaire):
        analyseur.error("Fournir ensemble --csv-daily et --csv-horaire.")
    if options.derniers < 0:
        analyseur.error("--derniers doit être positif ou nul.")
    if options.demo and (options.csv_daily or options.instant or options.debut):
        analyseur.error("--demo possède ses propres dates et prix fictifs.")
    try:
        identifiant = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        symbole = options.symbole
        if options.demo:
            demonstration_comparaison()
            demonstration_chronologie()
            daily, horaires, limite = scenario_fictif()
            debut = None
            source = "FICTIF, prix inventés sur le calendrier NASDAQ"
            prefixe = "fictif"
        else:
            limite = options.instant or datetime.now(UTC)
            if limite > datetime.now(UTC):
                raise ValueError("L'instant évalué doit être déjà passé.")
            jour = limite.astimezone(NEW_YORK).date()
            debut = options.debut or (None if options.csv_daily else jour - timedelta(days=30))
            # Un an pour les Daily et dix jours supplémentaires pour trouver t+1.
            grille = construire_grille(min(jour - timedelta(days=400), debut or jour), jour + timedelta(days=10))
            if options.csv_daily:
                daily = lire_csv_daily_horaire(options.csv_daily, limite, grille, symbole)
                horaires = lire_csv_horaire(options.csv_horaire, limite, grille, symbole)
                source = f"CSV {symbole} fourni, origine et convention à vérifier par l'utilisateur"
            else:
                daily, horaires = telecharger_marche(debut, limite, grille, symbole, options.source)
                source = f"Données réelles {symbole}, {NOMS_SOURCES[options.source]}"
                base = f"{symbole.lower()}_{options.source}"
                archive_daily = DOSSIER_PROJET / "donnees" / f"{base}_entree_daily_{identifiant}.csv"
                ecrire_csv(archive_daily, [{"Date": ligne["date"], "High": ligne["high"],
                           "Low": ligne["low"], "Close": ligne["cloture"]} for ligne in daily],
                           ["Date", "High", "Low", "Close"])
                archive_horaire = DOSSIER_PROJET / "donnees" / f"{base}_1h_{identifiant}.csv"
                ecrire_csv(archive_horaire, [{"Datetime": ligne["debut"].isoformat(),
                           "Open": ligne["ouverture"], "High": ligne["high"],
                           "Low": ligne["low"], "Close": ligne["cloture"]} for ligne in horaires],
                           ["Datetime", "Open", "High", "Low", "Close"])
                print(f"Archives hors ligne\n{archive_daily}\n{archive_horaire}")
            prefixe = symbole.lower()
        journal = scanner_entrees(daily, horaires, limite, debut)
        print(f"\nSource {source}\nConvention {CONVENTION_PRIX}, même ajustement pour OHLC")
        print("Simulation historique, disponibilité supposée aux bornes des bougies sauf métadonnées explicites.")
        print(f"Instant évalué {limite.isoformat()}, {len(horaires)} bougies horaires reçues.")
        afficher_journal(journal, options.derniers)
        if not journal:
            raise ValueError("NON_EVALUABLE, aucun événement dans la période demandée.")
        sortie = options.sortie or DOSSIER_PROJET / "resultats" / f"{prefixe}_entree_1h_{identifiant}.csv"
        lignes = [dict(ligne, source=source, convention_prix=CONVENTION_PRIX) for ligne in journal]
        ecrire_csv(sortie, lignes, list(lignes[0]))
        print(f"Journal complet {sortie}")
        return 0
    except (ValueError, OSError, KeyError) as erreur:
        print(f"NON_EVALUABLE — {erreur}")
        return 1


def declencheur_horaire(cloture, high_precedent):
    """True/False si les deux prix existent, None si un prix manque."""
    if cloture is None or high_precedent is None:
        return None
    cloture, high_precedent = valider_clotures([cloture, high_precedent])
    return cloture > high_precedent


def demonstration_comparaison():
    """Trois exemples inventés, indépendants du téléchargement et des Daily."""
    print("COMPARAISONS FICTIVES — High précédent = 113")
    for cloture, high in ((114, 115), (113, 115), (112.8, 114)):
        resultat = declencheur_horaire(cloture, 113)
        print(f"High actuel {high}, Close {cloture} > 113 -> {resultat}")
    print(f"Close absent -> {declencheur_horaire(None, 113)} (NON_EVALUABLE)")


if __name__ == "__main__":
    raise SystemExit(main())
