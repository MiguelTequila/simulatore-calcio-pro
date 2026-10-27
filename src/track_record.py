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
            "pGG": pred.get("pGG"), "pNG": pred.get("pNG"),
            "odds": {"1": odds.get("1"), "X": odds.get("X"), "2": odds.get("2"),
                     "over25": odds.get("over25"), "under25": odds.get("under25"),
                     "gg": odds.get("gg"), "ng": odds.get("ng")},
            "bestOdds": {"1": best.get("1"), "X": best.get("X"), "2": best.get("2"),
                         "over25": best.get("over25"), "under25": best.get("under25"),
                         "gg": best.get("gg"), "ng": best.get("ng")},
            "bestBet": (pred.get("value") or {}).get("bestBet"),
            "modelVersion": pred.get("modelVersion"),
            "result": None,
        }
        # CLV: conserviamo la PRIMA quota vista e la prima bet segnalata.
        # L'ultima registrazione prima della partita fa da quota di chiusura:
        # il confronto fra le due dice se stiamo battendo il mercato, e lo dice
        # con poche decine di scommesse invece che con centinaia.
        if existing:
            entry["firstOdds"] = existing.get("firstOdds") or existing.get("bestOdds")
            entry["firstBet"] = existing.get("firstBet") or existing.get("bestBet")
            entry["firstSeen"] = existing.get("firstSeen")
        if not entry.get("firstOdds"):
            entry["firstOdds"] = entry["bestOdds"]
            entry["firstBet"] = entry["bestBet"]
            from datetime import datetime, timezone
            entry["firstSeen"] = datetime.now(timezone.utc).isoformat()
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
    if market == "Goal (GG)": return result["gg"]
    if market == "NoGoal (NG)": return not result["gg"]
    return False


