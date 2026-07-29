"""Registro esiti reali: salva ogni predizione, la riconcilia col risultato
quando la partita finisce, e misura calibrazione + rendimento delle value bet.

Tutto a costo ZERO di API: i risultati arrivano dai recentMatches che la
pipeline scarica comunque, agganciati per id partita (stabile su Football-Data).
"""
import json, os

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "predictions_log.json")
TRACK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "track_record.json")


def load_log():
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
        log.setdefault("predictions", {})
        return log
    except Exception:
        return {"predictions": {}}


def save_log(log):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def log_predictions(log, comp_id, comp_name, fixtures):
    """Registra/aggiorna la predizione finche' la partita non e' giocata.
    Vale l'ULTIMA predizione pre-partita (dati piu' freschi)."""
    for fix in fixtures:
        mid = str(fix["id"])
        existing = log["predictions"].get(mid)
        if existing and existing.get("result"):
            continue  # gia' giocata e valutata: non toccare
        pred = fix["prediction"]
        odds = fix.get("odds") or {}
        best = odds.get("best") or {}
        entry = {
            "comp": comp_id, "compName": comp_name, "date": fix["date"],
            "home": fix["homeTeam"], "away": fix["awayTeam"],
            "p1": pred["p1"], "px": pred["px"], "p2": pred["p2"],
            "pOver25": pred["pOver25"], "pUnder25": pred["pUnder25"],
            "odds": {"1": odds.get("1"), "X": odds.get("X"), "2": odds.get("2"),
                     "over25": odds.get("over25"), "under25": odds.get("under25")},
            "bestOdds": {"1": best.get("1"), "X": best.get("X"), "2": best.get("2"),
                         "over25": best.get("over25"), "under25": best.get("under25")},
            "bestBet": (pred.get("value") or {}).get("bestBet"),
            "result": None,
        }
        log["predictions"][mid] = entry


def reconcile_results(log, raw_competitions):
    """Aggancia i risultati reali alle predizioni registrate (per id)."""
    finished = {}
    for comp in raw_competitions.values():
        for m in comp.get("recentMatches", []):
            if m.get("homeGoals") is not None and m.get("awayGoals") is not None:
                finished[str(m["id"])] = m
    n = 0
    for mid, entry in log["predictions"].items():
        if entry.get("result"):
            continue
        m = finished.get(mid)
        if not m:
            continue
        hg, ag = m["homeGoals"], m["awayGoals"]
        outcome = "1" if hg > ag else ("X" if hg == ag else "2")
        entry["result"] = {"hg": hg, "ag": ag, "outcome": outcome,
                           "over25": hg + ag >= 3, "gg": hg >= 1 and ag >= 1}
        n += 1
    return n


def _bet_won(market, result):
    if market == "1": return result["outcome"] == "1"
    if market == "X": return result["outcome"] == "X"
    if market == "2": return result["outcome"] == "2"
    if market == "Over 2.5": return result["over25"]
    if market == "Under 2.5": return not result["over25"]
    return False


def build_track_record(log):
    """Calibrazione (prob. prevista vs frequenza reale) + P&L delle value bet."""
    graded = [e for e in log["predictions"].values() if e.get("result")]

    # --- calibrazione su tutti i mercati principali ---
    samples = []  # (p_prevista, esito 0/1)
    for e in graded:
        r = e["result"]
        samples += [(e["p1"], r["outcome"] == "1"), (e["px"], r["outcome"] == "X"),
                    (e["p2"], r["outcome"] == "2"), (e["pOver25"], r["over25"]),
                    (e["pUnder25"], not r["over25"])]
    bins = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        inbin = [(p, w) for p, w in samples if lo / 100 <= p < hi / 100 or (hi == 100 and p == 1)]
        if inbin:
            avg_p = sum(p for p, _ in inbin) / len(inbin)
            freq = sum(1 for _, w in inbin if w) / len(inbin)
        else:
            avg_p, freq = None, None
        bins.append({"bin": f"{lo}-{hi}%", "n": len(inbin),
                     "avgPred": round(avg_p, 4) if avg_p is not None else None,
                     "actualFreq": round(freq, 4) if freq is not None else None})

    # Brier score complessivo (piu' basso = meglio; 0.25 = tirare a caso su eventi 50/50)
    brier = round(sum((p - (1 if w else 0)) ** 2 for p, w in samples) / len(samples), 4) if samples else None

    # --- verifica dell'edge: value bet giocate a quota registrata, puntata fissa 1 ---
    bets, profit, wins = [], 0.0, 0
    for e in graded:
        bb = e.get("bestBet")
        if not bb:
            continue
        won = _bet_won(bb["market"], e["result"])
        pl = (bb["odds"] - 1) if won else -1.0
        profit += pl
        wins += 1 if won else 0
        bets.append({"date": e["date"], "match": f'{e["home"]} - {e["away"]}',
                     "market": bb["market"], "odds": bb["odds"], "edge": bb["edge"],
                     "won": won, "pl": round(pl, 3)})
    bets.sort(key=lambda b: b["date"])
    cum = 0.0
    for b in bets:
        cum += b["pl"]
        b["cum"] = round(cum, 3)

    n_bets = len(bets)
    track = {
        "graded": len(graded), "pending": len(log["predictions"]) - len(graded),
        "brier": brier, "calibration": bins,
        "valueBets": {"n": n_bets, "wins": wins,
                       "profitUnits": round(profit, 3),
                       "roi": round(profit / n_bets, 4) if n_bets else None,
                       "history": bets[-100:]},
    }
    return track


def save_track(track):
    with open(TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(track, f, ensure_ascii=False, indent=1)
