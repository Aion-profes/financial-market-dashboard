# Guide détaillé — financial-market-dashboard

Ce guide raconte la construction du projet étape par étape, dans l'ordre où elle a eu lieu, avec les notions Python utiles à chaque étape. Pour une présentation rapide, voir le [README](README.md).

Les étapes 1 à 3 décrivent d'abord un filtre de tendance Daily pour AAPL, puis le pullback et le déclencheur horaire ; les sections suivantes ajoutent les sorties, le tableau de bord et le backtest. Tout sert à l'analyse et à la simulation : **« ADMISSIBLE » n'est pas un signal d'achat**, et aucune connexion à un courtier n'existe.

Le premier programme est `etape_01_tendance.py`. Les tests sont dans les fichiers `test_*.py`. `practice.py` conserve des exercices. Les téléchargements sont archivés dans `donnees/` et les tableaux dans `resultats/` ; ces deux dossiers restent sur ta machine et ne sont pas publiés.

**Les archives citées en exemple** (par exemple `aapl_daily_20261013_190747_061192.csv`) sont celles produites pendant la construction du projet. Elles ne sont pas publiées : chaque téléchargement crée les tiennes dans `donnees/`, avec la date et l'heure dans leur nom. Remplace le nom de fichier par celui de ton archive.

## Préparer et lancer le projet sous Windows

Dans PowerShell, place-toi dans le dossier du projet :

```powershell
Set-Location -LiteralPath "$env:USERPROFILE\Documents\financial-market-dashboard"
```

Un environnement virtuel contient les dépendances propres à ce projet. Le point-virgule du nom du dossier empêche `venv` de créer l'environnement à cet endroit sous Windows. L'environnement dédié est donc installé dans `$env:USERPROFILE\.venvs\financial-market-dashboard`, c'est-à-dire dans ton dossier personnel Windows. `$env:USERPROFILE` désigne ce dossier dans PowerShell ; les commandes ci-dessous fonctionnent donc sur n'importe quel PC. Adapte le chemin du `Set-Location` à l'endroit où se trouve ton dossier.

Ces commandes permettent de recréer l'environnement si nécessaire :

```powershell
py -3.14 -m venv "$env:USERPROFILE\.venvs\financial-market-dashboard"
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" -m pip install -r .\requirements.txt
```

Le symbole `&` demande à PowerShell d'exécuter le programme dont le chemin est entre guillemets. Aucune activation de l'environnement n'est nécessaire avec ces commandes.

Pour commencer sans connexion Internet :

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_01_tendance.py --demo
```

## Source des données : Alpaca, et choix du titre

Depuis le **13 novembre 2026**, les trois étapes téléchargent leurs cours chez **Alpaca Market Data** (offre gratuite), une API officielle, et non plus chez Yahoo. Avant de basculer, les deux sources ont été comparées sur AAPL avec `comparer_sources.py` :

- en Daily, 255 séances identiques au demi-centime près ;
- à l'étape 3, les mêmes décisions ligne par ligne ;
- en horaire, 67 bougies sur 155 différaient de plus d'un centime, et dans les cas vérifiables c'est Yahoo qui se trompait. Exemple : le 30 octobre 2026, le plus bas de la journée est 334,35 dans les deux Daily et dans l'horaire Alpaca, mais 342,90 dans l'horaire Yahoo.

Alpaca demande deux clés personnelles, créées sur le compte « Paper » (simulation). Elles restent dans les variables d'environnement Windows et ne doivent figurer dans aucun fichier du projet :

```powershell
setx APCA_API_KEY_ID "ta_cle"
setx APCA_API_SECRET_KEY "ton_secret"
```

Ferme puis rouvre VS Code après ces deux commandes. Sans clés, le programme s'arrête avec un message qui nomme les variables manquantes.

Trois options sont communes aux étapes 1, 2 et 3 :

| Option | Effet |
| --- | --- |
| `--symbole NVDA` | Choisit le titre : `AAPL` (par défaut), `NVDA` ou `AVGO`. Les règles sont identiques pour les trois. |
| `--source yahoo` | Revient à l'ancienne source, pour contrôler une valeur douteuse. Par défaut : `alpaca`. |
| `--csv ...` | Relit une archive hors ligne, comme avant. |

```powershell
# Pullback Daily de NVDA, données Alpaca.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --symbole NVDA

# Même calcul avec Yahoo, pour comparer.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --symbole NVDA --source yahoo
```

Le réglage `adjustment=split` d'Alpaca correspond à la convention du projet : cours ajustés des splits, non ajustés des dividendes. Les archives portent le titre et la source dans leur nom, par exemple `nvda_alpaca_daily_hlc_…csv`.

Deux particularités d'Alpaca sont gérées par `source_alpaca.py` :

- **Bougies horaires.** Alpaca fournit des barres de 30 minutes ; le programme les assemble deux par deux sur la grille 09:30–10:30 … 15:30–16:00. S'il manque une moitié, aucune bougie n'est fabriquée.
- **Retard de 15 minutes.** L'offre gratuite ne montre pas les 15 dernières minutes ; le programme en retient 16, pour ne pas être refusé si l'horloge du PC avance de quelques secondes. Une bougie horaire encore partielle ne garde donc que son Open, et la bougie Daily du jour n'est lue qu'à partir de 16:16 à New York. Entre-temps, l'étape 3 répond `NON_EVALUABLE` au lieu d'utiliser des prix incomplets.

Les fichiers concernés : `source_alpaca.py` (téléchargement), `comparer_sources.py` (comparaison avec Yahoo), `test_source_alpaca.py` et `test_sources.py` (tests sans réseau). `MISSION_ALPACA.md` et `lancer_mission_alpaca.py` gardent la trace de la vérification initiale.

## Étape 1 — comparer cinq valeurs

Objectif : comprendre le filtre avant d'utiliser des cours. Dans `etape_01_tendance.py`, `tendance_admissible()` reçoit les cinq valeurs suivantes : clôture, SMA20, SMA50, SMA20 cinq séances avant et SMA50 cinq séances avant.

La démonstration utilise uniquement des **chiffres fictifs** :

| Condition | Comparaison | Résultat |
| --- | --- | --- |
| C1 : clôture supérieure à SMA50 | 110 > 100 | `True` |
| C2 : SMA20 supérieure à SMA50 | 105 > 100 | `True` |
| C3 : SMA20 en hausse sur cinq séances | 105 > 102 | `True` |
| C4 : SMA50 en hausse sur cinq séances | 100 > 98 | `True` |

Le verdict global est `True`, car les quatre conditions sont vraies. Une seule condition fausse suffit à obtenir `False`. Le signe `>` est strict : `105 > 105` vaut `False`.

Les notions Python : `def` définit une fonction ; ses paramètres sont les valeurs reçues. `return` renvoie le résultat. Un booléen vaut `True` ou `False`. `and` exige que toutes les comparaisons soient vraies.

## Étape 2 — calculer les moyennes depuis les clôtures

Objectif : remplacer les moyennes saisies à la main par des calculs. La fonction `calculer_tendance()` utilise une liste de clôtures, de la plus ancienne à la plus récente.

Une SMA20 est la somme des 20 dernières clôtures divisée par 20. La SMA50 applique la même règle à 50 clôtures. Le décalage de cinq correspond à **cinq séances enregistrées**, sans compter les week-ends et jours de fermeture.

| Expression Python | Ce qu'elle sélectionne |
| --- | --- |
| `valeurs[-1]` | La dernière clôture |
| `valeurs[-20:]` | Les 20 dernières clôtures |
| `valeurs[-50:]` | Les 50 dernières clôtures |
| `valeurs[-25:-5]` | Les 20 clôtures terminant cinq séances auparavant |
| `valeurs[-55:-5]` | Les 50 clôtures terminant cinq séances auparavant |

Une **tranche** sélectionne une partie de la liste ; sa borne de fin est exclue. Ainsi, `-5` retire les cinq dernières observations. La fonction `mean()`, importée du module `statistics`, calcule la moyenne de la sélection.

La démonstration `--demo` contient 55 clôtures fictives de 100 à 154 :

```text
cloture : 154.0
sma20 : 144.5
sma50 : 129.5
sma20_avant_5 : 139.5
sma50_avant_5 : 124.5
admissible : True
Historique insuffisant : 54 clôtures valides ; au moins 55 sont nécessaires.
```

Il faut 55 clôtures pour calculer la SMA50 d'il y a cinq séances. Les prix manquants, infinis, nuls ou négatifs sont refusés ; aucune valeur n'est inventée.

Le résultat est un **dictionnaire** : chaque nom, par exemple `"sma20"`, est associé à une valeur. Une **exception** signale un problème ; `try` et `except` permettent ici d'afficher le message d'historique insuffisant sans interrompre la démonstration.

## Étape 3 — utiliser les données Daily AAPL

Objectif : alimenter les calculs avec des données de marché. Le téléchargement utilise Alpaca par défaut (voir « Source des données » plus haut), en bougies Daily et sur environ un an d'historique. Les paragraphes ci-dessous qui citent Yahoo décrivent l'ancienne source, toujours disponible avec `--source yahoo`.

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_01_tendance.py
```

