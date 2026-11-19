# Entrée AAPL en 1 h — SPÉCIFICATION VALIDÉE

Validé le 6 novembre 2026. Ce document complète SPEC_PULLBACK.md sans modifier
ses seuils ni les scripts existants. Le déclencheur est programmé dans
`etape_03_entree_1h.py` depuis le 13 novembre 2026.
Les conventions A, B et D sont validées. C autorise aussi un signal à la clôture
J2 pour une entrée à l'ouverture J3, sous les conditions causales ci-dessous.

## 1. Règle d'entrée fournie par l'utilisateur

- Lorsque la tendance Daily et le pullback sont admissibles, retenir la première
  bougie admissible terminée vérifiant `Close_1h[t] > High_1h[t-1]`.
- Exception validée pour préparer l'entrée à J3 : la dernière bougie de J2
  peut déclencher après confirmation du sommet et validation des autres filtres,
  même si le statut Daily J2 reste ATTENTE_J3. Aucune entrée n'a lieu à J2.
- `t-1` désigne la bougie immédiatement précédente selon la grille convenue.
  Égalité et simple mèche au-dessus du niveau ne déclenchent rien.
- Entrée simulée au prix `Open_1h[t+1]`, avant frais et glissement, seulement
  si la configuration demeure valide et si cette ouverture appartient à J3–J10.
- Le sommet Daily et son creux de référence restent figés pour la configuration.
  Le High horaire précédent sert uniquement au déclencheur ; il ne remplace ni
  le sommet Daily, ni J0, ni la référence du retracement.
- Une invalidation ou une ouverture après J10 interdit l'entrée. Après une
  entrée enregistrée, aucune seconde entrée n'est déduite de cette configuration.
  Les sorties, la taille de position et le risque restent à définir.
- **Pas de réarmement — validé le 13 novembre 2026.** Une configuration donne
  droit à un seul signal et à une seule tentative d'entrée. Après une entrée
  annulée, ou une ouverture manquée parce que le signal est arrivé trop tard,
  aucune cassure ultérieure ne crée un second signal pour cette configuration.
  Le journal l'indique par `SANS_REARMEMENT` lorsque les autres critères
  restent respectés. Seul un nouveau sommet de référence ouvre une nouvelle chance.

## 2. Découpage retenu — convention A validée

**Convention A : séance régulière uniquement, grille ancrée sur l'ouverture du
NASDAQ, fuseau `America/New_York`, sans pré-marché ni après-marché.**
Les horaires ordinaires sont 09:30–16:00, avec des clôtures anticipées à prendre
dans le calendrier de chaque séance, jamais dans une durée quotidienne fixe.
Source : [calendrier officiel NASDAQ](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule).

| Séance | Intervalles retenus |
| --- | --- |
| Normale | 09:30–10:30, 10:30–11:30, 11:30–12:30, 12:30–13:30, 13:30–14:30, 14:30–15:30, 15:30–16:00 |
| Clôture à 13:00 | 09:30–10:30, 10:30–11:30, 11:30–12:30, 12:30–13:00 |

Le dernier intervalle dure 30 minutes, même lorsqu'il est parfaitement terminé.
**Le conserver dans la grille, avec sa durée explicite, et l'autoriser comme
référence, déclencheur ou bougie d'entrée.** Cette exception à la durée de
60 minutes est validée ; une tranche de 30 minutes terminée est distincte
d'une bougie de 60 minutes encore en cours.

Conserver `debut`, `fin`, `duree_minutes`, `session` et le fuseau. La fin prévue
est `min(debut + 60 minutes, cloture_session)`. Une bougie utilisée pour le
signal ou sa référence doit être terminée ET effectivement disponible.
La dernière bougie en cours ne devient pas utilisable parce qu'une ligne existe.
Son Open peut néanmoins servir à l'événement d'entrée s'il est déjà connu ;
ses futurs High/Low/Close restent interdits avant leur observation.

Stocker les instants en UTC avec fuseau, identifier la séance en heure de New York.
Ne pas coder un décalage constant avec UTC ou Paris : les changements d'heure
peuvent intervenir à des dates différentes. La grille reçue doit être vérifiée ;
ne jamais renommer artificiellement une bougie 10:00 en bougie 09:30.

## 3. Fin de séance et continuité — convention B validée

**Convention B : continuer la suite des bougies entre deux séances.**
La première bougie d'une séance peut ainsi utiliser le High de la dernière
bougie de la séance précédente comme référence ; la fermeture prévue du marché
n'est pas une bougie manquante. Une référence horaire peut précéder J3.

Un signal sur la dernière bougie terminée d'une séance peut attendre l'ouverture
de la séance suivante, qui est alors l'ouverture suivante de la grille régulière.
Il faut y refaire les contrôles avec les Daily désormais disponibles et le prix
d'ouverture observé. Un signal de J9 peut ainsi conduire à une entrée J10 ;
un signal de clôture J10 ne peut jamais conduire à une entrée J11.

