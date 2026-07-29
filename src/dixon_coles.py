"""Modello Dixon-Coles + calibrazione sulle quote + rilevamento del valore (EV/Kelly)."""
import math
from scipy.stats import poisson
from scipy.optimize import minimize

LEAGUE_AVG_GF = {"PL": 1.52, "SA": 1.48, "PD": 1.55, "BL1": 1.58, "FL1": 1.42, "PPL": 1.45}
LEAGUE_AVG_GA = {"PL": 1.20, "SA": 1.15, "PD": 1.18, "BL1": 1.22, "FL1": 1.18, "PPL": 1.20}
LEAGUE_RHO    = {"PL": -0.075, "SA": -0.070, "PD": -0.065, "BL1": -0.060, "FL1": -0.075, "PPL": -0.080}

DEFAULT_GF, DEFAULT_GA, DEFAULT_RHO = 1.48, 1.20, -0.07
SHRINK_K = 5          # forza dello smorzamento a inizio stagione (partite "fittizie")
MARKET_WEIGHT = 0.25  # quanto ci si fida del mercato in calibrazione (0 = solo modello)


def tau(x, y, lam_h, lam_a, rho):
    if x == 0 and y == 0: return max(0.05, 1.0 - lam_h * lam_a * rho)
    elif x == 0 and y == 1: return max(0.05, 1.0 + lam_h * rho)
    elif x == 1 and y == 0: return max(0.05, 1.0 + lam_a * rho)
    elif x == 1 and y == 1: return max(0.05, 1.0 - rho)
    return 1.0


def dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7):
    raw, total = {}, 0.0
    ph = [poisson.pmf(i, lam_h) for i in range(max_goals + 1)]
    pa = [poisson.pmf(i, lam_a) for i in range(max_goals + 1)]
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = ph[h] * pa[a] * tau(h, a, lam_h, lam_a, rho)
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


def _shrink(rate, avg, played, k=SHRINK_K):
    """Smorza una media stagionale verso la media di lega quando i dati sono pochi."""
    if not rate or played is None or played <= 0:
        return avg
    return (rate * played + avg * k) / (played + k)


def compute_lambdas(home_stats, away_stats, elo_h, elo_a, league_id, home_adv=0.15, form_w=0.08):
    avg_gf = LEAGUE_AVG_GF.get(league_id, DEFAULT_GF)
    avg_ga = LEAGUE_AVG_GA.get(league_id, DEFAULT_GA)

    hp = home_stats.get("played", 0)
    ap = away_stats.get("played", 0)
    h_gf = _shrink(home_stats.get("gf_pg"), avg_gf, hp)
    h_ga = _shrink(home_stats.get("ga_pg"), avg_ga, hp)
    a_gf = _shrink(away_stats.get("gf_pg"), avg_gf, ap)
    a_ga = _shrink(away_stats.get("ga_pg"), avg_ga, ap)

    ha, hd = h_gf / avg_gf, h_ga / avg_ga
    aa, ad = a_gf / avg_gf, a_ga / avg_ga

    diff = elo_h - elo_a
    ef_h = 1.0 + (diff / 400) * 0.3
    ef_a = 1.0 - (diff / 400) * 0.3

    fm = {"W": 1.0, "D": 0.0, "L": -1.0}
    def fb(form):
        if not form: return 1.0
        sc = [fm.get(c.upper(), 0) for c in form[-5:]]
        return 1.0 + (sum(sc) / len(sc)) * form_w if sc else 1.0

    lam_h = avg_gf * ha * ad * ef_h * fb(home_stats.get("form", "")) * (1 + home_adv)
    lam_a = avg_gf * aa * hd * ef_a * fb(away_stats.get("form", ""))
    return max(0.3, min(lam_h, 4.0)), max(0.3, min(lam_a, 3.5))


