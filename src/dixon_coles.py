"""Modello Dixon-Coles + calibrazione sulle quote + rilevamento del valore (EV/Kelly)."""
import math
from scipy.stats import poisson
from scipy.optimize import minimize

# Versione del modello: cambiala a OGNI modifica che altera le previsioni.
# Viene salvata in ogni predizione, cosi' il registro degli esiti puo' separare
# i risultati del modello vecchio da quelli del nuovo invece di mescolarli.
MODEL_VERSION = "3.0"

# Media gol per squadra per partita, usata come riferimento di lega.
# NOTA IMPORTANTE: in un campionato la media dei gol FATTI e quella dei gol
# SUBITI sono necessariamente IDENTICHE (ogni gol segnato da uno e' subito da
# un altro). Tenere due costanti diverse gonfiava ogni lambda di circa il 25%.
# Questi valori sono solo un ripiego: la media vera viene calcolata dai dati
# con league_average() a ogni aggiornamento.
LEAGUE_AVG = {"PL": 1.44, "SA": 1.48, "PD": 1.53, "BL1": 1.84,
              "FL1": 1.52, "PPL": 1.37, "DED": 1.92, "CL": 2.04}
LEAGUE_RHO = {"PL": -0.075, "SA": -0.070, "PD": -0.065, "BL1": -0.060,
              "FL1": -0.075, "PPL": -0.080, "DED": -0.060, "CL": -0.065}

DEFAULT_AVG, DEFAULT_RHO = 1.50, -0.07

# Medie storiche di lungo periodo (gol per squadra per partita). Servono come
# ancora quando la stagione e' appena iniziata: con poche giornate la media
# osservata e' rumorosa e trascina tutto il modello.
LEAGUE_PRIOR = {"PL": 1.42, "SA": 1.38, "PD": 1.33, "BL1": 1.60,
                "FL1": 1.38, "DED": 1.60, "PPL": 1.35,
                "CL": 1.56, "EL": 1.50, "ECL": 1.60}

# Quanto pesa il priore, misurato in "partite-squadra". A 150, una lega con
# 150 partite-squadra giocate pesa il priore al 50%; a stagione avanzata
# l'effetto sparisce da solo.
PRIOR_WEIGHT = 150

# Competizioni di cui vediamo solo una PARTE delle squadre, e per giunta le
# migliori (quelle dei campionati che seguiamo). La loro media calcolata e'
# gonfiata per costruzione, quindi ci si affida quasi solo al priore.
BIASED_SAMPLE = {"EL", "ECL"}

# Vantaggio del campo di riferimento, usato se mancano i parziali casa/trasferta
HOME_EDGE = 0.11

# Retrocompatibilita' con il vecchio codice che importava questi nomi
LEAGUE_AVG_GF = LEAGUE_AVG
LEAGUE_AVG_GA = LEAGUE_AVG
DEFAULT_GF = DEFAULT_GA = DEFAULT_AVG


def league_average(teams, league_id=None):
    """Media gol/partita della lega. Non e' la media grezza osservata: viene
    fusa con la media storica in proporzione alle partite davvero giocate.
    Serve a non far decidere a tre giornate di Champions quanto si segna."""
    prior = LEAGUE_PRIOR.get(league_id, LEAGUE_AVG.get(league_id, DEFAULT_AVG))
    tot_goals, tot_games = 0.0, 0
    for t in (teams or {}).values():
        pl = t.get("played") or 0
        gf = t.get("gf_pg")
        if pl <= 0 or gf is None:
            continue
        tot_goals += gf * pl
        tot_games += pl
    if tot_games <= 0:
        return prior
    observed = tot_goals / tot_games
    if not (0.6 <= observed <= 4.0):     # dato palesemente sporco
        return prior
    # campione distorto (vediamo solo le squadre forti): peso del priore molto alto
    k = PRIOR_WEIGHT * 6 if league_id in BIASED_SAMPLE else PRIOR_WEIGHT
    return (tot_goals + k * prior) / (tot_games + k)


def league_observed(teams):
    """Media grezza osservata, senza smorzamento. Serve a riportare le
    statistiche delle squadre sulla stessa scala della media smorzata:
    altrimenti, abbassando solo il riferimento, OGNI squadra risulterebbe
    sopra la media e i gol previsti salirebbero invece di scendere."""
    g, n = 0.0, 0
    for t in (teams or {}).values():
        pl = t.get("played") or 0
        gf = t.get("gf_pg")
        if pl > 0 and gf is not None:
            g += gf * pl; n += pl
    return (g / n) if n else None


