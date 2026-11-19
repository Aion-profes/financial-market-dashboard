# Pullback Daily AAPL — SPÉCIFICATION VALIDÉE

Ce document définit les règles de `etape_02_pullback.py`, validées le 14 octobre 2026.
Le choix du creux, la SMA précédente, le maintien continu de la tendance, le
sommet de référence sur 20 séances et la chronologie sont validés :
compter J1/J2 ne prolonge pas la fenêtre J3–J10.
Aucun signal d'achat, déclencheur 1 h, risque, backtest ou interface n'est défini ici.

## 1. Cadre et pivots

- AAPL, séances NASDAQ ordonnées, uniquement bougies Daily terminées. Le scanner
  actuel exclut toute la journée courante à New York, même après clôture ; conserver
  cette convention de collecte. Les dates de confirmation désignent néanmoins
  les clôtures des séances concernées, pas le lendemain du téléchargement.
- À la séance `p`, un sommet exige `High[p] > High[p-2], High[p-1], High[p+1], High[p+2]`.
  Un creux exige les quatre comparaisons strictes inverses sur `Low`.
  Une égalité avec l'un des quatre voisins empêche la confirmation du pivot.
- Stocker deux dates : **apparition** à `p`, **confirmation** à la clôture de `p+2`.
  À une date évaluée `t`, seuls les pivots avec `p+2 <= t` sont connus. Ne jamais
  réécrire un statut passé comme si le pivot avait été connu dès son apparition.
- Les deux séances précédentes et les deux suivantes doivent réellement être
  disponibles : pas de pivot inventé aux extrémités d'un historique.

### Sommet de référence — définition validée

Un sommet de référence doit aussi dépasser STRICTEMENT tous les High des
**20 séances précédant son apparition J0**, de J−20 à J−1 inclus :
`High[J0] > max(High[J−20], ..., High[J−1])`.
J0, J1 et J2 ne font pas partie de cette fenêtre de comparaison. La référence
reste ancrée sur J0 lors de la confirmation J2 ; ne pas décaler les 20 séances.
Sans 20 High antérieurs valides, ce critère est non évaluable.
Une égalité avec le maximum antérieur est refusée. Le sommet n'est exploitable
qu'après la clôture de J2, et la fenêtre admissible commence toujours à J3.

Exemple fictif : maximum antérieur = 119,80. Un High de 119,80 est refusé ;
119,81 respecte le critère de record, sous réserve de la confirmation du pivot.
Les 20 séances sont une hypothèse de travail, sans garantie d'une hausse importante.
Un rebond sous un sommet récent est exclu, même s'il forme un pivot local.

## 2. Hausse de référence — choix validé

Noter `H = High[J0]`, où J0 est la séance d'apparition du sommet.
**À sa confirmation J2, choisir le creux confirmé dont la date
d'apparition est la plus récente STRICTEMENT avant J0**, parmi ceux connus à J2.
Utiliser son `Low` comme `Lref`, puis figer ce creux et H pour cette configuration.
Ce n'est ni le plus bas de tout l'historique, ni un creux apparu après le sommet.
Un creux et un sommet apparus sur la même séance ne forment pas cette hausse.

Un creux apparu à J−1 et confirmé à J1 est ainsi utilisable à J2,
même s'il n'était pas encore confirmé à J0.
Sans creux répondant au choix retenu, ou si `H - Lref <= 0`, signaler une
configuration non évaluable avec son motif ; ne pas inventer une référence.

## 3. Profondeur, fenêtre et invalidations

**Commencer le repli à J1**, en excluant le Low de J0 :
avec une bougie Daily, on ignore s'il a précédé ou suivi le High du sommet.
À la confirmation J2, intégrer les Low de J1 ET J2. À chaque clôture suivante,
mettre à jour `Lmin = min(Low[J1], ..., Low[Jk])`, mèches incluses.
Les deux séances J1/J2 sont déjà comptées depuis le sommet ; aucune séance
supplémentaire n'est ajoutée. J0 ne devient pas J2, et J10 ne devient pas J12.

```text
retracement = (H - Lmin) / (H - Lref)
```

La limite envisagée est `retracement <= 0.50` ; exactement 50 % est accepté.
Un dépassement invalide la configuration, même si les prix remontent ensuite :
le minimum observé reste dans son historique. Aucun arrondi avant comparaison.
Pour les bornes 50 % et 4 %, utiliser les représentations décimales des valeurs
avec `Decimal`, sans epsilon. Classer la profondeur en comparant les montants
avant division ; le ratio converti en float sert à l'export et à l'affichage.

| Moment | Ce qui peut être établi avec les données connues |
| --- | --- |
| J0 et J1 | Aucune configuration issue de ce sommet n'est encore confirmée. |
| Clôture J2 | Confirmation, référence et bilan des Low de J1/J2 ; hors fenêtre admissible. |
| J3 à J10 inclus | Vérification des critères à chaque clôture, sans utilisation de séances futures. |
| Fin de J10 | Sans déclenchement, expiration ; aucune admissibilité à J11. |

Si J1/J2 avaient déjà dépassé une limite, le refus n'est attribué à cette
configuration qu'à sa découverte J2, sans fabriquer de statut à J1.
Tout `High[Jk] > H` depuis J1 invalide définitivement cette configuration.
Après confirmation, un High égal à H ne suffit pas à cette invalidation ;
dans les quatre voisins du pivot, cette égalité empêche déjà sa confirmation.

Pour J10, distinguer le **bilan des critères de la séance J10** et l'**état après
sa clôture**, expiré sans déclenchement. Ce bilan Daily n'autorise aucun signal
1 h rétroactif. Le déclencheur n'existe pas encore : aucune activation n'est simulée.

