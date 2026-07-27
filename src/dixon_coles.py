"""
Modello predittivo Dixon-Coles per il calcio.
Risolve il problema dei pareggi sottostimati del Poisson puro.

Formula:
  P(X=x, Y=y) = Poisson(x, λh) * Poisson(y, λa) * τ(x,y,λh,λa,ρ)

dove τ è il fattore di correzione per la dipendenza:
  τ(0,0) = 1 - λh*λa*ρ
  τ(1,0) = 1 + λh*ρ
  τ(0,1) = 1 + λa*ρ
  τ(1,1) = 1 - ρ
  τ(x,y) = 1 altrimenti

ρ tipico per il calcio: -0.05 ~ -0.15 (negativo = più pareggi del previsto)
"""
import math
import json
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

# Parametri di lega (gol medi per partita, stimati da dati storici)
LEAGUE_AVG_GF = {
    "PL": 1.52, "ELC": 1.48, "SA": 1.48, "PD": 1.55,
    "BL1": 1.58, "FL1": 1.42, "DED": 1.65, "PPL": 1.45,
    "CL": 1.55, "EL": 1.50, "ECL": 1.45, "BSA": 1.38,
    "ALL": 1.35, "ELI": 1.55, "VEIK": 1.40,
}

LEAGUE_AVG_GA = {
    "PL": 1.20, "ELC": 1.25, "SA": 1.15, "PD": 1.18,
    "BL1": 1.22, "FL1": 1.18, "DED": 1.30, "PPL": 1.20,
    "CL": 1.20, "EL": 1.22, "ECL": 1.25, "BSA": 1.15,
    "ALL": 1.20, "ELI": 1.25, "VEIK": 1.25,
}

# Rho per lega (stimato empiricamente)
LEAGUE_RHO = {
    "PL": -0.075, "ELC": -0.080, "SA": -0.070, "PD": -0.065,
    "BL1": -0.060, "FL1": -0.075, "DED": -0.070, "PPL": -0.080,
    "CL": -0.050, "EL": -0.055, "ECL": -0.060, "BSA": -0.085,
    "ALL": -0.090, "ELI": -0.075, "VEIK": -0.080,
}


def tau(x, y, lam_h, lam_a, rho):
    """Fattore di correzione Dixon-Coles."""
    if x == 0 and y == 0:
        return max(0.1, 1.0 - lam_h * lam_a * rho)
    elif x == 0 and y == 1:
        return max(0.1, 1.0 + lam_h * rho)
    elif x == 1 and y == 0:
        return max(0.1, 1.0 + lam_a * rho)
    elif x == 1 and y == 1:
        return max(0.1, 1.0 - rho)
    return 1.0


def dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7):
    """
    Calcola la matrice di probabilità P(home=x, away=y).
    Ritorna dict {(x,y): prob} e probabilità aggregate.
    """
    raw = {}
    total = 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson.pmf(h, lam_h) * poisson.pmf(a, lam_a) * tau(h, a, lam_h, lam_a, rho)
            raw[(h, a)] = p
            total += p

    # Normalizza
    probs = {k: v / total for k, v in raw.items()}

    # Aggregati
    p1 = sum(p for (h, a), p in probs.items() if h > a)
    px = sum(p for (h, a), p in probs.items() if h == a)
    p2 = sum(p for (h, a), p in probs.items() if h < a)
    p_over = sum(p for (h, a), p in probs.items() if h + a >= 3)
    p_gg = sum(p for (h, a), p in probs.items() if h >= 1 and a >= 1)

    # Top risultati esatti
    top = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:5]
    top_exact = [(f"{h}-{a}", p) for (h, a), p in top]

    # Distribuzione gol totali
    dist = {}
    for g in range(max_goals + 1):
        if g < max_goals:
            dist[g] = sum(p for (h, a), p in probs.items() if h + a == g)
        else:
            dist[f"{g}+"] = sum(p for (h, a), p in probs.items() if h + a >= g)

    return {
        "matrix": probs,
        "p1": p1, "px": px, "p2": p2,
        "p_over25": p_over, "p_under25": 1 - p_over,
        "p_gg": p_gg, "p_ng": 1 - p_gg,
        "top_exact": top_exact,
        "total_goals_dist": dist,
        "lambda_h": lam_h, "lambda_a": lam_a, "rho": rho
    }


