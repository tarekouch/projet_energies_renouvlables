import pandas as pd
import numpy as np
import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt

# Chargement des données de la journée type
file_path = "jour_typique.csv"
df = pd.read_csv(file_path)

G = df["irradiance_W_m2"].astype(float).values  # irradiance en W/m²
v = df["wind_speed_m_s"].astype(float).values  # vitesse du vent en m/s
D = df["demand_kWh"].astype(float).values      # demande horaire en kWh
T = len(D)

# Paramètres techniques
eta_p = 0.18    # rendement panneau solaire
A_p = 1.0       # surface d'un panneau [m²]
C_b = 2.4       # capacité d'une batterie [kWh]
SoC_min = 0.20  # état de charge minimum
SoC_max = 0.90  # état de charge maximum
delta_t = 1.0   # pas de temps [h]

# Production solaire unitaire (1 panneau) à chaque heure [kWh]
P_sol_unit = eta_p * A_p * (G / 1000.0) * delta_t

# Courbe de puissance éolienne
P_nom_eol = 100.0  # kW

def wind_power_kw(v_arr):
    p = np.zeros(len(v_arr))
    for i, vi in enumerate(v_arr):
        if vi < 1.0 or vi > 25.0:
            p[i] = 0.0
        elif vi <= 10.0:
            p[i] = 0.9924 * vi**2 + 0.0227 * vi + 0.1667
        else:
            p[i] = P_nom_eol
    return p

W = wind_power_kw(v)

# Modèle Gurobi - autosuffisance sans objectif économique
model = gp.Model("SelfSuffisance_Jour")
model.Params.TimeLimit = 300

# Variables de décision
Np = model.addVar(vtype=GRB.INTEGER, lb=0, name="Np")
Nb = model.addVar(vtype=GRB.INTEGER, lb=0, name="Nb")
S = model.addVars(T + 1, lb=0.0, name="S")
S_plus = model.addVars(T, lb=0.0, name="S_plus")
S_minus = model.addVars(T, lb=0.0, name="S_minus")
curtail = model.addVars(T, lb=0.0, name="curtail")

# Objectif : minimiser le nombre d'unités installées
model.setObjective(
    Np + Nb,
    GRB.MINIMIZE,
)

# Contraintes
model.addConstrs(
    (
        P_sol_unit[t] * Np
        + W[t]
        + S_minus[t]
        - S_plus[t]
        - curtail[t]
        == D[t]
    for t in range(T)),
    name="bilan",
)
model.addConstr(S[0] == 0.45 * C_b * Nb, name="SoC_initial")
model.addConstr(
    S[T] == S[0], name="SoC_final_egal_initial"
)
model.addConstrs(
    (S[t + 1] == S[t] - S_minus[t] + S_plus[t] for t in range(T)),
    name="dynamique",
)

model.addConstrs(
    (S_plus[t] <= C_b * Nb for t in range(T)),
    name="charge_limit",
)
model.addConstrs(
    (S_minus[t] <= C_b * Nb for t in range(T)),
    name="discharge_limit",
)
model.addConstrs(
    (S[t] >= SoC_min * C_b * Nb for t in range(T + 1)),
    name="SoC_min",
)
model.addConstrs(
    (S[t] <= SoC_max * C_b * Nb for t in range(T + 1)),
    name="SoC_max",
)

model.optimize()

if model.Status == GRB.OPTIMAL:
    Np_opt = int(round(Np.X))
    Nb_opt = int(round(Nb.X))
    P_sol_total = P_sol_unit * Np_opt
    curtail_total = sum(curtail[t].X for t in range(T))

    print("\n=== Autosuffisance journée type ===")
    print(f"Nombre de panneaux solaires : {Np_opt}")
    print(f"Nombre de batteries : {Nb_opt}")
    print(f"Production solaire totale : {P_sol_total.sum():.2f} kWh")
    print(f"Production éolienne totale : {W.sum():.2f} kWh")
    print(f"Curtailment total : {curtail_total:.2f} kWh")
    print(f"Capacité totale batterie : {Nb_opt * C_b:.2f} kWh")

    # État de charge
    S_vals = np.array([S[t].X for t in range(T + 1)])
    SoC_pct = S_vals / (C_b * Nb_opt) * 100 if Nb_opt > 0 else np.zeros(T + 1)

    # Graphique production / demande
    hours = np.arange(T)
    plt.figure(figsize=(10, 6))
    plt.plot(hours, D, label="Demande", color="tomato")
    plt.plot(hours, P_sol_total, label="Solaire", color="gold")
    plt.plot(hours, W, label="Éolien", color="steelblue")
    plt.fill_between(hours, 0, P_sol_total + W, color="lightgray", alpha=0.3)
    plt.xlabel("Heure")
    plt.ylabel("kWh")
    plt.title("Journée type - autosuffisance")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("self_suffisance_resultats.png", dpi=150)
    print("Graphique sauvegardé : self_suffisance_resultats.png")

    # Graphique de l'état de charge
    plt.figure(figsize=(10, 5))
    plt.plot(np.arange(T + 1), SoC_pct, color="green", lw=2, label="SoC batterie")
    plt.axhline(SoC_min * 100, color="red", ls="--", lw=1, label=f"SoC min {SoC_min*100:.0f}%")
    plt.axhline(SoC_max * 100, color="orange", ls="--", lw=1, label=f"SoC max {SoC_max*100:.0f}%")
    plt.xlabel("Heure")
    plt.ylabel("SoC [%]")
    plt.title("État de charge des batteries")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("self_suffisance_soc.png", dpi=150)
    plt.show()
    print("Graphique sauvegardé : self_suffisance_soc.png")
else:
    print(f"Optimisation échouée — statut Gurobi : {model.Status}")