Ne pas réinitialiser la référence horaire à chaque séance ni annuler un signal
du seul fait de la fermeture prévue du marché.
Ne pas déplacer une entrée vers une ouverture ultérieure choisie arbitrairement.

## 4. Articulation des Daily et de J3 — convention C validée avec exception J2

Pendant la séance D encore ouverte, la tendance et la SMA20 utilisables proviennent au plus
de D−1, dernière séance terminée. Le seuil SMA reste `0.96 * SMA20[D-1]`
pendant D ; il est renouvelé à la séance suivante. Ne jamais comparer un ancien
Low au seuil renouvelé d'une séance ultérieure.
Après la clôture D, ses données devenues disponibles permettent d'actualiser la
tendance. La SMA20[D] servira aux prix de la séance suivante, pas rétroactivement
aux Low de D, qui restent comparés à SMA20[D−1].

Les contrôles restent continus depuis J1. Une tendance fausse connue à une
clôture Daily invalide la configuration pour la suite. Elle n'efface jamais
une entrée qui était valide avec les informations connues plus tôt ce jour-là.
Les prix intraday complètent les contrôles de profondeur et de nouveau sommet.

**À J3, le bilan Daily précédent est celui de J2 : il est confirmé mais porte
le statut ATTENTE_J3.** Vérifier ses conditions structurelles et de tendance,
puis calculer l'âge de la séance courante : J3. Exiger simplement que le champ
`admissible` de J2 soit True repousserait à tort la première possibilité à J4.
Ne pas utiliser à la place le bilan complet de J3, encore inconnu le matin.

**Convention C : entrée uniquement dans J3–J10 ; signal autorisé dès la clôture
officielle de J2, puis pendant J3–J10.** La dernière bougie de J2 peut constituer
le premier déclencheur. Il faut alors connaître effectivement les données qui
confirment le sommet, la tendance Daily J2 et les autres contrôles continus depuis J1.
Une cassure horaire plus tôt à J2 ne suffit pas : le sommet reste non confirmé.

| Moment | Décision permise pour cette configuration |
| --- | --- |
| J0, J1, puis J2 avant sa clôture officielle | Aucun signal qualifié fondé sur ce sommet encore non confirmé. |
| Après la clôture J2 et disponibilité des données | Confirmer le sommet, vérifier J1/J2, puis tester la dernière bougie horaire de J2. |
| Ouverture J3 | Entrer à cet Open si le signal existe et si les contrôles d'ouverture passent. |
| Fin J10 puis ouverture J11 | Aucune entrée J11, même si une cassure a été observée en fin J10. |

Le bilan Daily J2 conserve son statut ATTENTE_J3 : l'exception autorise la
préparation de l'entrée suivante, sans rendre J2 admissible à une entrée ni
modifier le scanner Daily. À l'ouverture J3, la SMA de référence est celle de
J2 désormais terminée ; les gaps peuvent toujours annuler l'entrée prévue.

Les anciens scanners Daily restent inchangés. Le futur module horaire pourra
analyser des bougies terminées de la journée courante en utilisant les Daily
antérieurs ; il ne doit pas exclure toute cette journée comme le collecteur Daily.

## 5. Ordre des événements et invalidations causales

1. À la clôture de t, intégrer ses High/Low/Close disponibles. Actualiser le
   minimum du repli depuis J1 et vérifier les invalidations avant le signal.
   Si cette clôture termine aussi la séance, intégrer les nouvelles données
   Daily lorsqu'elles deviennent disponibles.
2. Si les filtres sont respectés et que l'instant est autorisé par C (clôture
   J2 comprise), tester le premier `Close[t] > High[t-1]`. Retenir l'identité de
   la configuration et du signal.
3. À l'ouverture attendue suivante, contrôler la séance J3–J10, les nouvelles
   références Daily éventuelles et le seul prix Open déjà observé.
4. Si tous les contrôles passent, enregistrer l'entrée à cet Open. Ne pas lire
   les High/Low/Close finaux de la bougie d'entrée pour accepter ou refuser celle-ci.

Si la clôture de t et l'ouverture suivante partagent un horodatage, cet ordre
logique demeure nécessaire. Une donnée reçue tardivement ne permet pas une
entrée rétroactive à une ouverture déjà passée dans une analyse en temps réel.

Refuser l'entrée si un prix déjà observé, y compris l'Open suivant, implique :

- un High strictement supérieur au sommet Daily ;
- un retracement strictement supérieur à 50 % ;
- un prix strictement inférieur à 96 % de la SMA20 précédente de sa séance.

Les égalités déjà autorisées restent autorisées. Une invalidation au sein de t
reste définitive même si sa clôture remonte ensuite. Une ouverture sous le
niveau horaire franchi ne suffit pas, à elle seule, à annuler le signal : aucune
condition supplémentaire `Open[t+1] > High[t-1]` n'a été demandée.
Une invalidation observée après l'entrée ne supprime pas cette entrée passée ;
son éventuel rôle dans une sortie relève de la future spécification des sorties.