def compute_lambdas(home_stats, away_stats, elo_h, elo_a, league_id, 
                    home_advantage=0.15, form_weight=0.08):
    """
    Calcola λ casa e λ trasferta partendo da:
    - Statistiche gol fatti/subiti della squadra
    - Rating Elo relativo
    - Forma recente (W=+1, D=0, L=-1)
    - Vantaggio campo
    """
    avg_gf = LEAGUE_AVG_GF.get(league_id, 1.45)
    avg_ga = LEAGUE_AVG_GA.get(league_id, 1.20)

    # Forza attacco/difesa
    home_attack = home_stats.get("gf_pg", avg_gf) / avg_gf
    home_defense = home_stats.get("ga_pg", avg_ga) / avg_ga
    away_attack = away_stats.get("gf_pg", avg_gf) / avg_gf
    away_defense = away_stats.get("ga_pg", avg_ga) / avg_ga

    # Elo factor: differenza normalizzata
    elo_diff = elo_h - elo_a
    elo_factor_h = 1.0 + (elo_diff / 400) * 0.3
    elo_factor_a = 1.0 - (elo_diff / 400) * 0.3

    # Forma
    form_map = {"W": 1.0, "D": 0.0, "L": -1.0}
    def form_bonus(form_str):
        if not form_str:
            return 1.0
        scores = [form_map.get(c, 0) for c in form_str[-5:]]
        avg = sum(scores) / len(scores) if scores else 0
        return 1.0 + avg * form_weight

    form_h = form_bonus(home_stats.get("form", ""))
    form_a = form_bonus(away_stats.get("form", ""))

    # Lambda base
    lam_h = avg_gf * home_attack * away_defense * elo_factor_h * form_h * (1 + home_advantage)
    lam_a = avg_gf * away_attack * home_defense * elo_factor_a * form_a

    # Clip realistici
    lam_h = max(0.3, min(lam_h, 4.0))
    lam_a = max(0.3, min(lam_a, 3.5))

    return lam_h, lam_a


def calibrate_with_odds(lam_h, lam_a, odds, weight=0.65):
    """
    Calibra λ con le quote di mercato.
    Se le quote sono disponibili, fonde modello statistico e mercato.
    """
    if not odds or not odds.get("1") or not odds.get("X") or not odds.get("2"):
        return lam_h, lam_a

    # Probabilità implicite de-marginate
    q1, qx, q2 = odds["1"], odds["X"], odds["2"]
    raw = [1/q1, 1/qx, 1/q2]
    margin = sum(raw)
    p1_mkt, px_mkt, p2_mkt = [r / margin for r in raw]

    # Da probabilità 1X2 a λ: usiamo approssimazione Skellam
    # P(home win) ≈ P(H-A > 0) con H~Poisson(λh), A~Poisson(λa)
    # Per semplicità, usiamo ricerca numerica per trovare λ che matchano meglio

    def brier(params):
        lh, la = params
        if lh <= 0 or la <= 0:
            return 10
        rho = -0.07
        res = dixon_coles_matrix(lh, la, rho, max_goals=7)
        return (res["p1"] - p1_mkt)**2 + (res["px"] - px_mkt)**2 + (res["p2"] - p2_mkt)**2

    # Ricerca locale attorno ai λ statistici
    best = None
    best_score = float('inf')
    for scale_h in [0.7, 0.85, 1.0, 1.15, 1.3]:
        for scale_a in [0.7, 0.85, 1.0, 1.15, 1.3]:
            score = brier((lam_h * scale_h, lam_a * scale_a))
            if score < best_score:
                best_score = score
                best = (lam_h * scale_h, lam_a * scale_a)

    if best:
        lam_h_mkt, lam_a_mkt = best
        # Fusione pesata
        lam_h = (1 - weight) * lam_h + weight * lam_h_mkt
        lam_a = (1 - weight) * lam_a + weight * lam_a_mkt

    return max(0.3, lam_h), max(0.3, lam_a)


if __name__ == "__main__":
    # Test rapido
    res = dixon_coles_matrix(1.6, 1.2, -0.07)
    print(f"1: {res['p1']:.1%} | X: {res['px']:.1%} | 2: {res['p2']:.1%}")
    print(f"Over 2.5: {res['p_over25']:.1%} | GG: {res['p_gg']:.1%}")
    print("Top esatti:", res["top_exact"])