La convention retenue est **`Close` en USD, ajustée des splits et non ajustée des dividendes**. Chez Alpaca, c'est le réglage `adjustment=split`. Chez Yahoo, les options `auto_adjust=False`, `back_adjust=False` et `repair=False` sont explicites. On utilise `Close`, jamais un mélange de `Close` et `Adj Close`.

La [documentation de `download`](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) décrit les paramètres ; la date `end` est exclusive. Le [README de yfinance](https://github.com/ranaroussi/yfinance) précise que l'outil est indépendant de Yahoo, destiné à la recherche et à l'éducation, et que l'usage des données Yahoo est personnel. Aucun quota de téléchargement ni accès permanent n'est garanti : un téléchargement peut échouer ou renvoyer un historique incomplet.

La [page historique AAPL de Yahoo](https://finance.yahoo.com/quote/AAPL/history/) permet de consulter la source. La [documentation des réparations](https://ranaroussi.github.io/yfinance/advanced/price_repair.html) décrit des anomalies possibles ; le programme ne modifie pas automatiquement les prix pour les corriger.

Le calendrier NASDAQ de `pandas_market_calendars` sert à refuser les séances manquantes et les dates hors séance ; voir sa [documentation d'utilisation](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html). Cinq observations ne doivent pas masquer une séance absente.

La journée courante **à New York** est toujours exclue, même après la clôture : c'est une règle volontairement prudente pour conserver uniquement des bougies terminées. `--date` fixe une borne incluse, antérieure à cette journée ; si elle tombe un jour fermé, le tableau s'arrête à la dernière séance disponible avant cette date.

Chaque calcul utilise uniquement les clôtures de sa date et des séances précédentes. Cependant, les cours Yahoo téléchargés aujourd'hui peuvent intégrer des corrections ou des splits ultérieurs : cette source n'est pas une archive des données telles qu'elles étaient connues historiquement. Ce point devra être traité avant un backtest.

Un téléchargement réussi est conservé en CSV. Pour réutiliser hors ligne l'archive créée lors de cette session :

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_01_tendance.py --csv .\donnees\aapl_daily_20261013_190747_061192.csv
```

Un CSV externe doit avoir les colonnes `Date,Close`, des dates `AAAA-MM-JJ`, et la même convention de prix. Le séparateur peut être une virgule ou un point-virgule ; utilise un point pour les décimales avec un séparateur virgule. Il faut garantir que le fichier concerne AAPL : l'origine du CSV n'est pas vérifiée. Une colonne facultative `Symbol` est contrôlée si elle existe. Les dates sont triées, les doublons et les trous refusés.

```csv
Date,Close
2026-10-09,123.45
2026-10-12,124.00
```

Cet exemple de format contient **deux prix fictifs**, pas des cours AAPL ; il est insuffisant pour le calcul.

Les notions Python : `import` rend disponible un module. `csv` lit ou écrit des fichiers tabulaires. `argparse` lit les options comme `--csv` et `--date`. Les dépendances de téléchargement sont importées seulement lorsque le programme en a besoin.

## Étape 4 — lire le tableau

Objectif : vérifier les quatre conditions pour chaque date. `construire_tableau()` construit les lignes et `afficher_tableau()` les affiche. Une **boucle** répète le traitement pour chaque séance.

Exemple de **données réelles téléchargées pendant cette session**, avec 255 clôtures jusqu'au 12 octobre 2026 :

| Date | Clôture | SMA20 | SMA50 | SMA20(-5) | SMA50(-5) | C1 | C2 | C3 | C4 | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| 2026-10-12 | 340,97 | 335,78 | 323,03 | 332,54 | 322,41 | VRAI | VRAI | VRAI | VRAI | ADMISSIBLE |

Les arrondis servent uniquement à l'affichage. Les comparaisons utilisent les valeurs complètes. Le tableau conserve également les premières séances : avant 55 clôtures, le verdict est `INSUFFISANT`. En Python, `None` représente une valeur indisponible, différente de `False` ; le CSV l'écrit dans une cellule vide.

Le programme affiche les dix dernières lignes par défaut et exporte tout le tableau dans `resultats/`. Le tableau réel produit pendant cette session contenait 255 lignes. Les noms de sortie contiennent une date et une heure ; un fichier existant n'est jamais écrasé.

```powershell
# Afficher toutes les lignes.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_01_tendance.py --csv .\donnees\aapl_daily_20261013_190747_061192.csv --derniers 0

# Évaluer une date passée avec cette même archive.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_01_tendance.py --csv .\donnees\aapl_daily_20261013_190747_061192.csv --date 2026-10-09
```

Avec cette archive, le 9 octobre 2026 est refusé : C4 est fausse. Les lignes du 12 octobre sont exclues de cette évaluation.

## Vérifier et s'exercer

Les tests couvrent les quatre conditions respectées, chaque refus, chaque égalité, 54 clôtures insuffisantes et le calcul exact sur 55 clôtures. D'autres vérifications couvrent notamment les CSV, les séances manquantes, les dates exclues et l'absence d'utilisation des clôtures futures.

Validation effectuée : **23 tests réussis** (`OK`, 1,424 seconde). La vérification `pip check` n'a trouvé aucune incompatibilité de dépendances. Le téléchargement réel, la lecture CSV et l'évaluation du 9 octobre ont fonctionné. Une panne de téléchargement simulée a affiché le recours à `--csv`, sans utiliser de prix fictifs à la place.

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" -m unittest discover -v
```

Exercice : dans `demonstration_cinq_valeurs()`, remplace `sma20_avant_5 = 102.0` par `sma20_avant_5 = 105.0`. Prédis C3 et le verdict, puis relance `--demo`. Tu dois obtenir `False` pour C3 et pour la tendance admissible, car une égalité ne suffit pas. Rétablis ensuite `102.0`.

Le filtre de tendance constitue maintenant la première partie du playbook. La deuxième partie ajoute le pullback Daily selon les règles validées ci-dessous.

## Étape 2 du playbook : pullback Daily

Objectif : détecter un repli admissible après une hausse, sans produire de signal d'achat. Les règles ont été validées le **14 octobre 2026** dans [SPEC_PULLBACK.md](SPEC_PULLBACK.md). Le nouveau programme est `etape_02_pullback.py` ; il réutilise les calculs et les contrôles du module de tendance, qui reste inchangé. Aucune dépendance supplémentaire n'est nécessaire.

Un **pivot sommet** a un High strictement supérieur aux High des deux séances précédentes et des deux suivantes ; un pivot creux applique les comparaisons inverses aux Low. L'apparition du sommet est J0 ; sa confirmation n'est connue qu'après la clôture de J2. Le tableau conserve séparément `date_sommet` et `date_confirmation_sommet`, ainsi que les dates d'apparition et de confirmation du creux.

Les nouvelles fonctions relient les règles aux notions Python :

| Fonction | Rôle et notion à comprendre |
| --- | --- |
| `est_pivot()` | Renvoie `None` si un voisin requis manque, notamment avant J2 ; sinon `True` ou `False`. Inconnu ne signifie pas refusé. |
| `est_sommet_reference()` | Exige aussi un record strict sur les **20 High précédant J0**, sans inclure J0, J1 ou J2. La fenêtre reste ancrée sur J0. |
| `calculer_retracement()` | Renvoie un ratio : `(sommet - plus_bas) / (sommet - creux_reference)`. `0.40` représente 40 %. |
| `scanner_pullbacks()` | Parcourt les bougies dans une boucle chronologique ; chaque ligne utilise uniquement ce qui est connu à sa date. |

À la confirmation J2, la hausse de référence associe le sommet au dernier creux confirmé dont l'apparition précède J0. Ces deux prix sont ensuite figés. Sans référence exploitable, le résultat est `NON_EVALUABLE` avec son motif.

Le plus bas du repli est `min(Low[J1], ..., Low[t])` : `min()` sélectionne la plus petite valeur, mèches incluses. Le Low de J0 est exclu, car une bougie Daily ne révèle pas s'il est survenu avant ou après son High. Un retracement **exactement égal à 50 %** est accepté ; au-delà, la configuration est invalidée définitivement.

Les contrôles des limites utilisent `Decimal`, un type numérique fourni par Python qui conserve l'écriture décimale des valeurs. Cela évite qu'une petite erreur de représentation des `float` transforme une égalité en dépassement : sommet 100,01, creux 90,03 et Low 95,02 donnent bien 50 %. Aucun arrondi ni marge de tolérance n'est ajouté aux règles ; les arrondis du tableau servent uniquement à sa lecture.

De J1 à la séance évaluée, chaque Low doit vérifier `Low[t] >= 0.96 * SMA20[t-1]`. La référence est la moyenne connue avant cette séance, renouvelée chaque jour : exactement 4 % sous celle-ci est toléré. Les quatre conditions de tendance doivent aussi rester vraies continuellement dès J1. Le premier échec, ou un nouveau High strictement supérieur au sommet, invalide définitivement cette configuration. À J2, ces contrôles incluent déjà J1 et J2 ; les statuts passés ne sont pas réécrits.

Les branches `if` et `elif` choisissent le statut selon les contrôles : invalidation, données insuffisantes, attente de J3, puis admissibilité. Le scanner suit au maximum une configuration principale ; une configuration terminée n'est pas réactivée.

La démonstration comporte **72 bougies fictives**, avec des dates illustratives en semaine, sans reproduire le calendrier NASDAQ ni des cours AAPL. Avec `PLUS_BAS_DEMO = 112.0`, le creux vaut 100, le sommet 120 et le plus bas du repli 112 : `(120 - 112) / (120 - 100) = 40 %`.

| Séance depuis le sommet | `statut` | `statut_apres_cloture` |
| --- | --- | --- |
| J0 et J1 | `AUCUNE_CONFIGURATION` | `AUCUNE_CONFIGURATION` |
| J2 | `ATTENTE_J3` | `ATTENTE_J3` |
| J3 à J9 | `ADMISSIBLE` | `ADMISSIBLE` |
| J10 | `ADMISSIBLE` | `EXPIREE` |
| J11 | `AUCUNE_CONFIGURATION` | `AUCUNE_CONFIGURATION` |

J10 reste le dernier bilan Daily admissible, mais la configuration expire après sa clôture. Sa confirmation à J2 ne prolonge jamais la fenêtre J3–J10. Aucun déclenchement n'est simulé.

La conclusion distingue maintenant **l'état de la dernière séance** et **le dernier bilan de la dernière configuration suivie**, avec son motif, son retracement et son nombre de séances admissibles. Dans l'exercice, 109 donne 55 % : invalidation à J2 et aucune séance admissible. Avec 110 (50 %) ou 112 (40 %), la configuration est admissible pendant huit séances, puis expire après J10. À J11, les trois scénarios affichent pourtant `AUCUNE_CONFIGURATION` : ce même état final correspond à des parcours différents. Le résumé utilise tout l'historique, même avec `--derniers 1`.

Le CSV de cette étape exige **`Date,High,Low,Close`** et `Low <= Close <= High`. Les High, Low et Close doivent tous suivre la convention de prix de l'étape 1. L'ancien CSV `Date,Close` reste utilisable pour la tendance, mais est refusé pour le pullback : aucun High ou Low n'est inventé. En mode AAPL, le calendrier NASDAQ vérifie les séances ; la journée courante à New York reste exclue. L'origine d'un CSV fourni n'est pas vérifiée.

Comme pour le tableau de tendance, il faut au moins 55 bougies valides pour lancer le scanner. Les contrôles des premières dates peuvent rester inconnus : une tendance indisponible à J1 ne devient pas rétroactivement connue à J2.

Depuis le même dossier PowerShell, avec l'environnement déjà installé :

```powershell
# Comprendre les statuts avec les données fictives, de J0 à J11.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --demo --derniers 12

# Télécharger les bougies Daily AAPL terminées.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py

# Relire hors ligne l'archive réelle créée le 14 octobre 2026.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --csv .\donnees\aapl_daily_hlc_20261014_113044_149277.csv

# Évaluer une date passée ; les bougies postérieures sont exclues.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --csv .\donnees\aapl_daily_hlc_20261014_113044_149277.csv --date 2026-10-09

# Afficher toutes les lignes et vérifier l'ensemble des tests.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_02_pullback.py --csv .\donnees\aapl_daily_hlc_20261014_113044_149277.csv --derniers 0
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" -m unittest discover -v
```

Le téléchargement réel a fourni **255 bougies jusqu'au 13 octobre 2026**. Sa dernière ligne indique `AUCUNE_CONFIGURATION` : aucune configuration principale active à cette date. Le tableau complet, écrit dans `resultats/`, conserve les bilans précédents, leurs motifs et les deux états de clôture. Les limites Yahoo documentées à l'étape 1 s'appliquent aussi ici ; une panne propose le recours au CSV.

Exemple historique issu de ce même téléchargement : sommet du 22 septembre 2026 à 345,34, confirmé le 24 septembre, creux de référence à 309,90. Le 29 septembre, le minimum du repli à 328,70 donne 46,95 % et le bilan Daily est admissible. Le 1er octobre, ce minimum descend à 325,81 : 55,11 %, donc invalidation définitive. Il s'agit de bilans après clôture, sans achat simulé.

Validation effectuée : **74 tests réussis** (`OK`, 1,289 seconde), soit 23 tests existants, 29 tests du cœur du pullback et 22 tests de données. Ils vérifient notamment la confirmation causale, les bornes 50 % et 4 % y compris avec des prix décimaux, les invalidations permanentes, la fenêtre J3–J10 et le refus des CSV sans High/Low.

Exercice : dans `etape_02_pullback.py`, remplace `PLUS_BAS_DEMO = 112.0` par `110.0`, puis relance `--demo --derniers 12` : le retracement de 50 % est accepté. Essaie ensuite `109.0` : les 55 % rendent la configuration `INVALIDE` dès sa découverte J2. Rétablis enfin `112.0`.

Le pullback Daily reste un filtre d'analyse. La troisième partie ajoute le déclencheur en une heure.

## Étape 3 du playbook : entrée simulée en 1 h

Objectif : repérer le premier déclencheur horaire d'une configuration Daily valide, puis simuler l'entrée à l'ouverture suivante. Les règles ont été validées le **6 novembre 2026** dans [SPEC_ENTREE_1H.md](SPEC_ENTREE_1H.md). Le programme est `etape_03_entree_1h.py` ; il réutilise les étapes 1 et 2 sans les modifier. **Une entrée simulée n'est pas un ordre** : aucune sortie, aucun frais et aucune taille de position ne sont encore définis.

Le déclencheur est une seule comparaison stricte : `Close_1h[t] > High_1h[t-1]`. La clôture de la bougie horaire terminée doit dépasser le plus haut de la bougie précédente. Une égalité ne suffit pas, une simple mèche non plus. L'entrée est simulée au prix `Open_1h[t+1]`, l'ouverture de la bougie suivante.

| Fonction | Rôle |
| --- | --- |
| `declencheur_horaire()` | Compare deux prix ; renvoie `None` si l'un manque, sinon `True` ou `False`. |
| `construire_grille()` | Liste les créneaux attendus d'après le calendrier NASDAQ : 09:30–10:30 … 15:30–16:00. La dernière tranche dure 30 minutes. |
| `normaliser_horaires()` | Refuse doublons, bougies hors grille et prix incohérents ; masque les prix pas encore connus à l'instant évalué. |
| `scanner_entrees()` | Rejoue les événements dans l'ordre du temps et écrit une ligne de journal par ouverture et par clôture. |

Trois informations restent séparées dans le journal : le **statut Daily** (colonne `statut_daily`, issu de l'étape 2), le **signal en attente** (colonnes `signal_*`) et la **décision** (colonne `statut`).

| Décision | Signification |
| --- | --- |
| `AUCUNE_CONFIGURATION` | Aucun sommet de référence confirmé. |
| `ATTENTE_J3` | Sommet confirmé, mais entrée interdite avant J3. |
| `ATTENTE_SIGNAL` / `PAS_DE_SIGNAL` | Configuration valide, pas encore de cassure horaire. |
| `SIGNAL` puis `ATTENTE_OUVERTURE` | Première cassure retenue ; l'entrée est prévue à l'ouverture suivante. |
| `ENTREE_ACCEPTEE` / `ENTREE_ANNULEE` | Résultat des contrôles faits avec le seul prix d'ouverture. |
| `DEJA_ENTREE` | Une entrée existe déjà ; aucune seconde entrée sur cette configuration. |
| `SANS_REARMEMENT` | La tentative unique a échoué ou a été manquée ; aucun second signal sur cette configuration. |
| `INVALIDE` / `EXPIREE` | Configuration terminée : règle de prix dépassée, ou ouverture après J10. |
| `NON_EVALUABLE` | Une donnée indispensable manque ; aucune décision n'est inventée. |

Cas particulier validé : après la clôture de J2, le sommet est confirmé. La dernière bougie horaire de J2 peut donc produire un signal pour une entrée à l'ouverture de J3, alors que le statut Daily de J2 reste `ATTENTE_J3`. À l'inverse, un signal en fin de J10 ne permet jamais d'entrer à J11.

À l'ouverture d'entrée, seul l'Open de la nouvelle bougie est connu. Ses High, Low et Close futurs ne peuvent ni accepter ni annuler l'entrée. Un gap à l'ouverture peut l'annuler : avec un sommet à 120 et un creux à 100, une ouverture à 109 dépasse déjà les 50 % de repli.

```powershell
# Comparaisons fictives, puis scénario J2 -> J3 avec et sans gap.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_03_entree_1h.py --demo

# Télécharger les Daily et les bougies 1 h AAPL, sur 30 jours par défaut.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_03_entree_1h.py

# Rejouer hors ligne les deux archives du 13 novembre 2026, sans rien voir après l'instant choisi.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_03_entree_1h.py --csv-daily .\donnees\aapl_entree_daily_20261113_150143_329817.csv --csv-horaire .\donnees\aapl_1h_20261113_150143_329817.csv --instant 2026-11-12T16:00:00-05:00
```

Les deux options `--csv-daily` et `--csv-horaire` vont ensemble. Le CSV horaire exige `Datetime,Open,High,Low,Close`, avec un fuseau dans chaque horodatage, par exemple `2026-11-12T09:30:00-05:00`. Contrairement aux étapes 1 et 2, ce module lit les bougies horaires **terminées** de la journée en cours.

Le premier téléchargement réel du 13 novembre 2026, encore fait chez Yahoo, a fourni 155 bougies horaires. Rejoué le même jour avec les données Alpaca, le journal donne les mêmes décisions. Ce journal réel contenait 312 lignes, un signal et une entrée simulée : sommet du 13 octobre confirmé le 15 ; le 16 octobre (J3), la bougie 09:30–10:30 clôture à 344,30 au-dessus du High précédent 343,05 ; entrée simulée à l'ouverture de 10:30, à 344,285 (un demi-centime : c'est le prix de la première transaction du créneau). La configuration du 5 novembre est, elle, invalidée dès J2 : le Low du 6 novembre (338,30) passe sous la limite des 50 %, située à 340,36.

Validation effectuée le 13 novembre 2026 : **168 tests réussis** : 74 pour les étapes 1 et 2, 60 pour l'étape 3, 21 pour la source Alpaca et 13 pour la bascule et le choix du titre. Avec l'étape 4 et le tableau de bord ci-dessous, le total est de **363 tests** au 19 novembre 2026. Ces tests vérifient le programme ; ils ne disent rien de la rentabilité de la règle.

Exercice : lance `--demo` et repère les deux scénarios. Dans le premier, l'ouverture J3 à 114,20 est acceptée. Dans le second, l'ouverture à 109 est annulée. Calcule la limite : `120 - 0.50 * (120 - 100) = 110`. Une ouverture à 110 serait-elle acceptée ? Oui : exactement 50 % est toléré.

## Étape 4 du playbook : sorties et risque

Objectif : décider ce que devient une entrée acceptée par l'étape 3 — où placer le stop, quel objectif viser, combien acheter, et quand sortir. Les règles ont été validées le **15 novembre 2026** dans [SPEC_SORTIES_RISQUE.md](SPEC_SORTIES_RISQUE.md) ; elles remplacent les anciens seuils fixes de −6,5 % et +15 %. Ce sont des **hypothèses de simulation**, pas des valeurs optimales. Le programme est `etape_04_sorties_risque.py` ; aucun ordre réel n'est passé.

Les étapes 1 à 3 gardent leurs règles. Seul ajout : le journal horaire de l'étape 3 contient maintenant une colonne `plus_bas_repli`, que le stop utilise.

| Règle | Calcul |
| --- | --- |
| Stop | Plus bas du pullback à la clôture du signal − 0,25 × ATR14, arrondi vers le bas au centime |
| Objectif | Entrée + 2 × (entrée − stop), arrondi vers le haut au centime |
| Durée maximale | Sortie à la clôture officielle de la dixième séance de détention (D10) |
| Taille | La plus grande quantité dont le risque prévu, coûts compris, ne dépasse pas 0,5 % de l'equity |
| Plafonds | 1 % de risque pour toutes les positions ouvertes ; jamais plus de 100 % investi ; une position par titre |

L'**ATR14** (Average True Range) mesure l'amplitude moyenne d'une séance sur 14 jours, gaps compris. Il sert à placer le stop un peu sous le plus bas, à une distance qui dépend de la volatilité du moment. L'**equity** est la valeur du compte : liquidités plus positions ouvertes.

Exemple fictif, sans coûts, avec 1 USD = 1 EUR : plus bas 97, ATR14 de 4, entrée à 100.

```text
stop      = 97 − 0,25 × 4 = 96
risque    = 100 − 96      = 4 par action
objectif  = 100 + 2 × 4   = 108
budget    = 0,5 % de 1 000 EUR = 5 EUR
quantité  = 5 / 4 = 1,25 action   (1 action si les fractions ne sont pas disponibles)
```

Deux horloges ne doivent pas être confondues. **J3–J10** compte les séances depuis le sommet : c'est la fenêtre où l'entrée est permise. **D1–D10** compte les séances depuis l'achat : c'est la durée de détention. Une position ouverte à J10 peut donc durer jusqu'à J19.

Pendant la détention, chaque bougie horaire terminée est examinée dans cet ordre :

1. à l'ouverture : un gap sous le stop fait sortir au prix d'ouverture (`STOP_GAP`), jamais au niveau du stop ; un gap au-dessus de l'objectif fait sortir à l'objectif (`CIBLE_GAP`) ;
2. pendant la bougie : un Low au stop ou en dessous donne `STOP`, un High à l'objectif ou au-dessus donne `CIBLE` ;
3. si les deux sont touchés dans la même bougie, l'ordre réel est inconnu : la position est marquée `AMBIGU_INTRABAR` et le stop est retenu, par prudence ;
4. à la fin de D10 : `DUREE_MAX_D10`.

Une invalidation du signal après l'achat (par exemple un nouveau plus haut au-dessus du sommet) **n'est pas une sortie**. Une bougie manquante pendant la détention rend la position `NON_EVALUABLE` : on ne suppose pas que le stop a tenu. Une position sans sortie à la fin des données reste `OUVERTE`.

Une entrée acceptée par l'étape 3 ne donne pas toujours une position. Elle est refusée si l'ouverture est au niveau du stop ou en dessous (`ENTREE_SOUS_STOP`), si une position est déjà ouverte sur le titre, ou si même la plus petite quantité dépasse le budget (`PAS_DE_POSITION_TAILLE_INSUFFISANTE`). Le risque n'est jamais relevé pour rendre un achat possible.

| Fonction | Rôle et notion à comprendre |
| --- | --- |
| `calculer_atr()` | Parcourt les séances avec une boucle `for` ; renvoie `None` tant qu'il manque des séances. |
| `calculer_stop()`, `calculer_cible()` | Utilisent `Decimal` pour arrondir au centime sans erreur : en `float`, 90,07 − 0,01 donne 90,0599999… |
| `calculer_quantite()` | Cherche la plus grande quantité valide par **dichotomie** : on coupe l'intervalle en deux à chaque essai. |
| `regler_achat()`, `regler_vente()` | Mettent à jour deux soldes, EUR et USD, rangés dans un dictionnaire ; ne convertissent que ce qui manque. |
| `simuler_sortie()` | Avance bougie par bougie et s'arrête (`return`) au premier événement. |
| `simuler_portefeuille()` | Enchaîne les positions dans l'ordre du temps, tient les deux soldes et le journal des conversions. |

### Valoriser n'est pas convertir

Les cours sont en USD, alors que le capital est compté en EUR. Deux opérations différentes en découlent, et le programme les sépare depuis le 16 novembre 2026 :

- **valoriser** : traduire en EUR ce que le compte contient, pour savoir ce qu'il vaut. Aucun argent ne bouge, cela ne coûte rien ;
- **convertir** : échanger réellement des EUR contre des USD. Cela a un taux d'exécution et un coût.

Le compte simulé tient donc **deux soldes**, un en EUR et un en USD. Un achat utilise d'abord les USD disponibles ; seul ce qui manque est converti. Le produit d'une vente reste en USD, sauf si tu choisis le scénario « chaque vente est reconvertie en EUR ».

Exemple fictif avec 1 USD = 1 EUR, une action à 100 USD et une conversion à 2 USD minimum :

```text
1 000 EUR et 0 USD   -> 100 USD convertis, coût de change 2,00 EUR
500 EUR et 500 USD   -> aucune conversion, coût de change 0,00 EUR
```

La valorisation utilise le taux de référence de la Banque centrale européenne (`source_bce.py`), un par jour ouvré. La BCE écrit « 1 EUR = x USD » : pour passer de USD en EUR, on **divise** par x. Elle annonce une publication « vers 16:00 » sans archiver l'heure réelle ; par prudence, le taux d'un jour n'est utilisé qu'à partir de **18:00 à Francfort**, soit midi à New York. Avant, on garde celui de la veille. C'est un taux d'information, pas un taux garanti chez un courtier.

Le résultat d'une position est séparé en trois parts : le **résultat de prix** (le mouvement du cours), l'**effet de change** (la position en USD a changé de valeur en EUR) et les **coûts simulés**. Leur somme s'appelle **« résultat brut théorique »** quand aucun coût n'est simulé, et **« résultat après coûts simulés »** sinon. Le mot « net » n'est pas employé : aucune hypothèse n'est confirmée pour ton compte. Les USD gardés entre deux positions changent aussi de valeur en EUR : cet effet est suivi à part, il n'est ni une conversion ni un coût.

### Configuration : deux scénarios de coûts, côte à côte

Le compte simulé est un **compte au comptant** : il ne peut ni emprunter ni passer en négatif. Il détient des EUR, utilise les fractions d'action et la conversion automatique, et garde les USD d'une vente. Le barème de commissions, lui, est inconnu : « Fixed » ou « Tiered ». Le programme ne choisit donc pas. Il calcule deux configurations nommées, avec les mêmes règles et les mêmes données :

| Configuration | Commission d'un ordre d'environ 300 USD |
| --- | --- |
| `IBKR_CASH_AUTO_FRACTIONS_FIXED` | 1,00 USD (0,005 USD par action, minimum 1 USD, plafond 1 %) |
| `IBKR_CASH_AUTO_FRACTIONS_TIERED` | 0,35 USD, plus moins d'un centime de frais externes |
| `THEORIQUE_SANS_COUTS` | aucune : le résultat brut théorique de la stratégie |

Les quantités peuvent différer d'un scénario à l'autre, car les coûts entrent dans le dimensionnement. Ce sont des **scénarios de coûts simulés**, pas les résultats nets d'un compte.

Le capital de l'expérience (1 000 EUR, 0 USD) et la liste des scénarios sont lus dans un fichier de configuration, au format TOML : du texte de la forme `clé = valeur`. `configuration_exemple.toml` est publié avec le projet et ne contient aucune donnée personnelle. Pour décrire ton propre compte, copie-le sous le nom `configuration_locale.toml` : ce second fichier reste sur ta machine, `.gitignore` l'exclut de la publication. N'y écris ni identifiant, ni relevé, ni solde réel.

### Liquidités d'un compte au comptant

Sur un compte au comptant, le produit d'une vente n'est pas tout de suite utilisable : il faut attendre le **règlement**, le jour ouvré suivant pour une action américaine. Le programme distingue donc :

- le **solde comptable** : tout ce que le compte contient, y compris ce qui n'est pas encore réglé ;
- les fonds **en attente de règlement** ;
- les fonds **disponibles pour un achat** : le solde comptable moins ce qui attend.

Exemple fictif : une vente à 11:30 rapporte 135 USD. À 12:30 le même jour, ces 135 USD figurent au solde comptable mais ne sont pas disponibles : un nouvel achat est payé par une conversion d'EUR. Le lendemain à l'ouverture, ils paient l'achat sans conversion. Un week-end ou un jour férié repousse la date d'autant. Si les fonds disponibles ne paient pas même la plus petite quantité, l'entrée est refusée avec le motif `FONDS_DISPONIBLES_INSUFFISANTS`.

L'heure exacte à laquelle le courtier considère les fonds comme réglés n'est pas documentée : la convention retenue (« à l'ouverture du jour de règlement suivant ») porte un nom, `j1_prudent`, et une variante plus sévère, `j2_defavorable`, mesure la sensibilité à ce choix.

### Lancer le programme

```powershell
# Exemples fictifs, sans réseau.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_04_sorties_risque.py --demo

# AAPL, 45 derniers jours : les scénarios du fichier de configuration, l'un après l'autre.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_04_sorties_risque.py

# Les trois titres dans un même portefeuille, mêmes scénarios.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_04_sorties_risque.py --symbole AAPL --symbole NVDA --symbole AVGO

# Une seule configuration nommée, ici le résultat brut théorique.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_04_sorties_risque.py --configuration THEORIQUE_SANS_COUTS

# Simulation personnalisée : chaque hypothèse au choix.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_04_sorties_risque.py --fractions --commissions ibkr_fixe --conversion ibkr_manuelle --change retour_eur --reglement j2_defavorable
```

Les configurations nommées suivent un **scénario d'exécution** : `--execution principal` (par défaut : 2 points de base de glissement, règlement au délai en vigueur) ou `--execution defavorable` (10 points de base, un jour de règlement de plus). Un point de base vaut 0,01 % du prix. Le glissement est toujours défavorable : un achat au marché est payé un peu plus cher, une vente au marché rapporte un peu moins ; l'objectif, ordre à cours limité, n'est jamais vendu sous sa limite.

Options d'une simulation personnalisée : `--commissions`, `--conversion`, `--change`, `--reglement`, `--fractions`, `--glissement` (USD par action) et `--glissement-bps` (points de base du prix). À 0, le résultat porte la mention « hypothèse de glissement nul ».

Pour chaque scénario, le programme écrit deux journaux dans `resultats/` : celui des positions et celui des conversions réellement simulées.

### Inventaire des données

`inventaire_donnees.py` compte les bougies disponibles et les compare au calendrier NASDAQ. Il ne calcule ni signal ni performance : il sert à choisir des périodes de test d'après les données, pas d'après les cours.

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\inventaire_donnees.py
```

Résultat du 16 novembre 2026 : 2 733 séances Daily du 04/01/2016 au 13/11/2026 pour chacun des trois titres, sans aucune séance manquante ; bougies horaires complètes sauf le 22/02/2016 ; quatre divisions d'actions repérées (la dernière le 15/07/2024). Le protocole de backtest qui en découle est dans la spécification, section 15.

### Historique long et backtest

Une **division d'actions** (par exemple 10 actions nouvelles pour 1 ancienne) divise le cours par dix du jour au lendemain, sans gain ni perte. Pour qu'elle ne crée pas de faux signal, `historique.py` télécharge les cours **bruts** et les rend continus lui-même, avec le rapport exact de chaque division : les cours « ajustés » de la source sont arrondis, ce qui suffit à fausser une comparaison. Chaque position est ensuite calculée en cours réels de sa date d'entrée, pour que le pas de prix, le nombre d'actions et les commissions soient ceux de l'époque.

```powershell
# Télécharger une fois les cours bruts et figer l'archive (déjà fait le 16 novembre 2026).
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\historique.py

# Relire l'archive sans réseau : empreintes, couverture, bougies nettoyées.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\historique.py --verifier

# Mesurer la V1 sur la période de développement, dans les cinq simulations du protocole.
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\backtest.py --periode developpement
```

L'archive est **figée** : un manifeste garde l'empreinte de chaque fichier, une archive modifiée est refusée, et elle ne se réécrit pas. Les périodes sont inscrites dans `historique.PERIODES` : développement du 01/04/2016 au 28/06/2024, validation du 01/08/2024 au 31/08/2026. La validation ne se lit qu'une fois ; `backtest.py` exige pour elle l'option `--ouvrir-la-validation`. Aucun de ces programmes ne cherche de paramètres.

Voici l'effet des hypothèses sur la seule position réelle observée (les deux lignes « Fractions, automatique, conservés » sont les deux scénarios de référence ; les frais externes de « Tiered », ajoutés depuis, ramènent sa quantité à 1,0966) : AAPL, entrée du 16/10/2026 à 344,285 $, stop 339,93 $, objectif 353,00 $, sortie sur un gap à 339,86 $ le 20/10. Le résultat de prix vaut −1,02 fois le risque initial dans tous les cas ; seules la quantité et les coûts changent.

| Quantités | Commissions | Conversion | USD après la vente | Quantité | Coûts estimés au stop | Résultat après coûts simulés |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Entières | aucune | sans coût | conservés | 1 | 0,00 EUR | −4,41 EUR (brut théorique) |
| Entières | « Fixed » | automatique | conservés | 0 | — | refusée : 1 action risquerait 5,76 EUR |
| Fractions | « Fixed » | automatique | conservés | 0,8083 | 1,86 EUR | −5,42 EUR |
| Fractions | « Fixed » | automatique | reconvertis | 0,7903 | 1,93 EUR | −5,41 EUR |
| Fractions | « Fixed » | manuelle | conservés | 0,3683 | 3,57 EUR | −5,19 EUR |
| Fractions | « Fixed » | manuelle | reconvertis | 0,1432 | 4,44 EUR | −5,07 EUR |
| Fractions | « Tiered » | automatique | conservés | 1,0999 | 0,73 EUR | −5,57 EUR |
| Fractions | « Tiered » | automatique | reconvertis | 1,0753 | 0,82 EUR | −5,56 EUR |

Avec 1 000 EUR et 5 EUR de budget par position, les coûts consomment entre 15 % et 89 % du risque autorisé. Garder les USD évite une conversion sur deux : avec la conversion manuelle, la quantité passe de 0,14 à 0,37 action. **Une seule position ne mesure aucune performance** : ce tableau montre le poids des hypothèses, rien de plus.

### Résultat théorique, pas exécution garantie

La simulation suppose chaque événement exécuté exactement au prix de la règle : l'ouverture horaire pour l'entrée, le niveau du stop, le niveau de l'objectif, le cours de clôture officiel pour D10. Un ordre réel n'obtient pas forcément ces prix. En particulier, sortir au cours de clôture officiel demande un ordre « à la clôture », qu'aucune page officielle lue ne confirme pour les fractions d'action chez Interactive Brokers. La sortie à la clôture de D10 reste donc une **convention de simulation**. Le détail est dans la spécification, section 9.

Ce qui n'est pas fait, volontairement : aucun rejeu sur plusieurs mois ou années (les périodes d'évaluation doivent être fixées avant de regarder les résultats ; un protocole avec des dates exactes est proposé dans la spécification, section 15) et aucun filtre sur les publications de résultats d'entreprise.

Validation effectuée le 16 novembre 2026 : 111 tests pour cette étape, 12 pour les taux de change, 4 pour la configuration, 12 pour l'historique long et 9 pour les mesures du backtest, sans réseau. Ils couvrent l'ATR, les arrondis (dont l'entrée réelle à 344,285), les frais minimaux et le plancher des fractions, les budgets, les deux soldes et les conversions, l'absence de double comptage des frais de change, le règlement des ventes (même jour, lendemain, week-end, jours fériés), le refus d'une entrée non finançable, les gaps, le double contact stop/objectif, D10 un jour de clôture anticipée, les données manquantes et l'absence d'utilisation du futur.

Exercice : lance `--demo` et retrouve les nombres du scénario à la main. Le plus bas est 112 et l'ATR14 vaut 2,65. Calcule le stop (`112 − 0,25 × 2,65 = 111,3375`, arrondi vers le bas : 111,33), le risque par action (`114,20 − 111,33 = 2,87`) et l'objectif (`114,20 + 2 × 2,87 = 119,94`). Avec 5 EUR de budget, combien d'actions en fractions ? `5 / 2,87 = 1,7421`.

## État du jour et tableau de bord

Objectif : lire d'un coup d'œil, pour AAPL, NVDA et AVGO, si les conditions d'entrée du playbook sont remplies **maintenant**, et ce que deviendrait la position. Aucune règle n'est ajoutée : ces fichiers lancent les étapes 1 à 4 sur les cours Alpaca les plus récents et présentent le résultat. « Conditions remplies » décrit les règles du playbook ; **ce n'est pas un conseil d'achat**.

| Fichier | Rôle |
| --- | --- |
| `etat_du_jour.py` | Télécharge, lance les trois étapes et résume chaque titre : un verdict, une phrase, une liste de conditions. |
| `graphiques.py` | Dessine le graphique Daily et le graphique horaire à partir de ce résumé. |
| `tableau_de_bord.py` | La page elle-même (bibliothèque Streamlit) : tuiles, conditions, niveaux, graphiques, tableaux. |
| `ouvrir_tableau_de_bord.bat` | Lanceur : un double-clic ouvre la page dans le navigateur. |
| `.streamlit/config.toml` | Couleurs claires et sombres ; la page n'est visible que depuis ce PC. |

Pour ouvrir la page, double-clique sur `ouvrir_tableau_de_bord.bat` dans l'explorateur de fichiers. Une fenêtre noire démarre le programme, puis le navigateur s'ouvre sur `http://127.0.0.1:8510`. Fermer la fenêtre noire arrête la page. Le résumé existe aussi sans navigateur :

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etat_du_jour.py
```

Deux bibliothèques ont été ajoutées à `requirements.txt` : `streamlit` (la page) et `plotly` (les graphiques). Pour recréer l'environnement, relance la commande `pip install -r .\requirements.txt` du début de ce document.

Chaque titre reçoit une étiquette parmi cinq :

| Étiquette | Signification |
| --- | --- |
| Conditions remplies | Tendance, pullback et déclencheur 1 h sont réunis ; l'entrée simulée a lieu à l'ouverture horaire suivante. |
| Entrée simulée | Une entrée a déjà été simulée sur cette configuration. |
| En attente | Une configuration est suivie, mais il manque une étape : J3 pas encore atteint, ou pas de déclencheur 1 h. |
| Conditions non remplies | Aucune configuration valide : aucun sommet confirmé, configuration invalidée, ou fenêtre J3–J10 dépassée. |
| Non évaluable | Une donnée indispensable manque ; aucune décision n'est inventée. |

Sous l'étiquette, trois **conditions** sont détaillées : la tendance Daily (étape 1), le pullback Daily (étape 2) et le déclencheur 1 h (étape 3). En Python, chaque condition est un petit dictionnaire `{"nom": ..., "etat": ..., "detail": ...}` rangé dans la liste `etat["conditions"]`, construite par la fonction `resumer()` de `etat_du_jour.py`. Une future condition s'ajoutera à cette liste : la page l'affichera sans autre modification. Une condition qui doit aussi *empêcher* une entrée demande en plus une règle validée dans une spécification, comme pour les étapes existantes.

Depuis le 19 novembre 2026, la page est organisée en **cinq sections**, choisies dans le menu de gauche :

| Section | Contenu |
| --- | --- |
| Vue d'ensemble | Une carte par titre (prix, mini-courbe, étiquette, conditions en une ligne, bouton « Analyser »), les chiffres du portefeuille simulé, les barèmes comparés et les dernières entrées |
| Analyse d'un titre | Les niveaux de la configuration, les trois conditions, la position simulée (chiffres clés, détail replié), les graphiques Daily et 1 h en onglets |
| Positions simulées | Liquidités en EUR et en USD, fonds en attente de règlement, valorisation, journal de toutes les entrées, conversions |
| Backtest | Les résultats du protocole figé : chiffres des deux périodes et espérance par position avec son intervalle |
| Hypothèses | Les hypothèses en vigueur, le scénario d'exécution, la configuration « Personnalisée », la lecture des étiquettes |

Le menu de gauche choisit aussi les **données** : *En direct* (cours du moment, rechargés toutes les 5 minutes, avec les 16 minutes de retard de l'offre gratuite), *Rejeu* (ce que la page aurait affiché à un instant passé, sans rien de postérieur ; exemple vérifié : le 20/10/2026 à 10:30, la position AAPL est clôturée sur un gap sous le stop) ou *Démo* (prix inventés, à trois moments au choix). Il choisit enfin le **barème simulé** affiché en détail ; les barèmes du fichier de configuration restent toujours comparés.

Une adresse peut ouvrir directement une section : `?mode=demo&section=backtest`, ou `?rejeu=2026-10-20T10:30&section=analyse`.

Le résultat d'une position s'appelle « résultat brut théorique » sans coûts et « résultat après coûts simulés » sinon. Les prix sont affichés sans arrondi : une entrée à 344,285 $ ne devient pas « 344,29 ». Tant que le signal attend son ouverture, seul le stop est connu : l'objectif et la quantité se calculent sur le prix d'ouverture. Toutes les entrées gardent leur ligne dans le journal, même refusées ou non évaluables.

Les couleurs sont neutres : fond gris clair, cartes blanches, menu anthracite, un seul accent bleu ardoise. Elles se règlent dans `.streamlit/config.toml` ; la mise en forme des cartes et du menu est dans la fonction `injecter_le_style()` de `tableau_de_bord.py`.

**Logo animé, facultatif.** Une bande d'images carrées posées côte à côte, enregistrée sous `personnalisation/logo_anime.png`, s'anime en haut du menu : la page affiche une image, puis la suivante, en boucle (`apparence.py`). Par exemple, six poses de 144 × 144 pixels forment une bande de 864 × 144. Le dossier `personnalisation/` est exclu de Git : une image personnelle n'est jamais publiée, et sans elle le menu affiche seulement son titre. L'animation s'arrête si l'ordinateur demande de réduire les animations.

Pour lire les graphiques : une bougie creuse a clôturé au-dessus de son ouverture, une bougie pleine en dessous. La SMA20 est en bleu, la SMA50 en orange. Les traits horizontaux sont le sommet de référence, la limite des 50 % (en pointillé) et le creux de référence ; ils ne sont tracés que pour une configuration de dix séances au plus. La bande grisée est la fenêtre J3–J10. Sur le graphique horaire, le triangle marque la bougie de signal, le rond vert le prix d'entrée simulé et la croix orange la sortie. Quand une position est visible, ses deux pointillés sont le stop et l'objectif. Les mêmes données sont lisibles en tableaux, en bas de la page.

Limites à garder en tête : la page décrit des règles, elle ne mesure pas leur rentabilité ; avec 16 minutes de retard, une entrée réelle se ferait plus tard et à un autre prix que l'entrée simulée ; un rejeu utilise les cours tels qu'Alpaca les fournit aujourd'hui.

Validation effectuée le 19 novembre 2026 : **363 tests réussis** au total, dont 16 pour le résumé, 11 pour les graphiques et 18 pour la page en mode démonstration (les cinq sections). Les cinq sections ont aussi été ouvertes et contrôlées à l'écran, en thème clair et en thème sombre.

Exercice : ouvre la page, choisis « Rejouer une date passée », puis le 16/10/2026 à 09:30. Que dit l'étiquette d'AAPL avant la bougie de signal ? Passe ensuite à 10:30, puis à 11:30, et suis le changement d'étiquette.

Restent à faire : lire le barème du compte dans le portail client (« Settings », « Account Configuration », « IBKR Pricing Plan ») ; valider le protocole de backtest de la spécification (section 15) : périodes, glissement, publications de résultats, convention de règlement ; puis préparer le moteur pour une longue période et l'exécuter, avec une période de validation lue une seule fois.
