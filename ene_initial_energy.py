import pandas as pd
import numpy as np
import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt

# Script dérivé de `ene.py` mais avec énergie initiale absolue (kWh)

# =============================================================================
# 1. CHARGEMENT ET PREPARATION DES DONNEES
# =============================================================================

# --- Irradiance (kW/m²) ---
df_irr = pd.read_csv("irradiance.csv", sep=";")
df_irr["time"] = pd.to_datetime(df_irr["time"])
df_irr = df_irr.sort_values("time").reset_index(drop=True)
G = df_irr["irradiancetotale"].astype(str).str.replace(",", ".").astype(float).values  # kW/m²

# --- Vitesse du vent (m/s) ---
df_wind = pd.read_csv("wind_speed.csv", sep=";")
df_wind["Time"] = pd.to_datetime(df_wind["Time"])
df_wind = df_wind.sort_values("Time").reset_index(drop=True)
df_wind["Wind Speed"] = (
    df_wind["Wind Speed"].astype(str).str.replace(",", ".").astype(float)
)
v = df_wind["Wind Speed"].values  # m/s

# =============================================================================
# 2. PRODUCTION EOLIENNE
# =============================================================================
P_nom_eol = 100.0   # kW

def wind_power_kw(v_arr):
    p = np.zeros(len(v_arr))
    for i, vi in enumerate(v_arr):
        if vi < 1.0 or vi > 25:
            p[i] = 0.0
        elif vi <= 10.0:
            p[i] = 0.9924 * vi**2 + 0.0227 * vi + 0.1667
        else:
            p[i] = P_nom_eol
    return p

W = wind_power_kw(v)   # kWh/h

# =============================================================================
# 3. DEMANDE ELECTRIQUE
# =============================================================================
profil_jour = np.array([
    30, 30, 30, 30, 30, 33,
    35, 40, 45, 50, 45, 40,
    35, 36, 36, 36, 35, 40,
    47, 50, 47, 40, 35, 28,
], dtype=float)
jours_mois = np.array([31,28,31,30,31,30,31,31,30,31,30,31])
D = np.tile(profil_jour, 365)
T = len(D)

# =============================================================================
# 4. PARAMETRES TECHNIQUES
# =============================================================================
eta_p       = 0.18    # rendement panneau solaire
A_p         = 1.0     # surface d'un panneau [m²]
C_b         = 2.4     # capacité d'une batterie [kWh]
SoC_min     = 0.20    # état de charge minimum
SoC_max     = 0.90    # état de charge maximum
delta_t     = 1.0     # pas de temps [h]

# Production solaire unitaire (1 panneau) à chaque heure [kWh]
P_sol_unit = eta_p * A_p * G * delta_t   # G en kW/m² → kWh

# =============================================================================
# 5. PARAMETRE: ENERGIE INITIALE ABSOLUE
# =============================================================================
# Fixer ici l'énergie initiale en kWh (ex: 10 kWh). Le modèle ajustera Nb
# pour que SoC_min * C_b * Nb <= S_initial_kWh <= SoC_max * C_b * Nb.
S_initial_kWh = 10.0

# =============================================================================
# 6. MODELE GUROBI
# =============================================================================
model = gp.Model("Dimensionnement_Ferme_init_energy")
model.Params.LogToConsole = 1
model.Params.TimeLimit    = 300

# Variables de décision
Np  = model.addVar(vtype=GRB.INTEGER, lb=0, name="Np")
Nb  = model.addVar(vtype=GRB.INTEGER, lb=0, name="Nb")

S      = model.addVars(T + 1, lb=0.0, name="S")
S_plus = model.addVars(T,     lb=0.0, name="S_plus")
S_minus = model.addVars(T,  lb=0.0, name="S_minus")
curtail = model.addVars(T,  lb=0.0, name="curtail")

# Coûts (gardés pour objectif de minimisation économique)
cout_panneau   = 200
cout_batterie  = 440
cout_curtail   = 10