## 4. Règle SMA20 à 4 % — SMA précédente validée

Comparer le Low de CHAQUE séance à sa propre référence, et non le minimum
cumulé du repli à la SMA du dernier jour.

L'invalidation stricte est `Low[t] < 0.96 * SMA20[t-1]`.
La référence est connue avant la séance ; elle n'utilise pas sa clôture future.

**Règle retenue : SMA précédente, seuil renouvelé chaque
séance et fixe pendant celle-ci ; contrôle Daily après clôture, dès J1 ;
invalidation définitive au premier dépassement.** À J2, vérifier aussi J1 contre
SMA[J0] et J2 contre SMA[J1]. Une baisse exactement égale à 4 % est tolérée.
Exemple fictif : SMA précédente = 100 ; Low = 96, limite respectée ; Low = 95,50,
limite dépassée. Le lendemain, utiliser la nouvelle SMA précédente.
Une SMA indisponible empêche de déclarer ce contrôle satisfait.
Une SMA ou une tendance indisponible signifie **non évaluable**, sans constituer
une invalidation de prix ; ne pas confondre donnée manquante et condition fausse.

## 5. Tendance continue et configuration principale unique — validées

Les quatre conditions Daily doivent rester vraies de J1 à la séance évaluée.
À la découverte J2, vérifier J1/J2. Le premier échec invalide définitivement
cette configuration, même si la tendance redevient admissible ensuite.
Exemple fictif : tendance vraie à J3, fausse à J4, vraie à J5 ; la configuration
reste invalidée à J5. Il n'y a aucune suspension temporaire ni réactivation.
La tendance du jour n'est disponible qu'après clôture : son utilisation par un
futur déclencheur 1 h devra être définie séparément, sans anticiper cette clôture.

Suivre **au maximum une configuration principale** sur AAPL ; conserver les
configurations terminées dans l'historique sans les réactiver. Un nouveau High
supérieur au sommet actif invalide celui-ci à la clôture de sa séance, même si
le nouveau candidat ne devient jamais un pivot confirmé.
Attendre la confirmation J2 du nouveau sommet et tous ses critères avant
d'ouvrir une nouvelle configuration. Ne pas la créer dès le nouveau High.
Avec une durée maximale de 10 séances et le record sur 20 séances, un nouveau
sommet éligible apparu pendant la vie de l'ancien doit le dépasser : l'ancien
est inclus dans ses 20 séances précédentes. Il n'y a donc pas deux configurations
admissibles à départager ni remplacement par un sommet inférieur.

## 6. Trois exemples fictifs — profondeur uniquement

Avec Lref = 100 et H = 120, la hausse de référence vaut 20.

| Plus bas depuis J1 | Calcul | Retracement | Limite de profondeur |
| ---: | --- | ---: | --- |
| 112 | (120 − 112) / 20 | 40 % | Respectée |
| 110 | (120 − 110) / 20 | 50 % | Respectée, égalité admise |
| 109 | (120 − 109) / 20 | 55 % | Dépassée |

Ces nombres inventés ne prouvent ni un pivot confirmé, ni la fenêtre, ni la
tendance, ni le respect d'une règle SMA. Ils ne constituent pas des signaux.

## 7. Implémentation et contrôles

- Le module `etape_02_pullback.py` réutilise les fonctions utiles de
  l'étape 1, sans réorganisation. Conserver code, exercices, archives et venv.
- Le téléchargement actuel reçoit un tableau yfinance mais n'en conserve que
  Close : extraire aussi les vrais High et Low et créer de nouvelles archives
  `Date,High,Low,Close`. Garder USD, ajustement des splits sans dividendes, et
  `auto_adjust=False` ; vérifier la cohérence des trois colonnes fournies.
- L'étape 1 doit continuer à accepter Date/Close. L'étape 2 exigera High/Low ;
  refuser explicitement les anciennes archives incomplètes pour le pullback.
  Ne jamais déduire ou remplir High/Low depuis Close, ni écraser ces archives.
- Vérifier dates uniques, séances complètes, prix finis et positifs,
  `Low <= Close <= High` ; aucune interpolation. Comparaisons non arrondies.
- Prévoir des résultats distinguant apparition/confirmation du sommet et du
  creux, H, Lref, Lmin, âge en séances, retracement, tendance, statut et motif.
- Tests ciblés : pivots inconnus avant la deuxième clôture suivante ; égalités
  sur chaque voisin ; choix du creux ; J1/J2 intégrés sans statut rétroactif ;
  40 %, 50 % et 55 % ; J2/J3/J10/J11 ; record strict sur les 20 séances AVANT J0,
  égalité avec ce record, J−20 inclus/J−21 exclu, historique High insuffisant,
  aucun décalage à J2 ;
  nouveau High strict et égalité, ancienne configuration invalidée même sans
  confirmation du nouveau sommet ; configuration principale unique ; SMA et
  maintien continu sans réactivation ; High/Low manquants ou incohérents ; ajout
  ou modification de séances futures sans changement des statuts déjà produits.

Chronologie retenue : départ du repli à J1, J1/J2 déjà comptés,
fenêtre inchangée J3–J10. La qualité historique de Yahoo reste la limite déjà
décrite dans GUIDE.md, même avec des calculs causaux.

L'ATR reste une piste ultérieure pour comparer l'amplitude de la hausse à la
volatilité. Il tient compte des gaps et n'indique pas la direction des prix
([Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)).
Aucune période, aucun seuil ni filtre ATR n'est ajouté à cette étape.
