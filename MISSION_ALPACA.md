# Mission : brancher Alpaca comme source de données, sans rien basculer

> **Statut : terminée le 13 novembre 2026.** La comparaison a été faite
> (`resultats/mission_alpaca_20261113_155758_078864.log`), puis le propriétaire a
> décidé de basculer : Alpaca est la source par défaut des étapes 1 à 3, avec
> `--symbole` et `--source`. Voir « Source des données » dans `GUIDE.md`.
> Les interdictions de la section 3 ne valaient que pour cette mission.

Rédigée le 13 novembre 2026 par l'agent qui pilote le projet. Tu n'as pas suivi
les échanges précédents : tout ce qu'il faut savoir est ici ou dans les fichiers cités.

## 1. But

Le projet lit aujourd'hui les cours AAPL sur Yahoo via `yfinance`, une source non
officielle. On veut la remplacer par l'API officielle **Alpaca Market Data**
(offre gratuite « Basic »). Avant de basculer, il faut prouver que les deux
sources racontent la même histoire.

Ta mission s'arrête à cette preuve :

1. télécharger AAPL chez Alpaca, en Daily et en horaire ;
2. archiver ces données dans les formats CSV que le projet lit déjà ;
3. comparer avec les archives Yahoo du 13 novembre 2026 et rendre compte des écarts.

Tu ne changes pas la source par défaut des étapes 1 à 3. Cette décision sera
prise après lecture de ton rapport.

## 2. Le projet en bref

Scanner de swing trading sur AAPL, en simulation uniquement, sans aucun ordre.
Le propriétaire est étudiant en économie et débutant en Python : il doit pouvoir
lire ton code. Lis d'abord `README.md`, puis survole `etape_03_entree_1h.py`.

| Fichier | Rôle |
| --- | --- |
| `etape_01_tendance.py` | Tendance Daily ; fournit `ecrire_csv`, `valider_clotures`, `DOSSIER_PROJET`. |
| `etape_02_pullback.py` | Pullback Daily ; fournit `normaliser_bougies`. |
| `etape_03_entree_1h.py` | Entrée horaire ; fournit `construire_grille`, `instant_utc`, `normaliser_horaires`. |
| `SPEC_PULLBACK.md`, `SPEC_ENTREE_1H.md` | Règles validées par le propriétaire. |

