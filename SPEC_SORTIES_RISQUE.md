# Sorties et risque — SPÉCIFICATION V1

Validée le 15 novembre 2026 pour les règles marquées **[VALIDÉ]**. Elle remplace
les anciens seuils fixes de −6,5 % et +15 %, abandonnés sur décision de
l'utilisateur. Les paramètres chiffrés sont des **hypothèses de simulation** :
ni des valeurs optimales, ni une recette validée par un expert.

Trois niveaux de statut sont utilisés dans ce document :

- **[VALIDÉ]** : règle demandée explicitement par l'utilisateur.
- **[CONVENTION]** : précision choisie par le pilote pour rendre la règle
  calculable ; à relire, modifiable sans toucher aux règles validées.
- **[À CONFIRMER]** : dépend d'une information que le projet n'a pas encore.

Ce document complète SPEC_PULLBACK.md et SPEC_ENTREE_1H.md sans modifier leurs
règles. Le code est dans `etape_04_sorties_risque.py`.

**Révision du 16 novembre 2026.** Les règles de stratégie [VALIDÉ] sont
inchangées (stop, objectif 2R, D10, 0,5 % et 1 %). Les conventions de change, de
coûts et d'exécution ont été vérifiées et corrigées avant tout backtest long :

- le compte simulé tient **deux soldes**, EUR et USD ; une conversion n'est
  simulée que s'il manque des USD, et une vente ne revient plus d'office en EUR
  (section 8) ;
- commissions, coût de conversion et devenir des USD sont **trois hypothèses
  indépendantes**, nommées, jamais présentées comme celles d'un compte réel ;
- le taux BCE daté d'un jour n'est utilisé qu'à partir de 18:00 à Francfort
  (avant : 16:00 pile, une précision que rien ne garantit) ;
- le prix d'entrée est affiché sans arrondi : l'écart apparent 353,00 / 353,01
  venait d'une entrée à 344,285 affichée « 344,29 » (section 5) ;
- un résultat sans coûts s'appelle « résultat brut théorique », un résultat avec
  coûts « résultat après coûts simulés » ; le mot « net » n'est plus employé ;
- la différence entre résultat théorique et exécution réalisable est écrite
  (section 9).

**Seconde révision du 16 novembre 2026 : le compte est décrit.** Le titulaire a
confirmé : compte **au comptant**, uniquement des **EUR** détenus, **fractions
activées**, **conversion automatique** utilisée. La tarification (« Fixed » ou
« Tiered ») reste inconnue.

- Deux configurations nommées sont calculées côte à côte, avec les mêmes règles
  et les mêmes données : `IBKR_CASH_AUTO_FRACTIONS_FIXED` et
  `IBKR_CASH_AUTO_FRACTIONS_TIERED`. Aucune n'est retenue en silence.
