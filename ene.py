import pandas as pd
import numpy as np
import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt

# =============================================================================
# 1. CHARGEMENT ET PREPARATION DES DONNEES
# =============================================================================

# --- Irradiance (W/m²) ---
df_irr = pd.read_csv("irradiance.csv", sep=";")
df_irr["time"] = pd.to_datetime(df_irr["time"])
df_irr = df_irr.sort_values("time").reset_index(drop=True)
G = df_irr["irradiancetotale"].astype(str).str.replace(",", ".").astype(float).values  # KW/m²

# --- Vitesse du vent (m/s) ---
df_wind = pd.read_csv("wind_speed.csv", sep=";")
df_wind["Time"] = pd.to_datetime(df_wind["Time"])
df_wind = df_wind.sort_values("Time").reset_index(drop=True)
df_wind["Wind Speed"] = (
    df_wind["Wind Speed"].astype(str).str.replace(",", ".").astype(float)
)
v = df_wind["Wind Speed"].values  # m/s

# =============================================================================
# 2. PRODUCTION EOLIENNE  (courbe de puissance Hummer H25.0-100kW)
# =============================================================================
# Caractéristiques : D = 25 m, P_nom = 100 kW


P_nom_eol = 100.0   # kW


def wind_power_kw(v_arr):
    p = np.zeros(len(v_arr))
    for i, vi in enumerate(v_arr):
        if vi < 1.0 or vi > 25:
            p[i] = 0.0
        elif vi <= 10.0:
            # Polynôme: 0.9924*v² + 0.0227*v + 0.1667  [kW]
            p[i] = 0.9924 * vi**2 + 0.0227 * vi + 0.1667
        else:
            p[i] = P_nom_eol
    return p

W = wind_power_kw(v)   # kWh produits par l'éolienne à chaque heure (pas = 1h)

# =============================================================================
# 3. DEMANDE ELECTRIQUE DE LA FERME  (kWh/h)
# =============================================================================
# Profil journalier fixe fourni (kWh/h), identique chaque jour de l'année.
# Heure 0h → 23h (24 valeurs, ligne 24 ignorée car identique à 0h).

profil_jour = np.array([
    30, 30, 30, 30, 30, 33,   # 0h - 5h
    35, 40, 45, 50, 45, 40,   # 6h - 11h
    35, 36, 36, 36, 35, 40,   # 12h - 17h
    47, 50, 47, 40, 35, 28,   # 18h - 23h
], dtype=float)               # kWh/h

jours_mois = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

# Répétition sur 365 jours pour obtenir le profil annuel (8760 h)
D = np.tile(profil_jour, 365)

D_annuelle_kWh = D.sum()
print(f"Consommation annuelle : {D_annuelle_kWh:,.0f} kWh")

T = len(D)   # 8760

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
# Le fichier irradiance.csv fournit déjà l'irradiance en kW/m².
P_sol_unit = eta_p * A_p * G * delta_t   # G en kW/m² → kWh

# =============================================================================
# 5. MODELE GUROBI
# =============================================================================
model = gp.Model("Dimensionnement_Ferme")
model.Params.LogToConsole = 1
model.Params.TimeLimit    = 300   # 5 min max

# --- Variables de décision ---
Np  = model.addVar(vtype=GRB.INTEGER, lb=0, name="Np")   # nb panneaux
Nb  = model.addVar(vtype=GRB.INTEGER, lb=0, name="Nb")   # nb batteries

S      = model.addVars(T + 1, lb=0.0, name="S")          # stock batterie [kWh]
S_plus = model.addVars(T,     lb=0.0, name="S_plus")     # énergie chargée [kWh]
S_minus = model.addVars(T,  lb=0.0, name="S_minus")   # énergie soutirée [kWh]
curtail = model.addVars(T,  lb=0.0, name="curtail")   # surplus effacé (curtailment) [kWh]

# --- Fonction objectif ---
# Minimisation du coût d'investissement (pondération par coût unitaire)
# et pénalisation du curtailment.
# Coûts indicatifs : panneau ~200 €, batterie ~500 €, curtailment ~1 €/kWh
# Changez si vous avez des données précises.
cout_panneau   = 200  # € par panneau
cout_batterie  = 440  # € par batterie
cout_curtail   = 10   # € par kWh excédentaire effacé

model.setObjective(
    cout_panneau * Np + cout_batterie * Nb ,
    GRB.MINIMIZE
)

# --- Contraintes ---

# C1 : Bilan énergétique — production + décharge = demande + charge + curtail
model.addConstrs(
    (P_sol_unit[t] * Np + W[t] + S_minus[t] - S_plus[t] - curtail[t] >=D[t]
     for t in range(T)),
    name="bilan"
)