Exemple fictif J2 → J3 : sommet Daily 120, creux 100, plus bas observé 112. À la
clôture J2, le sommet est confirmé et les filtres passent. Le High horaire
précédent vaut 113 ; la dernière bougie de J2 clôture à 114 et déclenche.
L'ouverture J3 à 114,20 permet l'entrée si tous les contrôles passent. Si cette
bougie touche 109 plus tard, ce Low ne peut pas annuler rétroactivement l'entrée.
En revanche, une ouverture directement à 109 dépasse déjà les 50 % de repli
(plancher à 110) et interdit l'entrée avant toute utilisation du Low futur.

## 6. Données manquantes — convention D validée

**Convention D : bloquer les décisions dépendantes d'une lacune jusqu'à
résolution, avec un motif NON_EVALUABLE ; ne pas inventer une invalidation de prix.**

- Comparer les timestamps à la grille attendue du calendrier. Une fermeture
  prévue ou la demi-heure finale convenue ne constitue pas un trou.
- Une bougie attendue absente peut cacher une invalidation OU le premier
  déclencheur. Ne pas utiliser la dernière ligne disponible comme t−1 si ce n'est
  pas le véritable prédécesseur attendu ; ne pas annoncer un premier signal
  ultérieur tant que la séquence nécessaire n'est pas complète.
- Si l'Open suivant manque, aucune entrée ne peut être calculée. Ne pas prendre
  celui d'une bougie plus tardive comme remplacement de `Open[t+1]`.
- Conserver les décisions déjà établies avant le trou. Compléter l'archive peut
  permettre un nouveau calcul historique, clairement distinct d'une décision
  effectivement prise avec les données disponibles en temps réel.
- Refuser doublons, prix non finis/non positifs, OHLC incohérents et timestamps
  sans fuseau déclaré. Aucun remplissage artificiel d'Open, High, Low ou Close.

## 7. Données et future brique

Prévoir ensuite `etape_03_entree_1h.py`, sans réorganisation du projet.
Les archives Daily restent utilisables ; l'horaire exige aussi le vrai Open,
des instants de début/fin avec fuseau, la séance et la durée de chaque intervalle.
La convention USD et les ajustements doivent être identiques aux Daily.
L'import doit distinguer les données fictives et réelles ; l'origine et la
convention d'un CSV fourni ne peuvent pas être garanties par les seuls chiffres.

Pour yfinance, prévoir `interval="1h"`, `ignore_tz=False`, `prepost=False`,
`auto_adjust=False`, `back_adjust=False`, `repair=False`, `rounding=False`,
avec cache et secours CSV. Le code traite les timestamps de marché comme des
débuts de bougies et peut renvoyer une dernière bougie non terminée : la grille
et la complétude doivent donc être contrôlées par le programme.
[Documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html),
[code des horodatages, version 1.7.0](https://github.com/ranaroussi/yfinance/blob/1.7.0/yfinance/utils.py).

Limite à vérifier avant le backtest : la documentation annonce génériquement
60 jours intraday, tandis que la branche horaire du code 1.7.0 prévoit jusqu'à
730 jours pour `period="max"`. Cela ne garantit pas un historique complet ni
une durée d'accès contractuelle. Vérifier la couverture réellement reçue et
les lacunes ; ne pas extrapoler la profondeur d'historique Daily à l'horaire.
[Code concerné](https://github.com/ranaroussi/yfinance/blob/1.7.0/yfinance/scrapers/history.py#L227-L239).

Journal prévu : configuration et sommet Daily, barres signal/référence et leurs
dates de disponibilité, High de référence, Close du signal, ouverture attendue,
prix d'entrée connu, âge J, statut et motif d'annulation ou d'impossibilité.

Futurs tests : égalité/mèche ; premier déclencheur ; référence horaire distincte
du sommet Daily ; signal de clôture J2 puis entrée J3 ; aucun signal qualifié
avant confirmation effective J2 ; statut Daily J2 inchangé ; J3 et J10/J11 ;
invalidation dans la bougie signal ; gap à
l'ouverture et égalités ; High/Low futurs de la bougie d'entrée sans effet sur
l'entrée passée ; tendance Daily du jour encore inconnue ; clôtures simultanées ;
demi-séances, dernière tranche et changements d'heure ; continuité entre séances
selon B ; trous de données sans faux t−1/t+1 ; conservation des décisions passées.

**Conventions validées : A — grille avec dernière tranche raccourcie ; B — continuité
entre séances ; C — signal dès la clôture J2 et entrée J3–J10 ; D — blocage sur
données manquantes. Aucune sortie ni règle de risque supplémentaire n'est ajoutée.**
