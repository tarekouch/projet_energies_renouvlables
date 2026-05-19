# Modélisation du dimensionnement solaire et batteries

Ce document explique en détail le modèle d’optimisation implémenté dans `ene.py` pour dimensionner des panneaux solaires et des batteries dans une ferme agricole avec une production éolienne existante.

---

## 1. Objectif du modèle

L’objectif est de minimiser le coût d’investissement total de l’installation en choisissant :

- le nombre de panneaux solaires `Np`
- le nombre de batteries `Nb`

Le coût est modélisé de manière simplifiée comme :

```python
cout_total = 200 * Np + 440 * Nb
```

Ces coefficients sont indicatifs et doivent être ajustés si des données réelles sont disponibles.

---

## 2. Données d’entrée

### 2.1. Données solaires

- Le fichier `irradiance.csv` contient les valeurs horaires d’irradiation `irradiancetotale`.
- Dans le script, cette colonne est convertie en valeurs numériques.
- Le code suppose que l’unité est déjà en `kW/m²`.

La production solaire unitaire d’un panneau est calculée comme :

```python
P_sol_unit = eta_p * A_p * G * delta_t
```

avec :

- `eta_p = 0.18` : rendement du panneau
- `A_p = 1.0 m²` : surface d’un panneau
- `G` : irradiance horaire en `kW/m²`
- `delta_t = 1 h`

Cette expression donne la production horaire d’un panneau en kWh.

### 2.2. Données éoliennes

- Le fichier `wind_speed.csv` contient la vitesse du vent horaire.
- La fonction `wind_power_kw(v_arr)` convertit la vitesse en puissance produite.

La puissance est modélisée par une courbe simplifiée :

- `v < 1.0` ou `v > 25` → 0 kW
- `1.0 <= v <= 10.0` → polynôme quadratique
- `v > 10.0` → puissance nominale `100 kW`

La production horaire de l’éolienne est stockée dans `W`.

### 2.3. Consommation électrique

- La ferme a un profil journalier fixe `profil_jour` défini sur 24 heures.
- Ce profil est répété 365 fois pour obtenir la demande annuelle `D` (8760 heures).

Le modèle vérifie ensuite la consommation annuelle totale :

```python
D_annuelle_kWh = D.sum()
```

---

## 3. Variables de décision

Le modèle utilise les variables suivantes :

- `Np` : nombre entier de panneaux solaires
- `Nb` : nombre entier de batteries
- `S[t]` : stockage en batterie à l’heure `t` (kWh)
- `S_plus[t]` : énergie chargée dans la batterie à l’heure `t` (kWh)
- `S_minus[t]` : énergie déchargée de la batterie à l’heure `t` (kWh)
- `curtail[t]` : énergie non utilisée et effacée à l’heure `t` (kWh)

Les variables `S_plus` et `S_minus` sont continues et non négatives.

---

## 4. Contraintes du modèle

### 4.1. Bilan énergétique horaire

Pour chaque heure `t`, le modèle impose :

```python
P_sol_unit[t] * Np + W[t] + S_minus[t] - S_plus[t] - curtail[t] == D[t]
```

Cette contrainte signifie que la production solaire, la production éolienne et l’énergie batteries déchargée doivent couvrir la demande, en tenant compte :

- de la charge batterie (`S_plus[t]`) qui consomme de l’énergie,
- du curtailment (`curtail[t]`) qui représente l’énergie excédentaire non utilisée.

### 4.2. Dynamique de l’état de charge

Le stock de batterie évolue selon :

```python
S[t + 1] == S[t] - S_minus[t] + S_plus[t]
```

avec un état initial fixé à 50 % de la capacité totale :

```python
S[0] == 0.50 * C_b * Nb
```

et un état final identique à l’état initial pour assurer un cycle annuel équilibré :

```python
S[T] == 0.50 * C_b * Nb
```

### 4.3. Limites de charge et décharge

Chaque heure, la charge et la décharge sont limitées par la capacité totale de batterie :

```python
S_plus[t] <= C_b * Nb
S_minus[t] <= C_b * Nb
```

Ceci est une approximation importante : elle empêche une charge ou décharge instantanée supérieure à la capacité énergétique totale installée.

### 4.4. Bornes sur l’état de charge

L’état de charge de la batterie est contraint entre 20 % et 90 % de capacité :

```python
S[t] >= SoC_min * C_b * Nb
S[t] <= SoC_max * C_b * Nb
```

avec `SoC_min = 0.20` et `SoC_max = 0.90`.

---

## 5. Paramètres techniques

- `eta_p = 0.18` : rendement du panneau solaire
- `A_p = 1.0 m²` : surface d’un panneau
- `C_b = 2.4 kWh` : capacité d’une batterie
- `SoC_min = 0.20`
- `SoC_max = 0.90`
- `delta_t = 1.0 h`

Ces valeurs définissent la performance et les contraintes du système.

---

## 6. Optimisation

Le modèle est résolu avec Gurobi en minimisant :

```python
cout_panneau * Np + cout_batterie * Nb
```

avec un temps limite fixé à 300 secondes.

---

## 7. Résultats affichés

Le script affiche :

- nombre de panneaux solaires `Np`
- nombre de batteries `Nb`
- surface solaire totale en m²
- capacité batterie totale en kWh
- capacité utile entre SoC_min et SoC_max
- coût d’investissement estimé
- production solaire annuelle
- production éolienne annuelle
- consommation annuelle

Il génère également un graphique avec :

- puissances sur une semaine-type
- état de charge annuel
- bilan mensuel solaire / éolien / demande

---

## 8. Observations et limites du modèle

### 8.1. Limites actuelles

- Le coût du panneau et de la batterie est fixé de façon simplifiée.
- La puissance de charge/décharge est limitée par la capacité totale, mais pas par une puissance maximale réelle spécifique.
- Le curtailment est autorisé sans coût supplémentaire.
- Les pertes de conversion et les rendements batterie ne sont pas modélisés.
- L’éolienne est traitée comme une source fixe, sans décision de dimensionnement.

### 8.2. Améliorations possibles

- introduire des coûts différents pour l’éolien si l’on veut dimensionner plusieurs sources,
- modéliser la puissance maximale d’entrée/sortie de la batterie en kW,
- ajouter des rendements charge/décharge,
- autoriser l’export réseau ou la curtailment avec coût,
- utiliser des données de production solaire et éolienne plus détaillées.

---

## 9. Notes pratiques

- Si le fichier `irradiance.csv` a une unité différente de `kW/m²`, il faut corriger la conversion de `P_sol_unit`.
- Si la batterie a une capacité par unité différente, modifier `C_b`.
- Si le profil de demande change, ajuster `profil_jour`.

---

## 10. Fichiers clés

- `ene.py` : script principal du modèle.
- `irradiance.csv` : données d’irradiation solaire horaires.
- `wind_speed.csv` : données de vitesse du vent horaires.