def stat_scale(teams, league_avg):
    """Fattore per riportare le medie squadra sulla scala della lega smorzata."""
    obs = league_observed(teams)
    if not obs or obs <= 0 or not league_avg:
        return 1.0
    f = league_avg / obs
    return max(0.6, min(f, 1.4))      # protezione contro dati assurdi


def league_home_away(teams, league_avg):
    """Media gol di chi gioca in casa e di chi gioca fuori, misurata dai
    parziali della classifica. Se non ci sono, si usa il vantaggio campo fisso."""
    hg = ag = 0.0
    hp = ap = 0
    for t in (teams or {}).values():
        ph, pa = t.get("played_home") or 0, t.get("played_away") or 0
        if ph and t.get("gf_pg_home") is not None:
            hg += t["gf_pg_home"] * ph; hp += ph
        if pa and t.get("gf_pg_away") is not None:
            ag += t["gf_pg_away"] * pa; ap += pa
    if hp >= 40 and ap >= 40:
        h, a = hg / hp, ag / ap
        tot = h + a
        if tot > 0 and 0.9 <= (h / a) <= 1.9:
            # riscalati sulla media di lega smorzata, per non reintrodurre il rumore
            f = (2 * league_avg) / tot
            return h * f, a * f
    return league_avg * (1 + HOME_EDGE), league_avg * (1 - HOME_EDGE)
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


def _blend(rate, n, fallback, k=4):
    """Fonde una statistica parziale (casa o trasferta, meta' campione) con un
    valore di riserva, in proporzione alle partite su cui e' calcolata."""
    if rate is None or not n:
        return fallback
    return (rate * n + fallback * k) / (n + k)


def compute_lambdas(home_stats, away_stats, elo_h, elo_a, league_id,
                    home_adv=HOME_EDGE, form_w=0.08, league_avg=None, league_ha=None,
                    scale=1.0):
    """Gol attesi delle due squadre.

    Quando la classifica fornisce i parziali, si usano i gol fatti IN CASA
    dalla squadra di casa e quelli subiti IN TRASFERTA dall'ospite: cosi' le
    squadre-fortezza e quelle che crollano fuori non vengono piu' appiattite
    su un vantaggio del campo uguale per tutti."""
    avg = league_avg if league_avg else LEAGUE_AVG.get(league_id, DEFAULT_AVG)
    if league_ha:
        h_base, a_base = league_ha
    else:
        h_base, a_base = avg * (1 + home_adv), avg * (1 - home_adv)

    hp = home_stats.get("played", 0) or 0
    ap = away_stats.get("played", 0) or 0
    def sc(v):
        return None if v is None else v * scale
    # medie complessive, riportate sulla scala della lega smorzata e poi
    # avvicinate alla media se la squadra ha giocato poco
    h_gf_tot = _shrink(sc(home_stats.get("gf_pg")), avg, hp)
    h_ga_tot = _shrink(sc(home_stats.get("ga_pg")), avg, hp)
    a_gf_tot = _shrink(sc(away_stats.get("gf_pg")), avg, ap)
    a_ga_tot = _shrink(sc(away_stats.get("ga_pg")), avg, ap)

    # riporto la media complessiva nel contesto giusto (in casa si segna di piu')
    sh, sa = h_base / avg, a_base / avg
    h_gf = _blend(sc(home_stats.get("gf_pg_home")), home_stats.get("played_home"), h_gf_tot * sh)
    h_ga = _blend(sc(home_stats.get("ga_pg_home")), home_stats.get("played_home"), h_ga_tot * sa)
    a_gf = _blend(sc(away_stats.get("gf_pg_away")), away_stats.get("played_away"), a_gf_tot * sa)
    a_ga = _blend(sc(away_stats.get("ga_pg_away")), away_stats.get("played_away"), a_ga_tot * sh)

    diff = elo_h - elo_a
    ef_h = 1.0 + (diff / 400) * 0.3
    ef_a = 1.0 - (diff / 400) * 0.3

    fm = {"W": 1.0, "D": 0.0, "L": -1.0}
    def fb(form):
        if not form: return 1.0
        sc = [fm.get(c.upper(), 0) for c in form[-5:]]
        return 1.0 + (sum(sc) / len(sc)) * form_w if sc else 1.0

    # attacco di chi gioca in casa x difesa di chi gioca fuori, sulla base giusta
    lam_h = (h_gf * a_ga / h_base) * ef_h * fb(home_stats.get("form", ""))
    lam_a = (a_gf * h_ga / a_base) * ef_a * fb(away_stats.get("form", ""))
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
        "Goal (GG)": (pred["p_gg"], best.get("gg")),
        "NoGoal (NG)": (pred["p_ng"], best.get("ng")),
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