model.setObjective(
    cout_panneau * Np + cout_batterie * Nb + cout_curtail * gp.quicksum(curtail[t] for t in range(T)),
    GRB.MINIMIZE
)

# Contraintes
model.addConstrs(
    (P_sol_unit[t] * Np + W[t] + S_minus[t] - S_plus[t] - curtail[t] == D[t]
     for t in range(T)),
    name="bilan"
)

# Remplacer la contrainte SoC initial en pourcentage par une valeur absolue
model.addConstr(S[0] == S_initial_kWh, name="SoC_initial_absolute")
# (Option B) On supprime la contrainte finale S[T] == S[0] pour ne pas imposer
# que l'état final soit identique à l'état initial sur l'année.

# Limites et dynamique
model.addConstr(Np  <= 490, name="limite_de_panneaux")
model.addConstrs(
    (S[t + 1] == S[t] - S_minus[t] + S_plus[t]
     for t in range(T)),
    name="dynamique"
)
model.addConstrs(
    (S_plus[t] <= C_b * Nb for t in range(T)),
    name="charge_limit"
)
model.addConstrs(
    (S_minus[t] <= C_b * Nb for t in range(T)),
    name="discharge_limit"
)
model.addConstrs(
    (S[t] >= SoC_min * C_b * Nb for t in range(T + 1)),
    name="SoC_min"
)
model.addConstrs(
    (S[t] <= SoC_max * C_b * Nb for t in range(T + 1)),
    name="SoC_max"
)

# =============================================================================
# 7. Résolution
# =============================================================================
model.optimize()

# =============================================================================
# 8. Résultats
# =============================================================================
if model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT):
    Np_opt = int(round(Np.X))
    Nb_opt = int(round(Nb.X))
    cout_total = model.ObjVal

    print("\n" + "=" * 50)
    print("       RESULTATS DE L'OPTIMISATION (Initial energy)")
    print("=" * 50)
    print(f"  Energy initiale fixée : {S_initial_kWh:.1f} kWh")
    print(f"  Nombre de panneaux solaires  : {Np_opt}")
    print(f"  Nombre de batteries          : {Nb_opt}")
    print(f"  Capacité batterie totale     : {Nb_opt * C_b:.1f} kWh")
    print(f"  SoC utile                    : [{SoC_min*100:.0f}% – {SoC_max*100:.0f}%]  "
          f"→ {Nb_opt * C_b * (SoC_max - SoC_min):.1f} kWh utiles")
    print(f"  Coût d'investissement estimé : {cout_total:,.0f} €")
    print("=" * 50)

    P_sol_total = P_sol_unit * Np_opt
    print(f"\n  Production solaire annuelle  : {P_sol_total.sum():,.0f} kWh")
    print(f"  Production éolienne annuelle : {W.sum():,.0f} kWh")
    print(f"  Consommation annuelle        : {D.sum():,.0f} kWh")

    # Visualisation SoC
    S_vals = np.array([S[t].X for t in range(T + 1)])
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(S_vals, label='S [kWh]')
    ax.axhline(SoC_min * C_b * Nb_opt, color='red', ls='--', label='SoC min (kWh)')
    ax.axhline(SoC_max * C_b * Nb_opt, color='orange', ls='--', label='SoC max (kWh)')
    ax.set_xlabel('Heure')
    ax.set_ylabel('Stock batterie [kWh]')
    ax.set_title('État de charge (kWh) - Initial energy fixed')
    ax.legend()
    plt.tight_layout()
    plt.savefig('bilan_initial_energy.png', dpi=150)
    plt.show()
    print('\nGraphique sauvegardé : bilan_initial_energy.png')
else:
    print(f"Optimisation échouée — statut Gurobi : {model.Status}")
    try:
        model.computeIIS()
        # Write the full model in ILP format and the IIS-marked model (ILP will contain IIS markers)
        ilp_file = 'ene_initial_energy.ilp'
        model.write(ilp_file)
        print(f'Model written to {ilp_file} (contient les informations IIS) — inspectez les contraintes marquées par IIS)')
    except Exception as e:
        print('Échec du calcul de l\'IIS :', e)
