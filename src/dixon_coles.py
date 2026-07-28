"""Modello Dixon-Coles per il calcio."""
import math
from scipy.stats import poisson

LEAGUE_AVG_GF = {"PL": 1.52, "ELC": 1.48, "SA": 1.48, "PD": 1.55, "BL1": 1.58,
    "FL1": 1.42, "DED": 1.65, "PPL": 1.45, "CL": 1.55, "EL": 1.50,
    "ECL": 1.45, "BSA": 1.38, "ALL": 1.35, "ELI": 1.55, "VEIK": 1.40}

LEAGUE_AVG_GA = {"PL": 1.20, "ELC": 1.25, "SA": 1.15, "PD": 1.18, "BL1": 1.22,
    "FL1": 1.18, "DED": 1.30, "PPL": 1.20, "CL": 1.20, "EL": 1.22,
    "ECL": 1.25, "BSA": 1.15, "ALL": 1.20, "ELI": 1.25, "VEIK": 1.25}

LEAGUE_RHO = {"PL": -0.075, "ELC": -0.080, "SA": -0.070, "PD": -0.065,
    "BL1": -0.060, "FL1": -0.075, "DED": -0.070, "PPL": -0.080,
    "CL": -0.050, "EL": -0.055, "ECL": -0.060, "BSA": -0.085,
    "ALL": -0.090, "ELI": -0.075, "VEIK": -0.080}


def tau(x, y, lam_h, lam_a, rho):
    if x == 0 and y == 0: return max(0.1, 1.0 - lam_h * lam_a * rho)
    elif x == 0 and y == 1: return max(0.1, 1.0 + lam_h * rho)
    elif x == 1 and y == 0: return max(0.1, 1.0 + lam_a * rho)
    elif x == 1 and y == 1: return max(0.1, 1.0 - rho)
    return 1.0


def dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7):
    raw = {}
    total = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson.pmf(h, lam_h) * poisson.pmf(a, lam_a) * tau(h, a, lam_h, lam_a, rho)
            raw[(h, a)] = p
            total += p

    probs = {k: v / total for k, v in raw.items()}
    p1 = sum(p for (h, a), p in probs.items() if h > a)
    px = sum(p for (h, a), p in probs.items() if h == a)
    p2 = sum(p for (h, a), p in probs.items() if h < a)
    p_over = sum(p for (h, a), p in probs.items() if h + a >= 3)
    p_gg = sum(p for (h, a), p in probs.items() if h >= 1 and a >= 1)
    top = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:5]
    top_exact = [(f"{h}-{a}", p) for (h, a), p in top]

    dist = {}
    for g in range(max_goals + 1):
        if g < max_goals:
            dist[g] = sum(p for (h, a), p in probs.items() if h + a == g)
        else:
            dist[f"{g}+"] = sum(p for (h, a), p in probs.items() if h + a >= g)

    return {"p1": p1, "px": px, "p2": p2, "p_over25": p_over, "p_under25": 1 - p_over,
            "p_gg": p_gg, "p_ng": 1 - p_gg, "top_exact": top_exact,
            "total_goals_dist": dist, "lamH": lam_h, "lamA": lam_a, "rho": rho}


def compute_lambdas(home_stats, away_stats, elo_h, elo_a, league_id, home_adv=0.15, form_w=0.08):
    avg_gf = LEAGUE_AVG_GF.get(league_id, 1.45)
    avg_ga = LEAGUE_AVG_GA.get(league_id, 1.20)

    ha = home_stats.get("gf_pg", avg_gf) / avg_gf
    hd = home_stats.get("ga_pg", avg_ga) / avg_ga
    aa = away_stats.get("gf_pg", avg_gf) / avg_gf
    ad = away_stats.get("ga_pg", avg_ga) / avg_ga

    diff = elo_h - elo_a
    ef_h = 1.0 + (diff / 400) * 0.3
    ef_a = 1.0 - (diff / 400) * 0.3

    fm = {"W": 1.0, "D": 0.0, "L": -1.0}
    def fb(form):
        if not form: return 1.0
        sc = [fm.get(c.upper(), 0) for c in form[-5:]]
        av = sum(sc) / len(sc) if sc else 0
        return 1.0 + av * form_w

    lam_h = avg_gf * ha * ad * ef_h * fb(home_stats.get("form", "")) * (1 + home_adv)
    lam_a = avg_gf * aa * hd * ef_a * fb(away_stats.get("form", ""))
    return max(0.3, min(lam_h, 4.0)), max(0.3, min(lam_a, 3.5))


def calibrate_with_odds(lam_h, lam_a, odds, weight=0.60):
    if not odds or not odds.get("1") or not odds.get("X") or not odds.get("2"):
        return lam_h, lam_a
    q1, qx, q2 = odds["1"], odds["X"], odds["2"]
    raw = [1/q1, 1/qx, 1/q2]
    margin = sum(raw)
    p1m, pxm, p2m = [r / margin for r in raw]

    def brier(params):
        lh, la = params
        if lh <= 0 or la <= 0: return 10
        r = dixon_coles_matrix(lh, la, -0.07, max_goals=7)
        return (r["p1"] - p1m)**2 + (r["px"] - pxm)**2 + (r["p2"] - p2m)**2

    best, best_score = None, float('inf')
    for sh in [0.7, 0.85, 1.0, 1.15, 1.3]:
        for sa in [0.7, 0.85, 1.0, 1.15, 1.3]:
            score = brier((lam_h * sh, lam_a * sa))
            if score < best_score:
                best_score = score
                best = (lam_h * sh, lam_a * sa)

    if best:
        return max(0.3, (1 - weight) * lam_h + weight * best[0]), max(0.3, (1 - weight) * lam_a + weight * best[1])
    return lam_h, lam_a


if __name__ == "__main__":
    res = dixon_coles_matrix(1.6, 1.2, -0.07)
    print(f"1:{res['p1']:.1%} X:{res['px']:.1%} 2:{res['p2']:.1%}")