def calibrate_with_odds(lam_h, lam_a, odds, rho=DEFAULT_RHO, weight=MARKET_WEIGHT):
    """Adatta i lambda alle quote usando SIA 1-X-2 SIA Over/Under 2.5.
    L'1-X-2 fissa la differenza tra le squadre, l'Over/Under la somma dei gol."""
    if not odds:
        return lam_h, lam_a
    targets = {}
    q1, qx, q2 = odds.get("1"), odds.get("X"), odds.get("2")
    if q1 and qx and q2:
        raw = [1 / q1, 1 / qx, 1 / q2]
        s = sum(raw)
        targets["1x2"] = tuple(r / s for r in raw)
    qo, qu = odds.get("over25"), odds.get("under25")
    if qo and qu:
        ro, ru = 1 / qo, 1 / qu
        targets["ou"] = ro / (ro + ru)
    if not targets:
        return lam_h, lam_a

    def loss(x):
        lh, la = x
        if lh <= 0.1 or la <= 0.1 or lh > 6 or la > 6:
            return 1e3
        r = dixon_coles_matrix(lh, la, rho)
        e = 0.0
        if "1x2" in targets:
            p1m, pxm, p2m = targets["1x2"]
            e += (r["p1"] - p1m) ** 2 + (r["px"] - pxm) ** 2 + (r["p2"] - p2m) ** 2
        if "ou" in targets:
            e += (r["p_over25"] - targets["ou"]) ** 2
        return e

    res = minimize(loss, [lam_h, lam_a], method="Nelder-Mead",
                   options={"xatol": 1e-3, "fatol": 1e-5, "maxiter": 300})
    mh, ma = res.x
    mh = max(0.3, min(mh, 4.0))
    ma = max(0.3, min(ma, 3.5))
    return (1 - weight) * lam_h + weight * mh, (1 - weight) * lam_a + weight * ma


# ---------- Rilevamento del valore (EV) + Kelly ----------

def _implied_novig_1x2(q1, qx, q2):
    raw = [1 / q1, 1 / qx, 1 / q2]
    s = sum(raw)
    return [r / s for r in raw]


def kelly_fraction(p, dec_odds):
    """Frazione di Kelly PIENA. b = quota-1."""
    b = dec_odds - 1
    if b <= 0:
        return 0.0
    return max(0.0, (p * dec_odds - 1) / b)


def compute_value(pred, odds, kelly_cap=0.05, edge_min=0.03):
    """Confronta prob. del modello con la quota MIGLIORE disponibile.
    edge = p_modello * quota - 1. Kelly mostrato a meta' (piu' prudente),
    limitato a kelly_cap del bankroll."""
    if not odds:
        return None
    best = odds.get("best", odds)  # se non c'e' 'best', usa le quote medie
    markets = {
        "1": (pred["p1"], best.get("1")),
        "X": (pred["px"], best.get("X")),
        "2": (pred["p2"], best.get("2")),
        "Over 2.5": (pred["p_over25"], best.get("over25")),
        "Under 2.5": (pred["p_under25"], best.get("under25")),
    }
    rows = []
    for name, (p, q) in markets.items():
        if not q or q <= 1:
            continue
        edge = p * q - 1
        half_kelly = min(kelly_cap, kelly_fraction(p, q) / 2)
        rows.append({"market": name, "p": round(p, 4), "odds": round(q, 3),
                     "edge": round(edge, 4), "kelly": round(half_kelly, 4)})
    rows.sort(key=lambda r: r["edge"], reverse=True)
    bet = rows[0] if rows and rows[0]["edge"] >= edge_min else None
    return {"rows": rows, "bestBet": bet}


if __name__ == "__main__":
    r = dixon_coles_matrix(1.6, 1.2, -0.07)
    print(f"1:{r['p1']:.1%} X:{r['px']:.1%} 2:{r['p2']:.1%}")
    lh, la = calibrate_with_odds(1.6, 1.2, {"1": 2.1, "X": 3.3, "2": 3.6, "over25": 1.9, "under25": 1.95})
    print(f"calibrati: lamH={lh:.3f} lamA={la:.3f}")