# Fixer l'état de charge initial à 50% de la capacité utile
model.addConstr(S[0] == 0.50 * C_b * Nb, name="SoC_initial")
model.addConstr(Np  <= 490, name="limite de panneaux")  # pour éviter que le modèle n'exploite un panneau sans batterie
# C2 : Dynamique du stock
model.addConstrs(
    (S[t + 1] == S[t] - S_minus[t] + S_plus[t]
     for t in range(T)),
    name="dynamique"
)
# C2b : état de charge final identique à l'initial pour l'équilibre annuel
# model.addConstr(S[T] == 0.50 * C_b * Nb, name="SoC_final")
# C2c : Limites de charge/décharge par batterie
model.addConstrs(
    (S_plus[t] <= C_b * Nb for t in range(T)),
    name="charge_limit"
)
model.addConstrs(
    (S_minus[t] <= C_b * Nb for t in range(T)),
    name="discharge_limit"
)
model.addConstr(Nb<=1000, name="limite de batteries")  # pour éviter que le modèle n'exploite une batterie sans panneau
# C3 : Bornes état de charge
model.addConstrs(
    (S[t] >= SoC_min * C_b * Nb for t in range(T + 1)),
    name="SoC_min"
)
model.addConstrs(
    (S[t] <= SoC_max * C_b * Nb for t in range(T + 1)),
    name="SoC_max"
)



# --- Résolution ---
model.optimize()

# =============================================================================
# 6. RESULTATS
# =============================================================================
if model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT):
    Np_opt = int(round(Np.X))
    Nb_opt = int(round(Nb.X))
    cout_total = model.ObjVal

    print("\n" + "=" * 50)
    print("       RESULTATS DE L'OPTIMISATION")
    print("=" * 50)
    print(f"  Nombre de panneaux solaires  : {Np_opt}")
    print(f"  Nombre de batteries          : {Nb_opt}")
    print(f"  Surface solaire totale       : {Np_opt} m²")
    print(f"  Capacité batterie totale     : {Nb_opt * C_b:.1f} kWh")
    print(f"  SoC utile                    : [{SoC_min*100:.0f}% – {SoC_max*100:.0f}%]  "
          f"→ {Nb_opt * C_b * (SoC_max - SoC_min):.1f} kWh utiles")
    print(f"  Coût d'investissement estimé : {cout_total:,.0f} €")
    print("=" * 50)

    # --- Production annuelle ---
    P_sol_total = P_sol_unit * Np_opt
    print(f"\n  Production solaire annuelle  : {P_sol_total.sum():,.0f} kWh")
    print(f"  Production éolienne annuelle : {W.sum():,.0f} kWh")
    print(f"  Consommation annuelle        : {D.sum():,.0f} kWh")

    # ==========================================================================
    # 7. VISUALISATION
    # ==========================================================================
    S_vals = np.array([S[t].X for t in range(T + 1)])

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
    fig.suptitle(
        f"Dimensionnement ferme Estagel — {Np_opt} panneaux, {Nb_opt} batteries",
        fontsize=13, fontweight="bold"
    )

    # Sous-figure 1 : Puissances sur la semaine type (été + hiver)
    ax = axes[0]
    semaines = {"Hiver (jan)": range(0, 168), "Été (jul)": range(4320, 4488)}
    colors = {"Solaire": "gold", "Éolienne": "steelblue", "Demande": "tomato"}
    for nom, idx in semaines.items():
        idx = list(idx)
        ax.plot(range(len(idx)), P_sol_total[idx], label="Solaire" if nom == "Hiver (jan)" else "_",
                color="gold", alpha=0.8)
        ax.plot(range(len(idx)), W[idx], label="Éolienne" if nom == "Hiver (jan)" else "_",
                color="steelblue", alpha=0.8)
        ax.plot(range(len(idx)), D[idx], label="Demande" if nom == "Hiver (jan)" else "_",
                color="tomato", lw=1.5)
        break   # on affiche seulement hiver pour lisibilité
    ax.set_title("Puissances – semaine de janvier (168 h)")
    ax.set_ylabel("kWh/h")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Sous-figure 2 : État de charge annuel
    ax = axes[1]
    ax.plot(S_vals[:-1] / (C_b * Nb_opt) * 100, color="green", lw=0.7, alpha=0.9)
    ax.axhline(SoC_min * 100, color="red",   ls="--", lw=1, label=f"SoC min {SoC_min*100:.0f}%")
    ax.axhline(SoC_max * 100, color="orange",ls="--", lw=1, label=f"SoC max {SoC_max*100:.0f}%")
    ax.set_title("État de charge des batteries (annuel)")
    ax.set_ylabel("SoC [%]")
    ax.set_xlabel("Heure de l'année")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Sous-figure 3 : Bilan mensuel
    ax = axes[2]
    mois_labels = ["Jan","Fév","Mar","Avr","Mai","Jun",
                   "Jul","Aoû","Sep","Oct","Nov","Déc"]
    prod_sol_m, prod_eol_m, dem_m = [], [], []
    h = 0
    for m in range(12):
        nh = jours_mois[m] * 24
        prod_sol_m.append(P_sol_total[h:h+nh].sum())
        prod_eol_m.append(W[h:h+nh].sum())
        dem_m.append(D[h:h+nh].sum())
        h += nh
    x = np.arange(12)
    w = 0.3
    ax.bar(x - w, prod_sol_m, w, label="Solaire", color="gold")
    ax.bar(x,     prod_eol_m, w, label="Éolienne",color="steelblue")
    ax.bar(x + w, dem_m,      w, label="Demande", color="tomato")
    ax.set_xticks(x)
    ax.set_xticklabels(mois_labels)
    ax.set_title("Bilan mensuel")
    ax.set_ylabel("kWh")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig("bilan_ferme.png", dpi=150)
    plt.show()
    print("\nGraphique sauvegardé : bilan_ferme.png")

else:
    print(f"Optimisation échouée — statut Gurobi : {model.Status}")