- Le produit d'une vente n'est disponible pour un achat qu'une fois **réglé**
  (section 8, « Liquidités d'un compte au comptant »).
- Une entrée que les fonds disponibles ne peuvent pas payer est refusée avec le
  motif `FONDS_DISPONIBLES_INSUFFISANTS`.
- L'inventaire des données et le protocole de backtest sont en section 15.

**Décisions du titulaire, 16 novembre 2026, avant tout calcul de performance.**

- Historique long, avec traitement exact des divisions d'actions (section 9).
- Glissement : 2 points de base en scénario principal, 10 en scénario
  défavorable. Ce sont des hypothèses de simulation.
- Publications de résultats : la V1 sans filtre et une variante sont comparées ;
  la règle de la variante est écrite en section 15.
- Règlement : délai en vigueur à la date de la vente en scénario principal, un
  jour ouvré de plus en scénario défavorable.
- Les dates des périodes sont inscrites en section 15 et dans le code
  (`historique.PERIODES`). Elles ne changent plus après lecture d'un résultat.

## 1. Périmètre

- Positions acheteuses au comptant, sans levier, **simulation uniquement**.
  Aucun ordre réel, aucune connexion au courtier.
- Capital de l'expérience : **1 000 EUR et 0 USD**. Ce n'est pas le solde réel
  d'un compte. Cours et règlements en USD ; valorisation comptable en EUR.
- Scénario principal, d'après les caractéristiques confirmées du compte : compte
  au comptant, donc aucun emprunt ni solde négatif ; fractions d'action ;
  conversion automatique du seul montant nécessaire à un achat et à ses frais ;
  USD conservés après une vente puis réutilisés ; produit d'une vente
  disponible après règlement.
- Titres : AAPL d'abord ; les mêmes règles s'appliquent à NVDA et AVGO avec
  **une seule position ouverte par titre**. [CONVENTION pour NVDA et AVGO]
- L'objectif personnel (passer de 1 000 à 5 000 EUR de capital) n'intervient
  dans aucun calcul : ni la taille, ni les seuils, ni le choix des paramètres.

## 2. Paramètres V1 [VALIDÉ]

| Paramètre | Valeur |
| --- | --- |
| Stop initial | Plus bas du pullback connu à la clôture du signal − 0,25 × ATR14 Daily |
| Objectif | Entrée + 2 × (entrée − stop) |
| Durée maximale | Clôture officielle de la 10e séance de détention (D10), séance d'entrée = D1 |
| Risque par position | Au plus 0,5 % de l'equity à la décision, coûts estimés compris |
| Risque cumulé | Au plus 1 % de l'equity pour l'ensemble des positions ouvertes |
| Exposition | Au plus 100 % de l'equity, payée par les liquidités ; aucun emprunt |
| Gestion | Stop et objectif fixes, sortie intégrale, ni renfort ni réentrée |

## 3. Ce qui change par rapport à l'existant

Contradictions concrètes relevées en relisant les spécifications et le code,
avec la façon dont elles sont résolues. **Aucune règle des étapes 1 à 3 n'est
modifiée.**

1. **Une entrée acceptée ne donne pas toujours une position.** L'étape 3 accepte
   une entrée si la configuration reste valide à l'ouverture. La présente
   étape ajoute trois refus : ouverture au niveau du stop ou en dessous, taille
   impossible, position déjà ouverte sur le titre. Le journal de l'étape 3 reste
   identique ; le refus est écrit dans le **journal des positions**. Les deux
   notions sont donc distinctes : « entrée simulée » (étape 3) et « position »
   (étape 4).
2. **Une position peut chevaucher la configuration suivante.** D1–D10 dure plus
   longtemps que l'attente d'un nouveau sommet. L'étape 3 peut donc accepter
   une entrée sur une nouvelle configuration pendant qu'une position est
   ouverte : elle est refusée ici (`POSITION_DEJA_OUVERTE`).
3. **Le rôle des invalidations après l'entrée était laissé ouvert** par
   SPEC_ENTREE_1H.md (« relève de la future spécification des sorties »). Il est
   tranché : une invalidation du signal n'est **pas** une sortie. En particulier,
   un nouveau plus haut au-dessus du sommet est la continuation recherchée.
4. **Le plus bas du pullback n'était pas écrit dans le journal horaire.** Le
   moteur de l'étape 3 le suit déjà pour contrôler les 50 %. Seul ajout au
   module existant : une colonne `plus_bas_repli` sur chaque ligne du journal.
   Aucun statut, aucun motif, aucune décision ne change.
5. **Il n'existait ni ATR, ni frais, ni portefeuille, ni taux de change.** Tout
   est créé dans le nouveau module et dans `source_bce.py`.
6. **Deux horloges coexistent.** J3–J10 autorise l'entrée depuis le sommet.
   D1–D10 compte la détention depuis l'achat. L'expiration de J10 ne ferme
   jamais une position.

## 4. Stop initial [VALIDÉ]

Notations : `L` = plus bas du pullback, `A` = ATR14 Daily, `S` = stop, tous en
USD par action.

- `L` est la valeur `plus_bas_repli` du moteur horaire sur la ligne `SIGNAL` :
  Low Daily depuis J1, puis Low des bougies horaires **terminées**, bougie de
  signal comprise. Le Low final d'une séance en cours n'est jamais utilisé.
- `A` est l'ATR14 de la dernière séance Daily connue à l'instant du signal.
  Pendant une séance, c'est celle de la veille. À la clôture officielle de J2,
  la bougie J2 est comprise, selon l'ordre des événements déjà validé.
- `S_brut = L − 0,25 × A`. `S` est `S_brut` arrondi **vers le bas** au pas de prix.
- `S` est figé à la clôture du signal. À l'ouverture d'entrée, de prix `E` :
  si `E <= S`, l'entrée est refusée (`ENTREE_SOUS_STOP`). Le stop n'est jamais
  déplacé pour rendre une entrée acceptable.
- `L` ou `A` indisponible : `NON_EVALUABLE`, aucune position.

### ATR14 de Wilder

```text
TR[i]  = max(High[i] − Low[i], |High[i] − Close[i−1]|, |Low[i] − Close[i−1]|)
ATR[14] = moyenne simple de TR[1] … TR[14]          (15 séances nécessaires)
ATR[i]  = (13 × ATR[i−1] + TR[i]) / 14              pour i > 14
```

L'ATR dépend de son point de départ, de moins en moins à chaque séance : après
40 séances de lissage, la moyenne initiale ne pèse plus que 5 %. Le filtre de
tendance exige déjà 55 séances ; un signal dispose donc toujours d'au moins
40 séances de lissage. Le journal conserve la date de la séance utilisée et le
début de l'historique. Mêmes cours que le reste du projet : ajustés des splits,
non ajustés des dividendes.

### Pas de prix [À CONFIRMER]

Le pas est lu dans la configuration de l'instrument, jamais supposé en silence.
Valeur inscrite : **0,01 USD** pour AAPL, NVDA et AVGO, soit le pas minimal de
la règle 612 de la SEC pour les actions de 1 USD et plus. Une réforme prévoit un
pas de 0,005 USD pour certaines actions ; sa date d'application n'a pas pu être
confirmée. Le pas réellement affiché par le courtier fait foi.

## 5. Objectif [VALIDÉ]

Ordre des calculs, toujours le même :

1. stop brut `S_brut = L − 0,25 × A` ;
2. stop `S` : `S_brut` arrondi vers le bas au pas de prix ;
3. distance de risque par action `d = E − S`, strictement positive, calculée à
   partir du stop **arrondi** ;
4. objectif brut `T_brut = E + 2 × d`, puis `T` : `T_brut` arrondi **vers le
   haut** au pas de prix ;
5. ces mêmes `E`, `S`, `d` et `T` servent à la taille, à la sortie et à
   l'affichage.

- Ratio effectif journalisé : `(T − E) / (E − S)`.
- Risque initial de prix : `R = quantité × d`.
- Le journal conserve `stop_brut`, `stop`, `distance`, `cible_brute` et `cible`.

Le ratio 2R décrit un mouvement de prix avant frais, glissement et change. Il ne
garantit ni un gain de 2R après coûts, ni une perte limitée à 1R.

### Prix d'entrée hors du pas de prix [CONVENTION]

`E` est l'Open de la bougie horaire, tel que la source le fournit. Ce prix est
celui de la première transaction du créneau : il peut tomber entre deux
centimes. Exemple réel, AAPL le 16/10/2026 : `E = 344,285`, `S = 339,93`,
`d = 4,355`, `T_brut = 352,995`, `T = 353,00`. Avec une entrée à 344,29 tout
rond, le même calcul donnerait 353,01.

`E` n'est pas arrondi : ce serait modifier la règle d'entrée validée. Il est en
revanche **affiché tel quel** (« 344,285 »), et non plus arrondi à deux
décimales. Un ordre réel serait saisi sur un multiple du pas de prix.

## 6. Durée maximale [VALIDÉ]

- D1 est la séance d'entrée. D10 est la dixième séance du calendrier NASDAQ,
  séances raccourcies comprises.
- Sans stop ni objectif touché, la position est liquidée à la **clôture
  officielle de D10**. Cette sortie est programmée à l'avance.
- Prix retenu : le Close de la bougie Daily de D10. [CONVENTION] C'est un prix
  **théorique** : la simulation ne démontre pas qu'un ordre réel l'obtiendrait
  (section 9, « Résultat théorique et exécution réalisable »).
- Les événements de prix de D10 (stop, objectif) passent avant cette liquidation.

## 7. Taille de position [VALIDÉ]

À l'entrée : `C` = equity en EUR, `r` = EUR pour 1 USD au taux de référence,
`B = 0,005 × C`. La quantité `q` est la **plus grande** quantité autorisée qui
respecte à la fois :

1. `q × (E − S) × r + K_stop(q) <= B` — risque prévu, coûts d'un aller-retour
   jusqu'au stop compris ;
2. risque prévu `<= 0,01 × C −` risques initiaux déjà réservés ;
3. le paiement de l'achat est couvert par les USD disponibles, complétés par une
   conversion d'EUR, coût de conversion compris : **aucun solde ne devient
   négatif**, donc aucun emprunt ;
4. exposition après l'entrée `<= C`.

`q` est arrondie **vers le bas** au pas de quantité. Si aucune quantité positive
ne convient : `PAS_DE_POSITION_TAILLE_INSUFFISANTE`. Le risque n'est jamais
relevé pour rendre un achat possible ou pour rattraper une perte.

- L'equity est la valorisation comptable en EUR : solde EUR, plus solde USD et
  positions ouvertes (au dernier prix horaire connu) convertis au dernier taux
  de référence disponible. [CONVENTION]
- Le risque réservé d'une position ouverte reste son risque prévu initial
  jusqu'à sa clôture. Ce n'est pas une garantie contre un gap.
- Les frais ayant un minimum, la quantité est cherchée avec la vraie fonction
  de frais, pas par une division approchée.
- `K_stop(q)` est calculé par les **mêmes fonctions de règlement** que le
  résultat final (section 8) : un coût estimé au dimensionnement est le coût
  appliqué si la sortie a lieu au stop, ni plus ni moins.
- Conséquence : la quantité dépend des USD disponibles. Exemple fictif testé :
  avec 81 USD détenus et une conversion à 2 USD minimum, le modèle achète
  0,81 action à 100 USD et pas davantage, car convertir le complément ferait
  dépasser le budget.
- Le budget suit l'equity : il baisse après une perte et monte après un gain.

### Pas de quantité [À CONFIRMER]

Les fractions sont activées sur le compte : les configurations de référence les
utilisent, avec un pas de **0,0001 action**. Ce pas est une hypothèse : la
documentation publique donne un montant minimal de 0,01 USD par ordre
fractionné, pas le nombre de décimales accepté. Il se vérifie sur un ticket
d'ordre. Une simulation personnalisée peut encore imposer des actions entières.
Conséquence chiffrée, sans frais, pour
1 000 EUR : le budget est de 5 EUR. Une action AAPL dont le stop est à 8 USD de
l'entrée risque déjà environ 7 EUR. **Avec des actions entières, la plupart des
entrées seront refusées pour taille insuffisante.**

## 8. Coûts et change

Deux notions ne doivent jamais être confondues :

- la **valorisation en EUR** : traduire en EUR ce que le compte contient, au
  taux de référence. Elle ne déplace aucun argent et ne coûte rien ;
- une **conversion** : échanger réellement des EUR contre des USD, ou
  l'inverse. Elle a un taux d'exécution et un coût.

Une devise de base en EUR ne signifie pas que chaque flux est converti. Dans la
documentation générale d'Interactive Brokers, le produit d'une vente en USD
reste en USD tant que le client ne le convertit pas (section 13).

### Hypothèses de coûts et d'exécution [CONVENTION]

Cinq réglages **indépendants**. Aucun n'est choisi d'après les résultats qu'il
produit.

| Réglage | Valeurs | Contenu |
| --- | --- | --- |
| Commissions | `aucun` | Zéro. Théorique. |
| | `ibkr_fixe` | Barème public « Fixed » : 0,005 USD par action, minimum 1 USD, plafond 1 % du montant ; annoncé tout compris |
| | `ibkr_tiered` | Barème public « Tiered », premier palier : 0,0035 USD, minimum 0,35 USD, plafond 1 % ; frais externes en plus |
| Conversion | `sans_cout` | Au taux de référence, sans coût. Théorique. |
| | `ibkr_auto` | Tarif public de la conversion automatique : 0,03 % compris dans le taux |
| | `ibkr_manuelle` | Tarif public de la conversion manuelle : 0,002 %, minimum 2 USD par conversion |
| USD reçus d'une vente | `usd_conserves` | Ils restent en USD et paient les achats suivants |
| | `retour_eur` | Chaque vente est reconvertie en EUR |
| Règlement | `immediat` | Produit d'une vente réutilisable tout de suite. Théorique. |
| | `historique` | Délai en vigueur à la date de la vente : J+3 jusqu'au 04/09/2017, J+2 du 05/09/2017 au 27/05/2024, J+1 depuis le 28/05/2024 |
| | `historique_plus_un` | Le même, plus un jour ouvré de règlement |
| | `j1_prudent`, `j2_defavorable` | Délais fixes d'un et de deux jours ; égaux aux deux précédents depuis le 28/05/2024 |
| Glissement | deux nombres >= 0 | USD par action, et points de base du prix, sur chaque ordre au marché ; 0 et 0 = « hypothèse de glissement nul » |

Des valeurs `synthetique` existent pour les commissions et la conversion : elles
sont inventées, réservées aux tests, et absentes du tableau de bord.

### Configurations nommées et scénarios d'exécution

| Nom | Commissions | Conversion | USD après une vente | Quantités |
| --- | --- | --- | --- | --- |
| `IBKR_CASH_AUTO_FRACTIONS_FIXED` | `ibkr_fixe` | `ibkr_auto` | `usd_conserves` | fractions |
| `IBKR_CASH_AUTO_FRACTIONS_TIERED` | `ibkr_tiered` | `ibkr_auto` | `usd_conserves` | fractions |
| `THEORIQUE_SANS_COUTS` | `aucun` | `sans_cout` | `usd_conserves` | fractions |

Le glissement et le règlement des deux configurations IBKR viennent d'un
**scénario d'exécution**, validé le 16 novembre 2026 :

| Scénario d'exécution | Glissement | Règlement |
| --- | --- | --- |
| `principal` | 2 points de base du prix (0,02 %) | `historique` |
| `defavorable` | 10 points de base du prix (0,10 %) | `historique_plus_un` |

La configuration théorique n'a ni glissement ni délai. Ces valeurs sont des
hypothèses de simulation, pas des mesures de l'exécution du compte.

Les deux premières sont les **scénarios de coûts simulés**. Elles partagent les
règles, les données, le capital et le scénario d'exécution ; seul le barème change. Les
quantités et les refus peuvent différer, car les coûts entrent dans le
dimensionnement. Tant que la tarification du compte est inconnue, tout résultat
est donné pour les deux, jamais comme le résultat net du compte. La troisième
donne le résultat brut théorique de la stratégie.

Le capital et la liste des scénarios calculés sont lus dans un fichier de
configuration. `configuration_exemple.toml` est publié avec le projet et ne
contient aucune donnée personnelle. `configuration_locale.toml`, facultatif,
décrit le compte de l'utilisateur ; il est exclu de la publication par
`.gitignore`. Aucun identifiant, relevé ou solde réel n'y est écrit.

### Commissions, fractions et frais externes

```text
commission(q, prix) = max( plancher, min( max(par_action × q, minimum), plafond × q × prix ) )   en USD
frais externes      = externes_par_action × q  (+ externes_vente_taux × q × prix sur une vente)
glissement          = q × (glissement_par_action + prix × points_de_base / 10 000)   ordres au marché
conversion(U)       = max(U × r × taux, minimum_usd × r)   en EUR, pour U dollars convertis
                    = 0 si U = 0 : détenir des USD ne coûte rien
```

- **Fractions.** Le barème public indique que les ordres fractionnés suivent les
  mêmes tarifs que les ordres entiers, avec une commission d'au moins 0,01 USD.
  Son exemple : la moitié d'une action à 10 USD coûte 0,05 USD, soit le plafond
  de 1 %. D'où `plancher = 0,01`.
- **Ordre de grandeur.** Pour un ordre d'environ 300 USD, le plafond de 1 %
  (3 USD) ne joue pas : « Fixed » facture son minimum de 1 USD, « Tiered » son
  minimum de 0,35 USD plus les frais externes.
- **Frais externes de « Tiered »** [CONVENTION]. Hypothèse : 0,0030 USD par
  action de frais de place et 0,0002 USD de compensation, plus 20,60 USD par
  million vendu (frais de la SEC en vigueur depuis le 4 avril 2026). Pour une
  action, cela fait moins d'un centime : l'effet est négligeable à ce capital,
  mais il est compté.

### Glissement [VALIDÉ le 16 novembre 2026]

Le glissement est toujours **défavorable** : un achat au marché est payé plus
cher que le prix de la règle, une vente au marché rapporte moins.

- Ordres concernés : l'entrée, le stop, la sortie sur gap et la sortie D10.
- Ordre non concerné : l'objectif. C'est un ordre à cours limité : il n'est
  jamais simulé sous sa limite. Son risque propre est de **ne pas être
  exécuté** ; il est suivi à part, par le décompte des objectifs touchés sans
  être dépassés (section 9), et non par un glissement.
- Le journal garde le prix de la règle (`entree_prix`, `sortie_prix`) et le
  prix d'exécution simulé (`entree_prix_execute`, `sortie_prix_execute`).
- Le glissement est un poste distinct (`glissement_eur`), séparé des
  commissions et des coûts de conversion. Il n'est compté qu'une fois : dans le
  montant à payer à l'achat, dans le produit de la vente, et donc dans le
  risque prévu au dimensionnement.
- Le stop, l'objectif et la distance de risque restent calculés sur le prix de
  la règle.

Exemple fictif : achat de 2 actions à 100 USD avec 10 points de base. Prix
d'exécution simulé 100,10 USD ; glissement 0,20 USD ; commission « Fixed »
1,00 USD ; conversion automatique de 201,20 USD.

Ambiguïtés restantes, documentées et non tranchées :

- le barème réel du compte ;
- les frais de place dépendent du lieu d'exécution, et la partie fractionnaire
  d'un ordre est exécutée par le courtier lui-même ;
- une page décrit « Fixed » comme tout compris, d'autres mentionnent des frais
  réglementaires sur les ventes ;
- les frais de la SEC et ceux de la FINRA changent dans le temps : un taux
  constant est appliqué à tout l'historique ;
- la façon dont le plancher de 0,01 USD et le plafond de 1 % se combinent sur
  un très petit ordre fractionné.

Un avis d'opéré réel lève la plupart de ces doutes en une ligne.

### Deux soldes et règlements [CONVENTION]

Le compte simulé détient un solde en EUR et un solde en USD. Les liquidités de
départ sont un paramètre : par défaut 1 000 EUR et 0 USD.

**Achat** de `q` actions au prix `E` :

```text
à payer (USD)   = q × E + commission + glissement
manque (USD)    = max(0, à payer − USD disponibles)
EUR prélevés    = manque × r + conversion(manque)
```

Les USD disponibles paient d'abord. Seul le manque est converti. Un achat payé
entièrement avec des USD déjà détenus ne déclenche **aucune** conversion.

**Vente** de `q` actions au prix `P` :

```text
produit (USD)   = q × P − commission − glissement
usd_conserves   : le produit s'ajoute au solde USD ; aucune conversion
retour_eur      : EUR reçus = produit × r − conversion(produit)
```

Avec `retour_eur`, seul le produit de la vente est converti, pas les USD
détenus par ailleurs. Si les frais d'une vente dépassaient son produit, le
manque serait acheté en EUR : un solde n'est jamais négatif.

**Taux d'exécution simulé.** Chaque conversion est journalisée avec le taux de
référence, les EUR réellement payés ou reçus, et le taux d'exécution simulé,
égal à `EUR / USD` coût compris. Exemple fictif : 75 USD achetés quand
1 USD = 1 EUR, minimum de 2 USD ; 77 EUR payés ; taux d'exécution 1,0267 contre
une référence de 1,0000. Ce taux est une hypothèse, pas un prix garanti.

### Liquidités d'un compte au comptant [CONVENTION]

Documentation du courtier : un compte au comptant ne peut pas emprunter ; il
achète avec ses liquidités **réglées** ; le produit d'une vente reste
indisponible pour un achat jusqu'au règlement ; les actions américaines se
règlent le jour ouvré qui suit la transaction. Pour éviter une conversion
automatique, il faut des fonds réglés dans la devise de l'achat.

Quatre notions sont donc tenues séparément :

| Notion | Définition dans la simulation |
| --- | --- |
| Solde comptable | Ce que le compte contient, produits de ventes non réglés compris. Il sert à la valorisation en EUR. |
| En attente de règlement | Produit d'une vente pas encore réglé, avec sa date de disponibilité. |
| Disponible pour un achat | Solde comptable moins les montants en attente. Lui seul paie un achat et entre dans le dimensionnement. |
| Réservé par un ordre | Toujours 0 : un achat simulé est payé à l'instant où il est décidé, et les frais d'une vente sont prélevés sur son produit. Un courtier, lui, bloque des fonds dès qu'un ordre d'achat est déposé. |

Chaque flux a son propre délai ; aucun délai unique n'est appliqué à tout :

| Flux | Effet sur le disponible |
| --- | --- |
| Achat, commission, glissement | Débit immédiat |
| Conversion automatique à l'achat | EUR débités tout de suite ; les USD obtenus sont consommés par l'achat |
| Vente d'actions (USD reçus) | Disponible à l'ouverture du **jour de règlement suivant** |
| Vente reconvertie en EUR (`retour_eur`) | Disponible à l'ouverture du **deuxième** jour de règlement, délai usuel d'une opération de change |

**Délai selon l'époque [VALIDÉ le 16 novembre 2026].** Le délai de règlement
des actions américaines a changé deux fois sur la période étudiée. La
convention `historique` applique celui de la date de la vente :

| Vente | Délai |
| --- | --- |
| jusqu'au 04/09/2017 | J+3 |
| du 05/09/2017 au 27/05/2024 | J+2 |
| depuis le 28/05/2024 | J+1 |

`historique_plus_un` ajoute un jour ouvré de règlement : c'est le scénario
défavorable.

**Calendrier de règlement.** Un jour de règlement est une séance NASDAQ qui
n'est pas un jour férié bancaire américain. Deux jours par an, la Bourse ouvre
alors que les banques sont fermées (Columbus Day, deuxième lundi d'octobre ;
Veterans Day, 11 novembre). Les avis de la chambre de compensation ne sont pas
tranchés pour ces jours : par prudence, ils ne comptent pas. Un week-end ou un
jour férié repousse donc la disponibilité d'autant.

**Heure de disponibilité.** Les fonds sont rendus disponibles à l'ouverture de
la séance, 09:30 à New York. C'est une **convention de simulation**, pas une
heure confirmée pour le compte : l'heure à laquelle le courtier considère les
fonds comme réglés n'est pas documentée.

**Ordre de financement d'un achat.** D'abord les USD déjà disponibles ; puis la
conversion du seul complément nécessaire, depuis les EUR disponibles ; sinon la
quantité est réduite, ou l'achat refusé. Les USD en attente de règlement ne
sont jamais utilisés avant leur date.

Conséquences testées :

- une vente à 11:30 puis un achat à 12:30 le même jour : les USD de la vente ne
  sont pas utilisables, l'achat est payé par une conversion d'EUR ;
- le lendemain à l'ouverture, ces USD paient l'achat sans conversion ;
- une vente du vendredi est disponible le lundi ; une vente du jeudi 3 juillet
  2025 (vendredi férié) aussi ; une vente du vendredi 9 octobre 2026 ne l'est
  que le mardi 13, le lundi 12 étant férié pour les banques ;
- si les fonds disponibles ne paient pas même la plus petite quantité, l'entrée
  est refusée : `FONDS_DISPONIBLES_INSUFFISANTS`. Ce refus est distinct de
  `PAS_DE_POSITION_TAILLE_INSUFFISANTE`, qui concerne le risque ;
- si les fonds disponibles ne paient qu'une partie de la quantité voulue, la
  position est réduite, et la contrainte `LIQUIDITES` est notée.

### Résultat d'une position et valorisation [CONVENTION]

`r_e` et `r_s` sont les taux de référence (EUR pour 1 USD) à l'entrée et à la
sortie ; `P` est le prix de sortie.

```text
brut_usd         = q × (P − E)
brut_eur         = brut_usd × r_e                 résultat de prix
effet_change     = q × P × (r_s − r_e)            valorisation : la position en USD a changé de valeur en EUR
couts_eur        = commissions + glissement (valorisés au taux de leur date)
                   + coûts des conversions réellement simulées pour cette position
apres_couts_eur  = brut_eur + effet_change − couts_eur
```

Les USD **détenus entre deux positions** changent aussi de valeur en EUR quand
le taux bouge. Cet effet n'appartient à aucune position : il est suivi à part
(`effet_change_liquidites_eur`). Ce n'est ni une conversion ni un coût.

Identité comptable, vérifiée par les tests dans les deux scénarios :

```text
equity finale = equity de départ + somme des apres_couts_eur
                + effet de change sur les USD détenus
```

Elle garantit qu'aucun coût n'est compté deux fois ni oublié. La somme des
coûts de change des positions est égale à la somme des coûts du journal des
conversions.

Le taux d'entrée sert au dimensionnement ; une variation EUR/USD peut donc
modifier la perte finale en EUR.

### Vocabulaire des résultats

| Situation | Libellé |
| --- | --- |
| Aucun coût simulé | « Résultat brut théorique » |
| Au moins un coût simulé | « Résultat après coûts simulés », suivi des hypothèses |
| Glissement à 0 | Mention « hypothèse de glissement nul » |
| Conditions du courtier non confirmées | Jamais « net » ni « réaliste » |

### Taux de référence et causalité [CONVENTION]

Source : taux de référence EUR/USD de la Banque centrale européenne, un par
jour ouvré. La BCE écrit qu'ils sont « habituellement mis à jour vers 16:00
CET », sauf les jours de fermeture de TARGET, qu'ils sont publiés « pour
information seulement » et qu'elle déconseille fortement de s'en servir pour
des transactions. Ce taux sert donc à **valoriser**, jamais à prétendre
connaître le taux d'un courtier.

- **Sens du taux.** La BCE cote « 1 EUR = x USD ». Convertir des USD en EUR,
  c'est diviser par x : avec x = 1,25, 100 USD valent 80 EUR. Le code nomme les
  deux sens (`usd_par_eur`, `eur_par_usd`) pour éviter toute confusion.
- **Heure de disponibilité.** Le fichier de la BCE ne contient que des dates :
  l'heure réelle de chaque publication passée est inconnue. Convention
  prudente : le taux daté du jour J n'est utilisé qu'à partir de **18:00, heure
  de Francfort** (`Europe/Berlin`, heure d'été comprise), soit midi à New York
  la plupart de l'année. Avant, on garde le dernier taux précédent. Cette marge
  couvre un retard de publication et les deux lectures possibles de « CET » en
  été. **18:00 est une hypothèse de disponibilité, pas une preuve historique de
  publication** : rien n'établit qu'un taux passé était en ligne à cette heure,
  ni qu'il ne l'était pas plus tôt. Seul contrôle réel disponible : le vendredi
  13/11/2026, le fichier a été mis à jour à 15:56 à Francfort.
- **Jours sans publication** (week-end, jour férié TARGET, valeur « N/A ») : le
  dernier taux publié reste en vigueur.
- **Taux trop ancien.** Sans taux disponible depuis moins de sept jours :
  `TAUX_DE_CHANGE_INDISPONIBLE`, et aucune valeur n'est inventée.
- **Journal.** Chaque position note la date du taux utilisé à l'entrée et à la
  sortie (`taux_entree_jour`, `taux_sortie_jour`).

Exemple réel : l'entrée AAPL du 16/10/2026 a lieu à 10:30 à New York, soit
16:30 à Francfort. Le taux du 16 n'est pas encore réputé disponible : le taux
du 15 (1 EUR = 1,1208 USD) est utilisé. La sortie du 20/10 à 09:30 utilise le
taux du 19 (1,1225).

Limite assumée : un taux quotidien, lu avec retard, n'est pas le taux du moment.
La valorisation en EUR d'une position de quelques jours peut s'en écarter de
quelques dixièmes de pour cent.

## 9. Simulation des sorties [VALIDÉ]

Séance régulière seulement, même grille horaire que l'étape 3. Stop et objectif
sont actifs dès l'entrée. Une information postérieure peut clôturer une
position ; elle ne modifie jamais rétroactivement l'entrée ni sa taille.

Pour chaque bougie horaire terminée, dans l'ordre du temps :

1. **Ouverture** (sauf bougie d'entrée, dont l'Open est le prix d'achat) :
   - `Open <= S` : sortie à l'Open, motif `STOP_GAP`. Jamais au niveau du stop.
   - `Open >= T` : sortie au prix `T`, motif `CIBLE_GAP`. Aucune amélioration
     de prix n'est créditée.
2. **Pendant la bougie** : `Low <= S` déclenche le stop au prix `S` ;
   `High >= T` déclenche l'objectif au prix `T`. Les égalités comptent.
3. **Les deux dans la même bougie** : la chronologie est inconnue. La position
   est marquée `AMBIGU_INTRABAR` et le **stop est retenu**, par prudence. Ces cas
   sont comptés à part ; cet ordre n'est pas présenté comme observé.
4. **Dernière bougie de D10** sans sortie : liquidation au Close Daily de D10,
   motif `DUREE_MAX_D10`.

Le glissement s'applique aux sorties au marché (stop, gap, D10), pas à
l'objectif, qui est un ordre à cours limité.

Un objectif touché **sans être dépassé** (plus haut exactement égal à `T`) est
compté comme atteint, selon la règle validée. Un ordre limite réel n'aurait pas
forcément été servi : ces cas portent le repère `cible_a_l_egalite` et sont
comptés à part.

### Divisions d'actions : cours continus et cours réels [VALIDÉ le 16 novembre 2026]

Une division d'actions (par exemple 10 actions nouvelles pour 1 ancienne)
divise le cours par dix du jour au lendemain, sans que rien n'ait été gagné ni
perdu. Quatre divisions touchent la période : AAPL le 31/08/2020 (4 pour 1),
NVDA le 20/07/2021 (4 pour 1) et le 10/06/2024 (10 pour 1), AVGO le 15/07/2024
(10 pour 1).

Les cours « ajustés » de la source ne conviennent pas : ils sont arrondis, au
centime pour AAPL et AVGO, à quatre décimales pour NVDA. Constat du 16 novembre
2026 : AVGO, cours brut 157,32 USD le 04/04/2016, cours ajusté fourni 15,73 au
lieu de 15,732. Un tel arrondi peut transformer une égalité en dépassement et
créer un faux signal. Le projet télécharge donc les **cours bruts** et applique
lui-même les rapports exacts, sans arrondi.

Deux séries, qui ne se mélangent jamais :

| Série | Calcul | Usage |
| --- | --- | --- |
| Cours continus | cours brut ÷ facteur de sa date | Indicateurs et signaux des étapes 1 à 3. Toutes leurs règles comparent des prix entre eux : elles ne voient aucun saut le jour d'une division. |
| Cours réels de l'époque | cours continu × facteur de la séance d'entrée | Tout le calcul d'une position : plus bas, ATR, stop, objectif, bougies suivies, quantité, commissions. |

Le facteur d'une date est le produit des divisions **postérieures** à cette
date : 40 pour NVDA avant le 20/07/2021, 10 entre les deux divisions, 1 depuis
le 10/06/2024.

Conséquences, toutes testées :

- le pas de prix de 0,01 USD s'applique au cours réel. Exemple : cours continu
  100, facteur 40 ; le stop est arrondi sur 3 877,10 USD réels, et non sur
  96,93 ;
- la quantité est un nombre d'actions de l'époque : dix fois moins d'actions,
  dix fois plus chères, pour le même montant et le même risque ;
- les commissions par action portent sur ces actions réelles ;
- une division **pendant** la détention ne crée ni gain ni perte : la position
  est suivie en cours réels de sa date d'entrée, série continue ; à la vente,
  dix fois plus d'actions valent chacune dix fois moins ;
- la table des divisions est vérifiée contre les données à chaque
  téléchargement : un désaccord arrête le programme.

Le tableau de bord en direct n'est pas concerné : aucune division n'est
intervenue sur son année de recul.

### Rôle des barres de 30 minutes

La source fournit des barres de 30 minutes. Elles ont **un seul rôle** :
reconstruire les bougies horaires du projet, ancrées à 09:30 (09:30–10:30 …
14:30–15:30, puis la dernière tranche 15:30–16:00, acceptée telle quelle selon
la convention validée). Si une moitié manque, aucune bougie n'est fabriquée.

Le déclencheur d'entrée reste évalué sur ces bougies horaires, à leur clôture.
Il n'est jamais évalué toutes les 30 minutes : un test le vérifie.

Les barres de 30 minutes pourraient aussi départager un stop et un objectif
touchés dans la même heure. Ce n'est **pas fait** : ce serait une nouvelle
convention de sortie, à valider et à tester à part. Le cas reste marqué
`AMBIGU_INTRABAR`, stop retenu.

### Résultat théorique et exécution réalisable

La simulation produit le **résultat théorique de la stratégie** : chaque
événement est supposé exécuté exactement au prix de la règle. Elle ne démontre
pas qu'un ordre réel aurait obtenu ce prix. Ni l'heure de sortie ni le
déclencheur d'entrée ne sont modifiés pour réduire cet écart.

| Événement simulé | Prix retenu | Ce qu'il faudrait en réel | Écart à prévoir |
| --- | --- | --- | --- |
| Entrée | Open de la bougie 1 h suivante | Ordre au marché envoyé à l'heure pile | Prix différent de la première transaction ; taille fixée avant de connaître le prix |
| Stop touché en séance | Niveau du stop | Ordre stop déposé dès l'achat | Un stop devient un ordre au marché : exécution souvent en dessous |
| Gap sous le stop | Open de la bougie | Idem | Simulé à l'Open, qui reste un prix théorique |
| Objectif | Niveau de l'objectif | Ordre limite déposé dès l'achat | Aucune garantie d'être servi au contact ; stop et limite doivent s'annuler l'un l'autre |
| Durée maximale D10 | Close Daily officiel | Ordre exécuté à l'enchère de clôture | Voir ci-dessous |

**Fractions d'action chez Interactive Brokers.** D'après la documentation
publique consultée le 15 et le 16 novembre 2026 (section 13) : les ordres au
marché, à cours limité, stop et stop-limite sont cités pour les fractions ; une
page précise que la partie fractionnaire d'un ordre limite non exécutable
immédiatement peut attendre que l'ordre le devienne. Les ordres « à
l'ouverture » et « à la clôture » ne sont confirmés par aucune page officielle
lue pour les fractions. Les fractions sont annoncées sur les plateformes du
courtier, mais pas par son interface de programmation selon deux pages (une
troisième indique « toutes les plateformes »).

Conséquences, à garder en tête devant tout résultat :

- la sortie au Close de D10 reste la **convention de simulation** ; avec des
  fractions, l'ordre réel le plus proche serait un ordre au marché peu avant
  16:00, à un prix différent du cours de clôture officiel ;
- un stop et un objectif simultanés sur une fraction restent à vérifier sur le
  compte ;
- une exécution automatique par programme n'est pas acquise pour des fractions.

### Données manquantes [CONVENTION]

- Bougie horaire attendue absente ou incomplète, **suivie** d'une bougie
  complète : `NON_EVALUABLE`, motif `BOUGIE_HORAIRE_MANQUANTE`. On ne suppose pas
  que le stop a tenu, et le trade reste dans les statistiques.
- Bougie absente **sans rien après** : les données s'arrêtent là. La position
  reste `OUVERTE`, motif `POSITION_OUVERTE_FIN_DONNEES`. La dernière ligne n'est
  jamais transformée en sortie.
- Close Daily de D10 absent alors que des données plus récentes existent :
  `NON_EVALUABLE`, motif `CLOTURE_D10_MANQUANTE`.
- Une position `NON_EVALUABLE` rend l'equity inconnue : les entrées suivantes
  sont `NON_EVALUABLE`, motif `PORTEFEUILLE_NON_EVALUABLE`.

### Limite de la convention d'entrée

La quantité est calculée sur l'Open, connu au moment où il se produit. Un ordre
réel doit être dimensionné **avant** l'ouverture, sur un prix estimé : la
quantité réelle et le prix obtenu différeront. Avec le retard de 16 minutes des
données gratuites, l'écart sera plus grand encore.

## 10. Journal des positions

Une ligne par entrée acceptée à l'étape 3, quelle que soit son issue.

| Statut | Motifs possibles |
| --- | --- |
| `REFUSEE` | `ENTREE_SOUS_STOP`, `POSITION_DEJA_OUVERTE`, `PAS_DE_POSITION_TAILLE_INSUFFISANTE`, `FONDS_DISPONIBLES_INSUFFISANTS` |
| `NON_EVALUABLE` | `PLUS_BAS_INDISPONIBLE`, `ATR_INDISPONIBLE`, `STOP_NON_POSITIF`, `TAUX_DE_CHANGE_INDISPONIBLE`, `BOUGIE_HORAIRE_MANQUANTE`, `CLOTURE_D10_MANQUANTE`, `PORTEFEUILLE_NON_EVALUABLE` |
| `OUVERTE` | `POSITION_OUVERTE_FIN_DONNEES` |
| `CLOTUREE` | `STOP`, `STOP_GAP`, `CIBLE`, `CIBLE_GAP`, `DUREE_MAX_D10` |

Champs conservés : titre et configuration ; instant du signal, `L`, ATR et sa
date ; stop brut et stop ; instant et prix d'entrée ; distance, objectif brut,
objectif, ratio effectif ; D1 et D10 ; equity, budget, taux de référence et sa
date, soldes EUR et USD avant l'achat, quantité, montant investi, USD convertis
à l'entrée, risque de prix, coûts estimés au stop (dont change), risque prévu,
contrainte qui a limité la quantité ; sortie (instant, bougie, prix, motif,
séance Dn, ambiguïté, objectif touché à l'égalité) ; taux de sortie et sa date,
USD convertis à la sortie ; résultats brut USD, brut EUR, effet de change,
commissions, glissement, coûts de change, coûts totaux, résultat après coûts,
multiples du risque initial ; equity après clôture ; les quatre hypothèses et
la mention « non confirmées ».

Deux compléments accompagnent ce journal :

- le **journal des conversions** : une ligne par conversion réellement simulée
  (instant, titre, achat ou vente, sens, USD, EUR, taux de référence et sa date,
  taux d'exécution simulé, coût) ;
- le **décompte** : nombre d'entrées par statut et par motif, cas ambigus,
  objectifs touchés à l'égalité. Une entrée refusée, ambiguë ou non évaluable
  n'est jamais retirée des comptes.

## 11. Exemples fictifs

Sans coûts, avec 1 USD = 1 EUR pour simplifier : `C = 1 000`, `L = 97`,
`ATR14 = 4`, pas de prix 0,01, `E = 100`.

- `S = 97 − 0,25 × 4 = 96` ; `d = 4` ; `T = 100 + 2 × 4 = 108`.
- `B = 5 EUR`. Quantité théorique : 5 / 4 = 1,25 action. En actions entières :
  1 action, 100 EUR investis, 4 EUR de risque de prix, 8 EUR visés.
- Avec plus de 1 EUR de coûts au stop, 1 action dépasse le budget : refus.
- Une ouverture ultérieure à 90 coûte 10 EUR : le stop à 96 n'a rien plafonné.
- Ouverture d'entrée à 96 ou moins : refus `ENTREE_SOUS_STOP`.
- Bougie avec Low 95 et High 109 : `AMBIGU_INTRABAR`, stop retenu à 96.

## 12. Publications de résultats — NON IMPLÉMENTÉ [À CONFIRMER]

Une position de dix séances peut traverser une publication de résultats, et un
stop ne protège pas d'un gap. Règle **proposée, non validée, non codée** :

- refuser une entrée si une publication connue est prévue entre l'entrée et la
  clôture de D10 ;
- si une publication est annoncée après l'entrée, sortir à la dernière clôture
  régulière qui la précède ;
- calendrier inconnu : la décision qui en dépend est `NON_EVALUABLE`.

Données nécessaires avant tout test historique : les dates de publication
**telles qu'elles étaient annoncées à l'époque**, avec la date de chaque annonce
et le moment de la séance (avant l'ouverture ou après la clôture). Un calendrier
reconstitué aujourd'hui contient des dates connues après coup : un filtre testé
dessus paraîtrait meilleur qu'il ne l'est. Aucune source de ce type n'est
branchée ; **aucun filtre de ce genre n'est appliqué**.

## 13. Interactive Brokers

Caractéristiques générales relevées dans la documentation publique les 15 et
16 novembre 2026. Elles ne décrivent pas le compte de l'utilisateur. Les pages
du courtier refusent la lecture automatique : plusieurs lignes viennent
d'extraits renvoyés par un moteur de recherche, et non de la page entière. Elles
sont à relire sur le site, connecté au compte.

Confirmé par le titulaire le 16 novembre 2026 : compte au comptant, EUR seuls
détenus, fractions activées, conversion automatique utilisée. Inconnu : la
tarification.

**Où lire la tarification.** Portail client du courtier : icône du compte en
haut à droite, puis « Settings », « Account Configuration » (parfois « Account
Settings »), « IBKR Pricing Plan ». La page indique « Fixed » ou « Tiered » pour
les actions. Autre moyen : la commission d'un petit ordre réel sur une action
américaine vaut 1,00 USD en « Fixed » et 0,35 USD en « Tiered ».

| Sujet | Documentation publique | Reste à confirmer pour le compte |
| --- | --- | --- |
| Devise de base | Sert à traduire les relevés et à calculer la marge ; pour un compte au comptant, elle détermine aussi la devise des produits négociables | — |
| Produit d'une vente | Le courtier ne reconvertit pas d'office un solde vers la devise de base ; le client le fait lui-même s'il le souhaite | Confirmé : scénario `usd_conserves` |
| Compte au comptant | Aucun emprunt ; achats avec des liquidités réglées seulement ; règlement des actions américaines le jour ouvré suivant | Heure exacte de disponibilité le jour du règlement |
| Conversion automatique | Pour les comptes au comptant et les achats seulement ; utilise d'abord les fonds dans la devise de l'ordre ; 0,03 % ajouté au taux, sans commission séparée | Confirmé : utilisée |
| Fractions, tarif | Mêmes tarifs que les ordres entiers ; commission d'au moins 0,01 USD ; ordre fractionné d'au moins 0,01 USD | Nombre de décimales accepté |
| Exception d'une entité | L'entité d'Europe centrale convertit chaque opération vers la devise de base le jour même, pour ses comptes au comptant | Entité qui tient le compte |
| Conversion manuelle | 0,20 point de base du montant, minimum 2 USD par ordre ; commission prélevée dans la devise de base | Mode de conversion utilisé |
| Frais | Prélevés dans la devise du produit négocié | — |
| Commission « Fixed » | 0,005 USD par action, minimum 1,00 USD par ordre, plafond 1 % du montant | Formule réellement appliquée |
| Commission « Tiered » | 0,0035 USD par action, minimum 0,35 USD, plus frais de place ; plafond 1 % (0,5 % sur une autre page) | Formule, plafond, frais de place |
| Fractions | Annoncées pour tous les types de compte en Irlande, sur titres éligibles | Activées ? AAPL éligible ? pas de quantité ? |
| Ordres sur fractions | Marché, limite, stop, stop-limite cités ; « la plupart des types d'ordres » sans liste complète ; ordres à l'ouverture ou à la clôture non confirmés | Types d'ordres proposés sur le ticket ; stop et limite simultanés |
| Plateformes | Fractions annoncées sur les plateformes du courtier ; exclues de l'interface de programmation selon deux pages | Plateforme utilisée |
| Règlement | Règlement des actions américaines le jour ouvré suivant ; un compte au comptant achète avec des liquidités réglées ; pages d'âges différents, délais contradictoires | Délai avant de réutiliser le produit d'une vente |

Tant que ces lignes ne sont pas confirmées, aucun résultat n'est présenté comme
réaliste après frais.

Ce que le modèle ne suppose pas : il ne choisit ni le type de compte, ni le
barème, ni le mode de conversion. Il ne modélise ni emprunt, ni intérêts, ni
délai de règlement (section 15).

## 14. Tests

ATR : valeurs calculées à la main, 14 séances insuffisantes, lissage de Wilder.
Stop et objectif : exemple 97/4/100, arrondis vers le bas et vers le haut,
erreurs de représentation décimale, stop figé, entrée sous le stop.
Taille : budget, arrondi vers le bas, commission minimale et plafond, liquidités
insuffisantes, exposition, risque cumulé, refus sans relèvement du risque.
Sorties : stop, objectif, égalités, gap sous le stop, gap au-dessus de
l'objectif, double contact, D10 et séance raccourcie, horloges J et D distinctes,
invalidation du signal sans effet, bougie manquante, fin d'historique.
Causalité : modifier le futur de la bougie d'entrée ne change ni l'entrée ni la
taille ; ajouter des données ne réécrit pas une sortie passée.
Comptabilité : prix, effet de change, coûts et résultat se recoupent avec les flux.
Arrondis : non-régression sur l'entrée réelle à 344,285 (objectif 353,00, et
353,01 pour une entrée à 344,29) ; prix affichés sans arrondi trompeur.
Règlements : achat payé par des USD disponibles sans conversion ; conversion du
seul manque ; vente qui conserve les USD ; réutilisation de ces USD à l'achat
suivant ; vente reconvertie dans le scénario `retour_eur`.
Double comptage : identité comptable dans les deux scénarios ; coûts de change
des positions égaux à ceux du journal des conversions ; coûts estimés au
dimensionnement égaux aux coûts appliqués pour une sortie au stop.
Taux : entrée avant disponibilité (taux de la veille), décision après (taux du
jour), jour sans nouveau taux, heure d'été et d'hiver, sens du taux (division),
taux d'exécution distinct du taux de référence.
Libellés : « résultat brut théorique » sans coûts, « résultat après coûts
simulés » avec ; mention du glissement nul ; décompte des refus et de leurs
motifs.
Tarifs : plancher de 0,01 USD sur un ordre fractionné, exemple du courtier
(0,05 USD pour une demi-action à 10 USD), minimum et frais externes de
« Tiered », glissement en points de base.
Configurations : les deux scénarios de coûts ne diffèrent que par le barème ;
fichier d'exemple valide et sans donnée personnelle ; fichier local exclu de la
publication.
Règlement : vente puis achat le même jour, le lendemain, après un week-end,
après un jour férié de Bourse, après un jour férié bancaire ; achat avec
conversion automatique pendant qu'une vente attend ; entrée non finançable
refusée avec son motif ; soldes comptable, disponible et en attente.
Déclencheur : sept créneaux par séance à partir de 09:30, le dernier de
30 minutes ; un signal tombe toujours sur un créneau horaire.

## 15. Limites et suite

- Aucune hypothèse de coût n'est confirmée ; le glissement est inconnu et vaut
  0 par défaut.
- Chaque sortie est supposée exécutée au prix de la règle (section 9).
- Le taux BCE n'est pas celui du courtier ; il est quotidien et lu avec retard.
- La chronologie à l'intérieur d'une bougie horaire est inconnue.
- **Règlement modélisé par convention.** Le produit d'une vente n'est disponible
  qu'après règlement (`j1_prudent`). L'heure exacte retenue par le courtier et
  le traitement de deux jours fériés bancaires restent des hypothèses.
- **Fonds bloqués par un ordre en attente** : non modélisés, car un achat simulé
  est payé à l'instant où il est décidé. Un courtier peut aussi exiger une
  marge de sécurité sur un ordre au marché converti automatiquement.
- **Aucun emprunt, aucun intérêt** : le compte simulé ne passe jamais en
  négatif, dans aucune devise, conformément à un compte au comptant.
- **Cours ajustés des divisions d'actions.** Avant une division, le cours
  ajusté n'est pas le cours réel de l'époque : le pas de prix de 0,01 USD, le
  nombre d'actions et les commissions par action seraient faussés. Aucun
  backtest ne doit couvrir une date antérieure à la dernière division d'un
  titre sans corriger ce point (voir le protocole).
- **Publications de résultats** : la politique de la section 12 n'est ni
  validée ni appliquée.
- Dividendes, taxes et intérêts sur les liquidités ne sont pas comptés.
- Les cours sont ceux que la source fournit aujourd'hui, pas ceux connus à
  l'époque.

### Inventaire des données accessibles (16 novembre 2026)

Produit par `inventaire_donnees.py`, qui compte des bougies et ne calcule ni
signal ni performance. Source : Alpaca, flux SIP, cours ajustés des divisions
d'actions et non ajustés des dividendes.

| Donnée | Couverture constatée |
| --- | --- |
| Daily, AAPL, NVDA, AVGO | 2 733 séances du 04/01/2016 au 13/11/2026 ; aucune séance NASDAQ manquante |
| Bougies 1 h (assemblées depuis 30 minutes) | Toutes les séances complètes, sauf le 22/02/2016 : un créneau incomplet sur les trois titres |
| Divisions d'actions | AAPL 31/08/2020 (4 pour 1) ; NVDA 20/07/2021 (4 pour 1) et 10/06/2024 (10 pour 1) ; AVGO 15/07/2024 (10 pour 1) |
| Taux BCE EUR/USD | 3 039 taux du 02/01/2015 au 13/11/2026 ; 57 jours de semaine sans taux (jours fériés TARGET) |
| Publications de résultats | Aucune donnée branchée. Le registre officiel de la SEC refuse un client anonyme : il demande une adresse de contact, qui n'a pas été envoyée |

Limites de ces données : elles sont telles que la source les fournit
aujourd'hui, corrections ultérieures comprises ; les dividendes ne sont pas
versés aux positions simulées ; avant le 15/07/2024, les cours ajustés ne sont
pas les cours réels de l'époque.

### Protocole de backtest — hypothèses figées le 16 novembre 2026

Aucun calcul de performance n'a été lancé. Aucune recherche de paramètres n'est
prévue : le protocole mesure la V1 telle qu'elle est écrite, avec 1 000 EUR, ses
coûts simulés et ses contraintes. Tout ce qui suit a été fixé **avant** le
premier calcul.

**1. Données figées.** Les cours bruts des trois titres ont été téléchargés une
fois, le 16 novembre 2026 à 12:35 UTC, et archivés dans `donnees/historique/`.
Un manifeste garde l'empreinte de chaque fichier : une archive modifiée est
refusée, et elle ne peut pas être réécrite. Tous les calculs partiront de
cette archive (`historique.py --verifier` la relit sans réseau).

| Contenu de l'archive | Constat |
| --- | --- |
| Étendue | 04/01/2016 – 30/09/2026 ; 2 702 bougies Daily et 34 986 barres de 30 minutes par titre |
| Bougies Daily manquantes | Aucune, sur les quatre périodes et les trois titres |
| Séances horaires incomplètes | Une seule : le 22/02/2016, pendant la mise en route |
| Divisions d'actions | Les quatre de la table, retrouvées dans les données |
| Bougies Daily incohérentes | 7 séances sur environ 8 000 (voir la règle de nettoyage) |

**2. Périodes [VALIDÉ].** Fixées d'après la seule couverture des données ;
inscrites aussi dans le code (`historique.PERIODES`).

| Période | Dates | Séances | Raison |
| --- | --- | ---: | --- |
| Mise en route | 04/01/2016 – 31/03/2016 | 61 | Historique nécessaire aux moyennes ; contient le seul trou horaire |
| Développement | 01/04/2016 – 28/06/2024 | 2 075 | Sert à vérifier le moteur et à écrire les critères de lecture |
| Tampon, exclu | 01/07/2024 – 31/07/2024 | 22 | Sépare les deux périodes ; contient la dernière division (AVGO, 15/07/2024) |
| **Validation** | **01/08/2024 – 31/08/2026** | **522** | Après la dernière division ; lue une seule fois |
| Déjà vue, exclue | depuis le 01/09/2026 | — | A servi à construire et à contrôler l'outil (entrées du 25/09 et du 16/10) |

Chaque période repart de 1 000 EUR et 0 USD. Une position appartient à la
période de son entrée ; une position encore ouverte à la fin est déclarée
ouverte, jamais clôturée de force. L'archive va jusqu'au 30/09/2026 pour qu'une
position entrée fin août puisse se dénouer. Ces dates ne changent pas après
lecture d'un résultat.

**3. Règle de nettoyage des bougies Daily.** Sur 7 séances, la bougie Daily
contient un plus haut ou un plus bas que les barres de 30 minutes de la séance
régulière ne montrent pas ; le cas le plus net est NVDA le 10/06/2024, jour de
sa division : plus haut Daily 195,95 USD, contre 123,10 dans la séance. Laissée
telle quelle, cette valeur créerait un faux sommet. Règle, fixée d'après la
seule cohérence des données : quand un plus haut ou un plus bas Daily s'écarte
de plus de 0,5 % de celui des barres de 30 minutes, il est remplacé par ce
dernier. L'ouverture et la clôture ne sont jamais modifiées ; l'archive reste
brute ; chaque correction est listée.

| Titre | Séance | Correction | Période |
| --- | --- | --- | --- |
| AAPL | 10/11/2022 | plus bas 139,50 → 140,40 | développement |
| NVDA | 02/02/2023 | plus bas 207,00 → 209,60 | développement |
| NVDA | 10/06/2024 | plus haut 195,95 → 123,10 | développement |
| AVGO | 26/12/2017 | plus haut 262,35 → 258,38 | développement |
| NVDA | 04/09/2024 | plus haut 113,27 → 109,99 | validation |
| NVDA | 31/03/2025 | plus haut 110,955 → 108,96 | validation |
| NVDA | 10/04/2025 | plus bas 99,15 → 103,01 | validation |

**4. Divisions d'actions [VALIDÉ].** Cours continus pour les signaux, cours
réels de l'époque pour chaque position (section 9).

**5. Scénarios de coûts.** Les deux configurations nommées, « Fixed » et
« Tiered », tant que la tarification est inconnue : deux scénarios
explicitement hypothétiques. La configuration théorique est donnée pour
mémoire.

**6. Exécution [VALIDÉ].** Chaque scénario de coûts est calculé dans les deux
scénarios d'exécution :

| Scénario | Glissement | Règlement |
| --- | --- | --- |
| Principal | 2 points de base du prix | Délai en vigueur à la date de la vente |
| Défavorable | 10 points de base du prix | Le même, plus un jour ouvré |

Soit quatre simulations par période, plus la théorique.

**7. Publications de résultats [VALIDÉ : comparer deux versions].** La mesure
de référence est la V1 **sans filtre**. La variante « sans détention pendant
une publication » suit la règle ci-dessous, écrite avant tout test.

- *Information utilisable.* À l'instant d'une décision, seules comptent les
  publications déjà parues à cet instant, avec leur date et leur heure.
- *Date estimée.* La prochaine publication d'un trimestre est estimée à la date
  du même trimestre un an plus tôt, décalée de 364 jours. Fenêtre interdite :
  de 7 jours avant à 7 jours après cette date. La largeur se règle sur les
  seules dates passées, jamais sur les cours.
- *Entrée refusée*, motif `PUBLICATION_ATTENDUE`, si l'une des séances D1 à D10
  tombe dans une fenêtre connue à l'instant de l'entrée.
- *Position existante fermée*, motif `SORTIE_AVANT_PUBLICATION`, à la clôture
  officielle de la dernière séance qui précède une fenêtre, lorsque cette
  fenêtre n'était **pas** connue à l'entrée et le devient pendant la
  détention. Avec des dates seulement estimées, la fenêtre est connue dès
  l'entrée : ce cas ne se produit pas. Il s'appliquera si une source datée des
  annonces de l'entreprise devient disponible.
- *Estimation impossible* (pas de publication connue un an plus tôt) : l'entrée
  est `NON_EVALUABLE`, motif `CALENDRIER_PUBLICATIONS_INCONNU`.
- *Classement a posteriori, pour le diagnostic seulement.* Dans les deux
  versions, les positions qui ont réellement traversé une publication sont
  comptées et isolées. Ce classement utilise une date connue après coup : il
  n'est jamais présenté comme un filtre utilisable à l'époque.

**La variante ne peut pas encore être évaluée**, pour trois raisons :

- aucune date de publication n'est collectée. Le registre de la SEC refuse un
  client anonyme et demande une adresse de contact ; elle n'a pas été envoyée ;
- un dépôt à la SEC (formulaire 8-K, rubrique 2.02) établit quand des résultats
  ont **paru**. Il ne dit pas quand leur date avait été **annoncée** : la date
  d'un dépôt n'est pas une date connue à l'avance. Les documents devront être
  examinés avant de s'y fier ;
- pour AVGO, les dépôts d'avant 2018 sont enregistrés sous d'anciennes sociétés
  du groupe : la continuité de l'historique reste à vérifier.

La règle n'est donc pas codée. La V1 sans filtre peut être mesurée sans
attendre.

**8. Mesures décidées à l'avance**, pour chaque scénario : nombre d'entrées et
décompte complet des refus, cas ambigus, objectifs à l'égalité et
non-évaluables ; positions réduites faute de fonds disponibles ; résultat brut
théorique et résultat après coûts simulés par position ; espérance par position
et son intervalle d'incertitude ; plus forte perte ; plus longue série de
pertes ; drawdown maximal ; coûts rapportés au risque ; durée de détention ;
part du résultat due au change.

**9. Critères de lecture [VALIDÉ le 17 novembre 2026, avant l'ouverture de la
validation].** Rédigés après la période de développement, approuvés par le
titulaire avant toute lecture de la validation :

1. *Échantillon.* En dessous de 20 positions clôturées, aucune conclusion.
2. *Scénario jugé.* `IBKR_CASH_AUTO_FRACTIONS_TIERED`, exécution principale :
   le titulaire a décidé le 16 novembre 2026 de passer son compte en
   tarification « Dégressif » (Tiered). Les quatre autres simulations sont
   données pour information.
3. *Lecture.* Si l'intervalle approximatif de l'espérance par position contient
   zéro, la conclusion est « pas d'avantage démontré », quel que soit le signe
   du total.
4. *Change.* Le résultat de prix et l'effet de change sont lus séparément : un
   gain dû au seul dollar n'est pas un avantage de la stratégie.

Rappel de la période de développement (01/04/2016 – 28/06/2024), scénario
jugé : 112 positions clôturées, espérance −0,02 EUR par position, intervalle
−1,19 à +1,15 EUR, donc pas d'avantage démontré. Contrôle position par position
des cinq journaux : aucune anomalie.

**10. Une seule lecture de la validation.** Si la V1 est modifiée après l'avoir
vue, cette période ne vaut plus validation.

**Validation lue le 17 novembre 2026, une seule fois.** Période 01/08/2024 –
31/08/2026, archive et taux figés, aucune règle modifiée. Contrôle position par
position des cinq journaux : aucune anomalie. Aucune division d'actions dans la
période (facteur 1 partout).

| Simulation | Positions clôturées | Résultat | Espérance par position | Intervalle approximatif |
| --- | ---: | ---: | ---: | --- |
| Brut théorique | 27 | +34,41 EUR | +1,27 EUR (+0,26 R) | −1,46 à +4,01 EUR |
| **« Tiered », exécution principale (jugé)** | **27** | **+10,82 EUR** | **+0,40 EUR (+0,10 R)** | **−1,94 à +2,74 EUR** |
| « Tiered », exécution défavorable | 27 | +3,46 EUR | +0,13 EUR (+0,04 R) | −2,08 à +2,34 EUR |
| « Fixed », exécution principale | 27 | −24,72 EUR | −0,92 EUR (−0,28 R) | −2,64 à +0,81 EUR |
| « Fixed », exécution défavorable | 27 | −29,84 EUR | −1,11 EUR (−0,36 R) | −2,75 à +0,54 EUR |

Application des critères au scénario jugé :

1. 27 positions clôturées : au moins 20, une conclusion est permise.
2. Scénario jugé : « Tiered », exécution principale.
3. L'intervalle (−1,94 à +2,74 EUR) contient zéro : **pas d'avantage démontré**.
4. Résultat de prix +28,55 EUR, effet de change +0,67 EUR, coûts simulés
   18,40 EUR : le résultat ne vient pas du dollar sur cette période.

**Conclusion de la V1.** Sur le développement comme sur la validation, la V1
ne montre pas d'avantage démontré après coûts. Les deux périodes concordent :
un résultat proche de zéro avec le barème « Tiered », négatif avec « Fixed ».
La validation étant lue, toute modification des règles constitue une nouvelle
version, qui demandera une nouvelle période jamais vue pour être évaluée.

Ordre d'exécution : la période de développement d'abord ; puis les critères de
lecture ; puis, une seule fois, la validation.

Encore ouvert : la tarification du compte (les deux scénarios restent
hypothétiques) ; l'accès aux dates de publication pour la variante.

Outils prêts, écrits et testés sans qu'aucun résultat réel ait été calculé :

- `historique.py` : archive figée, cours continus, nettoyage, rapport de
  couverture ;
- `backtest.py` : les cinq simulations d'une période (deux barèmes × deux
  scénarios d'exécution, plus la théorique) et les mesures du point 8. La
  période de validation exige l'option `--ouvrir-la-validation` ;
- taux BCE figés : le fichier `donnees/bce_eurusd_20261115_024314_370946.csv`
  (empreinte SHA-256 commençant par `dbc69f1dddc1bbae`), qui s'arrête au
  13/11/2026.

Un essai purement technique, sans lecture d'aucun résultat, a vérifié que la
chaîne tourne sur l'archive : environ une seconde par année et par titre.

L'objectif personnel (1 000 → 5 000 EUR) n'entre dans aucun de ces choix.

## 16. Sources

- Adam Grimes, « Cutting losses quickly or properly? » :
  <https://adamhgrimes.com/cutting-losses-quickly-properly/>
- Adam Grimes, « Exits: know when to hold 'em, know when to fold 'em » :
  <https://adamhgrimes.com/trade-exits/>
- CME Group, « Proper Position Size » :
  <https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size>
- FINRA, « Stop Orders: Factors to Consider During Volatile Markets » :
  <https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets>
- Interactive Brokers Ireland, commissions actions :
  <https://www.interactivebrokers.ie/en/pricing/commissions-stocks.php>
- Interactive Brokers Ireland, change :
  <https://www.interactivebrokers.ie/en/pricing/commissions-spot-currencies.php>
- Interactive Brokers Ireland, fractions :
  <https://www.interactivebrokers.ie/en/trading/fractional-trading.php>
- Interactive Brokers, ordres sur fractions :
  <https://www.interactivebrokers.com/en/trading/orders/fractional-share-orders.php>
- Interactive Brokers, questions fréquentes sur les fractions :
  <https://www.ibkrguides.com/kb/en-us/fractional-share-trading.htm>
- Interactive Brokers, devise de base :
  <https://www.ibkrguides.com/clientportal/basecurrency.htm>
- Interactive Brokers, mécanique d'un achat en devise étrangère :
  <https://www.interactivebrokers.com/campus/trading-lessons/mechanics-of-an-overseas-trade/>
- Interactive Brokers, questions fréquentes « Products & Exchanges » (conversion automatique) :
  <https://www.interactivebrokers.com/support/faq/articles/614705860>
- Interactive Brokers, configuration du compte (comptant, marge) :
  <https://www.interactivebrokers.com/en/accounts/configuring-your-account.php>
- Interactive Brokers, règlement à un jour :
  <https://www.interactivebrokers.com/campus/traders-insight/securities/stocks/t1-settlement-what-it-means-for-traders-and-investors/>
- Interactive Brokers, compte au comptant (définition) :
  <https://www.interactivebrokers.com/campus/glossary-terms/cash-account/>
- Interactive Brokers, soldes du compte (liquidités réglées) :
  <https://www.ibkrguides.com/traderworkstation/account-balances.htm>
- Interactive Brokers, choix du barème dans le portail client :
  <https://www.ibkrguides.com/clientportal/pricingstructure.htm>
- Interactive Brokers, fiche d'information (fractions) :
  <https://www.interactivebrokers.com/en/general/about/ibkr-fact-sheet.php>
- SEC, taux des frais de transaction pour l'exercice 2026 :
  <https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2>
- FINRA, avis d'information du 17 mars 2026 :
  <https://www.finra.org/rules-guidance/notices/information-notice-20260317>
- DTCC, calendriers des jours fériés et avis de traitement :
  <https://www.dtcc.com/-/media/Files/pdf/2025/10/15/23036-25.pdf>
- Banque centrale européenne, taux de référence :
  <https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html>
- Banque centrale européenne, changement de l'heure de publication (2015) :
  <https://www.ecb.europa.eu/press/pr/date/2015/html/pr151207.en.html>
- SEC, réforme du pas de cotation : <https://www.sec.gov/newsroom/press-releases/2024-137>

Ces sources éclairent la méthode ou les tarifs généraux. Aucune ne valide les
paramètres chiffrés retenus pour cette stratégie.