Python et les tests se lancent ainsi, depuis le dossier du projet (le venv est
hors du projet à cause du `;` dans le nom du dossier) :

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" -m unittest discover
```

État de départ : **134 tests réussis**. Ils doivent tous rester verts.

## 3. Ce qui ne doit pas bouger

- Ne modifie pas `etape_01_tendance.py`, `etape_02_pullback.py`,
  `etape_03_entree_1h.py`, leurs tests, les deux `SPEC_*.md` ni `README.md`.
  Les calculs sont validés ; seule l'origine des données est en question.
- N'écrase et ne supprime aucun fichier de `donnees/` ou `resultats/`.
  `ecrire_csv` refuse déjà d'écraser : réutilise-la.
- N'ajoute aucune dépendance. Utilise `urllib.request` et `json` de la
  bibliothèque standard : le code reste lisible et `requirements.txt` inchangé.
- Même style que l'existant : noms et commentaires en français, fonctions
  simples, pas de classe sans nécessité, aucun prix inventé ou interpolé.

## 4. Clés API

Les clés sont dans les variables d'environnement Windows `APCA_API_KEY_ID` et
`APCA_API_SECRET_KEY`. Elles s'envoient dans les en-têtes HTTP `APCA-API-KEY-ID`
et `APCA-API-SECRET-KEY`.

- Ne les affiche jamais, ne les écris dans aucun fichier, aucun journal, aucun
  message d'erreur.
- Si elles sont absentes, le programme s'arrête avec un message clair qui dit
  quelles variables définir. Dans ce cas, livre le code et les tests simulés,
  puis signale que le téléchargement réel n'a pas pu être fait.

## 5. Ce que l'on sait de l'API

Référence : <https://docs.alpaca.markets/reference/stockbars>. Relis-la avant de
coder ; elle fait foi si elle contredit ce document.

Confirmé dans la documentation le 13 novembre 2026 :

- `timeframe` accepte `[1-59]Min`, `[1-23]Hour`, `1Day` ;
- `adjustment` accepte `raw`, `split`, `dividend`, `spin-off`, `all` ; défaut `raw` ;
- `feed` accepte `iex`, `otc`, `sip`, `boats` ; défaut `sip` ;
- offre gratuite : historique depuis 2016, 200 appels par minute, et
  **les 15 dernières minutes ne sont pas consultables**.

De mémoire, à vérifier dans la référence : l'adresse
`https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL`, les paramètres
`start`, `end`, `limit`, `page_token`, et une réponse JSON contenant les barres
(`t`, `o`, `h`, `l`, `c`) plus un `next_page_token` pour la page suivante.

Réglages imposés :

- `adjustment=split`, toujours explicite. C'est la convention du projet : cours
  en USD, ajustés des splits, non ajustés des dividendes.
- `feed=sip`, toujours explicite. Si Alpaca le refuse avec ce compte, arrête-toi
  et rapporte le message exact. Ne bascule pas sur `iex` en silence : ce flux ne
  couvre qu'une bourse et ses High/Low peuvent différer.
- Suis la pagination jusqu'au bout. Une archive tronquée sans avertissement
  serait pire qu'une panne.
- Borne `end` à 15 minutes avant l'instant présent au plus tard.

## 6. À construire

### `source_alpaca.py`

- **Daily.** Barres `1Day` converties au format de l'étape 2 :
  `{"date", "high", "low", "cloture"}`, validées par `normaliser_bougies`.
- **Horaire.** Ne demande pas `1Hour` : on ignore si ces barres commencent à
  09:00 ou à 09:30. Demande `30Min`, puis assemble-les sur la grille de
  `construire_grille` (09:30–10:30 … 15:30–16:00, dernière tranche de 30 minutes,
  clôtures anticipées comprises). Pour chaque créneau, prends les barres de
  30 minutes dont le début est dans `[debut, fin)` :
  Open de la première, plus grand High, plus petit Low, Close de la dernière.
- **Créneau incomplet.** Un créneau de 60 minutes exige ses deux moitiés ; un
  créneau de 30 minutes en exige une. S'il en manque, ne produis pas la bougie
  et note le créneau. Le scanner sait traiter une bougie absente
  (`NON_EVALUABLE`) ; il ne sait pas détecter une bougie fabriquée.
- **Hors séance.** Les barres de pré-marché et d'après-marché ne tombent dans
  aucun créneau : ignore-les, et compte-les.
- **Archives.** Écris dans `donnees/`, avec un horodatage dans le nom comme
  l'existant, aux formats déjà lus par le projet : `Date,High,Low,Close` et
  `Datetime,Open,High,Low,Close` (instants ISO avec fuseau).
  Préfixes : `alpaca_daily_hlc_` et `alpaca_1h_`.

### `test_source_alpaca.py`

Sans réseau et sans clés : simule la réponse HTTP avec `unittest.mock.patch`,
comme le fait `test_donnees_entree_1h.py` pour `yfinance`. À couvrir au minimum :
assemblage de deux moitiés, moitié manquante, dernière tranche de 30 minutes,
barre hors séance ignorée, pagination sur deux pages, clés absentes, erreur
HTTP, et le fait que les clés n'apparaissent dans aucun message.

### `comparer_sources.py`

Compare les archives Alpaca aux archives Yahoo, date par date et créneau par créneau :

- `donnees\aapl_entree_daily_20261113_150143_329817.csv`
- `donnees\aapl_1h_20261113_150143_329817.csv`

Télécharge chez Alpaca exactement la même période que chacun de ces deux
fichiers (première et dernière ligne). Écris le détail des écarts dans un CSV de
`resultats/`, et affiche un résumé : lignes présentes d'un seul côté, puis pour
chaque champ l'écart maximal en dollars et en pourcentage, et le nombre de
bougies dont l'écart dépasse 0,01 USD.

Ne fixe aucun seuil de réussite. Tu mesures, le propriétaire décide.

## 7. Vérification finale

1. Tous les tests passent, anciens et nouveaux.
2. Rejoue l'étape 3 sur tes archives Alpaca, au même instant que le rejeu Yahoo :

```powershell
& "$env:USERPROFILE\.venvs\financial-market-dashboard\Scripts\python.exe" .\etape_03_entree_1h.py --csv-daily <ton_daily> --csv-horaire <ton_1h> --instant 2026-11-13T15:01:43+00:00 --debut 2026-10-14 --derniers 0
```

3. Compare ce journal à `resultats\aapl_entree_1h_20261113_150143_329817.csv`.
   Avec Yahoo, le résultat était : 1 signal et 1 entrée, sommet du 13 octobre 2026,
   signal sur la bougie 09:30–10:30 du 16 octobre (Close 344,30 contre High
   précédent 343,05), entrée simulée à 344,29. Dis si Alpaca donne les mêmes
   décisions, et sinon quelle bougie fait diverger.

## 8. Ce que tu dois rapporter

Réponds par des faits observés sur les données reçues, pas par des suppositions :

- `feed=sip` a-t-il été accepté avec ce compte ?
- Les barres `30Min` commencent-elles bien à :00 et :30, et leur horodatage
  marque-t-il le début de la barre ?
- Combien de barres hors séance ignorées, combien de créneaux incomplets, lesquels ?
- La barre `1Day` correspond-elle à la séance régulière ? Compare son High et son
  Low au plus haut et au plus bas de tes bougies horaires du même jour.
- Le tableau des écarts avec Yahoo, et les dix plus gros.
- Le résultat du rejeu de l'étape 3.
- Les fichiers créés, la sortie des tests, et tout ce que tu n'as pas pu faire ou vérifier.

Si un point de ce document se révèle faux ou impossible, arrête-toi sur ce point
et explique-le plutôt que de le contourner.