def build_track_record(log):
    """Calibrazione (prob. prevista vs frequenza reale) + P&L delle value bet."""
    graded = [e for e in log["predictions"].values() if e.get("result")]

    # --- calibrazione, divisa anche per gruppo di mercati ---
    # Mescolare esiti e gol nascondeva dove il modello sbaglia davvero:
    # ora 1X2, Over/Under e Goal/NoGoal si leggono separatamente.
    samples = []            # (p_prevista, esito 0/1) su tutto
    by_group = {"1X2": [], "Over/Under": [], "Goal/NoGoal": []}
    for e in graded:
        r = e["result"]
        g1 = [(e["p1"], r["outcome"] == "1"), (e["px"], r["outcome"] == "X"),
              (e["p2"], r["outcome"] == "2")]
        g2 = [(e["pOver25"], r["over25"]), (e["pUnder25"], not r["over25"])]
        g3 = []
        if e.get("pGG") is not None:
            g3 = [(e["pGG"], r["gg"]), (e["pNG"], not r["gg"])]
        by_group["1X2"] += g1
        by_group["Over/Under"] += g2
        by_group["Goal/NoGoal"] += g3
        samples += g1 + g2 + g3
    def make_bins(data):
        out = []
        for lo in range(0, 100, 10):
            hi = lo + 10
            inbin = [(p, w) for p, w in data if lo / 100 <= p < hi / 100 or (hi == 100 and p == 1)]
            if inbin:
                avg_p = sum(p for p, _ in inbin) / len(inbin)
                freq = sum(1 for _, w in inbin if w) / len(inbin)
            else:
                avg_p, freq = None, None
            out.append({"bin": f"{lo}-{hi}%", "n": len(inbin),
                        "avgPred": round(avg_p, 4) if avg_p is not None else None,
                        "actualFreq": round(freq, 4) if freq is not None else None})
        return out

    def brier_of(data):
        return round(sum((p - (1 if w else 0)) ** 2 for p, w in data) / len(data), 4) if data else None

    def bias_of(data):
        """ATTENZIONE: su mercati complementari (1-X-2, Over/Under, GG/NG) questo
        valore e' ZERO per costruzione, qualunque sia la bravura del modello:
        le probabilita' sommano a 1 e succede sempre esattamente un esito.
        Resta solo per compatibilita' con i registri gia' salvati."""
        if not data: return None
        return round(sum(p for p, _ in data) / len(data) - sum(1 for _, w in data if w) / len(data), 4)

    def confidence_split(data):
        """La misura che conta davvero: il modello sbaglia di piu' quando si
        sbilancia o quando e' prudente? Separa i casi in cui promette oltre
        il 50% da quelli sotto, e confronta promesso e avvenuto."""
        out = {}
        for key, sel in (("sicuro", lambda p: p >= 0.5), ("incerto", lambda p: p < 0.5)):
            sub = [(p, w) for p, w in data if sel(p)]
            if not sub:
                out[key] = None
                continue
            pred = sum(p for p, _ in sub) / len(sub)
            act = sum(1 for _, w in sub if w) / len(sub)
            out[key] = {"n": len(sub), "pred": round(pred, 4),
                        "actual": round(act, 4), "gap": round(act - pred, 4)}
        return out

    bins = make_bins(samples)
    brier = brier_of(samples)
    groups = []
    for name, data in by_group.items():
        if not data:
            continue
        groups.append({"group": name, "n": len(data), "brier": brier_of(data),
                       "bias": bias_of(data), "confidence": confidence_split(data),
                       "calibration": make_bins(data)})

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
    # --- CLV: la quota presa contro quella di chiusura ---
    # Se batti sistematicamente la linea di chiusura hai un vantaggio reale,
    # e lo si capisce con 30-50 scommesse invece che con centinaia.
    clv_rows, clv_sum, clv_pos = [], 0.0, 0
    for e in graded:
        fb_ = e.get("firstBet")
        if not fb_:
            continue
        mkey = {"1": "1", "X": "X", "2": "2", "Over 2.5": "over25",
                "Under 2.5": "under25", "Goal (GG)": "gg", "NoGoal (NG)": "ng"}.get(fb_["market"])
        close = (e.get("bestOdds") or {}).get(mkey)
        taken = fb_.get("odds")
        if not close or not taken or close <= 1 or taken <= 1:
            continue
        clv = taken / close - 1
        clv_sum += clv
        clv_pos += 1 if clv > 0 else 0
        clv_rows.append({"date": e["date"], "match": f'{e["home"]} - {e["away"]}',
                         "market": fb_["market"], "taken": round(taken, 3),
                         "close": round(close, 3), "clv": round(clv, 4)})
    clv_rows.sort(key=lambda x: x["date"])
    clv = {"n": len(clv_rows), "avg": round(clv_sum / len(clv_rows), 4) if clv_rows else None,
           "beatenPct": round(clv_pos / len(clv_rows), 4) if clv_rows else None,
           "history": clv_rows[-50:]}

    bets.sort(key=lambda b: b["date"])
    cum = 0.0
    for b in bets:
        cum += b["pl"]
        b["cum"] = round(cum, 3)

    n_bets = len(bets)
    track = {
        "graded": len(graded), "pending": len(log["predictions"]) - len(graded),
        "brier": brier, "calibration": bins, "groups": groups, "clv": clv,
        "valueBets": {"n": n_bets, "wins": wins,
                       "profitUnits": round(profit, 3),
                       "roi": round(profit / n_bets, 4) if n_bets else None,
                       "history": bets[-100:]},
    }
    return track


def save_track(track):
    with open(TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(track, f, ensure_ascii=False, indent=1)


def build_results(log):
    """Estrae i soli risultati delle partite gia' giocate, in forma compatta.
    Finiscono dentro track_record.json (che l'app scarica comunque) sotto la
    chiave "results", cosi' l'app verifica DA SOLA le schedine simulate invece
    di costringere a spuntare gli esiti a mano. Il registro completo pesa
    centinaia di KB: questo estratto sta in poche decine."""
    out = {}
    for mid, e in (log.get("predictions") or {}).items():
        r = e.get("result")
        if not r:
            continue
        out[str(mid)] = {"h": r["hg"], "a": r["ag"], "o": r["outcome"],
                         "ov": bool(r["over25"]), "gg": bool(r["gg"]),
                         "d": e.get("date", ""), "n": (e.get("home", "") + " - " + e.get("away", ""))[:48]}
    return out
