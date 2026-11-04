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


def write_json(path, dati, indent=1):
    """Scrittura ATOMICA: prima su un file di lavoro, poi rinomina.
    Senza questo, un giro interrotto a metà (GitHub Actions che va in timeout,
    disco pieno, errore dopo la open) lasciava un JSON troncato: il sito lo
    leggeva, non riusciva ad analizzarlo e restava vuoto, e per capirlo
    bisognava guardare il file a mano. La rinomina sullo stesso disco è
    un'operazione indivisibile: o c'è il file vecchio intero, o il nuovo
    intero, mai mezzo file."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# Quante previsioni gia' valutate tenere nel registro, in giorni.
# A 40 partite al mese il registro cresce di circa 30 KB al mese, e viene
# riscritto a ogni giro: senza un limite la cronologia del repository gonfia
# per sempre. 550 giorni tengono due stagioni, abbastanza per qualunque
# confronto fra versioni del modello.
PRUNE_AFTER_DAYS = 550


def prune_log(log, oggi=None):
    """Toglie le previsioni valutate troppo vecchie. Le partite non ancora
    giocate non si toccano mai, qualunque sia la data."""
    from datetime import date, timedelta
    oggi = oggi or date.today()
    limite = (oggi - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    prima = len(log.get("predictions") or {})
    log["predictions"] = {
        k: v for k, v in (log.get("predictions") or {}).items()
        if not v.get("result") or (v.get("date") or "9999") >= limite
    }
    return prima - len(log["predictions"])


def save_log(log):
    write_json(LOG_FILE, log, indent=1)


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

    # --- lo stesso conto, diviso per VERSIONE del modello ---
    # Finche' tutto finiva in un calderone unico, nessuna modifica al modello
    # era misurabile: una versione nuova e migliore restava sepolta sotto
    # centinaia di previsioni della vecchia. Da qui in avanti ogni versione ha
    # i suoi numeri, e si vede se un cambiamento ha funzionato o no.
    def metriche(sub):
        camp = []
        for e in sub:
            r = e["result"]
            camp += [(e["p1"], r["outcome"] == "1"), (e["px"], r["outcome"] == "X"),
                     (e["p2"], r["outcome"] == "2"),
                     (e["pOver25"], r["over25"]), (e["pUnder25"], not r["over25"])]
            if e.get("pGG") is not None:
                camp += [(e["pGG"], r["gg"]), (e["pNG"], not r["gg"])]
        prof = wn = 0.0
        nb = 0
        for e in sub:
            bb = e.get("bestBet")
            if not bb:
                continue
            nb += 1
            won = _bet_won(bb["market"], e["result"])
            prof += (bb["odds"] - 1) if won else -1.0
            wn += 1 if won else 0
        cs, cpos = [], 0
        for e in sub:
            fb_ = e.get("firstBet")
            if not fb_:
                continue
            mk = {"1": "1", "X": "X", "2": "2", "Over 2.5": "over25",
                  "Under 2.5": "under25", "Goal (GG)": "gg", "NoGoal (NG)": "ng"}.get(fb_["market"])
            cl = (e.get("bestOdds") or {}).get(mk)
            tk = fb_.get("odds")
            if not cl or not tk or cl <= 1 or tk <= 1:
                continue
            c = tk / cl - 1
            cs.append(c)
            cpos += 1 if c > 0 else 0
        date = sorted(e.get("date", "") for e in sub)
        return {"n": len(sub), "nPrev": len(camp), "brier": brier_of(camp),
                "confidence": confidence_split(camp), "calibration": make_bins(camp),
                "dal": date[0] if date else None, "al": date[-1] if date else None,
                "valueBets": {"n": nb, "wins": int(wn), "profitUnits": round(prof, 3),
                              "roi": round(prof / nb, 4) if nb else None},
                "clv": {"n": len(cs),
                        "avg": round(sum(cs) / len(cs), 4) if cs else None,
                        "beatenPct": round(cpos / len(cs), 4) if cs else None}}

    # --- tabellone dei successi: quante ne azzecca, per mercato ---
    # Da solo un numero di successi non dice niente: azzeccare il 61% su
    # Goal/NoGoal sembra tanto finche' non si scopre che "sempre Goal" fa lo
    # stesso senza nessun modello. Quindi accanto a ogni riga del modello
    # stanno le regole di confronto che non usano intelligenza.
    def conta(sub, scelta, vero):
        n = c = 0
        for e in sub:
            s = scelta(e)
            if s is None:
                continue
            n += 1
            c += 1 if s == vero(e) else 0
        return {"n": n, "hit": c, "pct": round(c / n, 4) if n else None}

    def favorito_1x2(e):
        """Chi il bookmaker ritiene piu' probabile: la quota piu' bassa."""
        o = e.get("odds") or {}
        q = [o.get("1"), o.get("X"), o.get("2")]
        if None in q or not all(q):
            return None
        return ["1", "X", "2"][min(range(3), key=lambda i: q[i])]

    def favorito_ou(e):
        o = e.get("odds") or {}
        qo, qu = o.get("over25"), o.get("under25")
        if not (qo and qu):
            return None
        return qo < qu          # quota piu' bassa = esito che il bookmaker ritiene piu' probabile

    def modello_1x2(e):
        ps = [e.get("p1"), e.get("px"), e.get("p2")]
        if None in ps:
            return None
        return ["1", "X", "2"][max(range(3), key=lambda i: ps[i])]

    vero_1x2 = lambda e: e["result"]["outcome"]
    vero_ou = lambda e: bool(e["result"]["over25"])
    vero_gg = lambda e: bool(e["result"]["gg"])

    # Confronto a PARITA' di partite: si contano solo quelle dove tutte le
    # righe sono calcolabili. Contare il modello su 630 partite e il favorito
    # su 421 darebbe un confronto falsato e rassicurante.
    sub12 = [e for e in graded if favorito_1x2(e) and modello_1x2(e)]
    subou = [e for e in graded
             if favorito_ou(e) is not None and e.get("pOver25") is not None]
    subgg = [e for e in graded if e.get("pGG") is not None]
    hit = {
        "1X2": {
            "modello": conta(sub12, modello_1x2, vero_1x2),
            "favorito": conta(sub12, favorito_1x2, vero_1x2),
            "sempreCasa": conta(sub12, lambda e: "1", vero_1x2),
            "sempreX": conta(sub12, lambda e: "X", vero_1x2),
        },
        "Over/Under 2.5": {
            "modello": conta(subou, lambda e: (e.get("pOver25") or 0) > 0.5, vero_ou),
            "favorito": conta(subou, favorito_ou, vero_ou),
            "sempreOver": conta(subou, lambda e: True, vero_ou),
            "sempreUnder": conta(subou, lambda e: False, vero_ou),
        },
        "Goal/NoGoal": {
            "modello": conta(subgg, lambda e: (e.get("pGG") or 0) > 0.5, vero_gg),
            "sempreGoal": conta(subgg, lambda e: True, vero_gg),
            "sempreNoGoal": conta(subgg, lambda e: False, vero_gg),
        },
    }

    # --- OSSERVAZIONE: big match contro il resto -------------------------
    # Non cambia NESSUNA previsione: conta soltanto. Serve a far maturare da
    # sola l'unica ipotesi che, nei dati, punta a un errore che il mercato
    # commette insieme al modello (e quindi l'unica che potrebbe dare un
    # vantaggio invece che solo accuratezza): nelle partite fra squadre forti
    # entrambi sovrastimano l'Over 2.5 di circa dieci punti.
    # Al 4 nov 2026 il segnale valeva 0.68-1.75 volte l'errore tipico: troppo
    # poco per giocarci. Qui si accumula finche' non supera 2, o finche' non
    # si spegne.
    BIG_FRAZIONE = 3.0        # "forte" = il terzo di squadre piu' forti
    BIG_MIN_PARTITE = 4       # partite minime per giudicare una squadra

    def forza_squadre(sub):
        """Forza di ogni squadra secondo il MERCATO: probabilita' implicita
        media di vittoria nelle sue partite. Si usa il mercato e non il
        modello di proposito: serve un metro indipendente da cio' che stiamo
        misurando, altrimenti il modello si giudicherebbe da solo."""
        acc = {}
        for e in sub:
            o = e.get("odds") or {}
            q1, qx, q2 = o.get("1"), o.get("X"), o.get("2")
            if not (q1 and qx and q2):
                continue
            tot = 1 / q1 + 1 / qx + 1 / q2
            acc.setdefault(e["home"], []).append((1 / q1) / tot)
            acc.setdefault(e["away"], []).append((1 / q2) / tot)
        return {t: sum(v) / len(v) for t, v in acc.items() if len(v) >= BIG_MIN_PARTITE}

    def segnale(valori):
        """Quante volte l'errore tipico vale il risultato medio. Sotto 2 e'
        indistinguibile dal caso, e va detto a chiare lettere."""
        n = len(valori)
        if n < 2:
            return None
        media = sum(valori) / n
        var = sum((x - media) ** 2 for x in valori) / (n - 1)
        if var <= 0:
            return None
        return round(media / ((var ** 0.5) / (n ** 0.5)), 2)

    def gruppo_big(sub, e_big):
        sel = [e for e in sub if e.get("pOver25") is not None]
        if not sel:
            return None
        prev = sum(e["pOver25"] for e in sel) / len(sel)
        reale = sum(1 for e in sel if e["result"]["over25"]) / len(sel)
        # errore tipico della frequenza osservata, in punti percentuali
        err = ((max(reale * (1 - reale), 0.01) / len(sel)) ** 0.5)
        # e se avessi puntato Under 2.5 su tutte?
        esiti = []
        for e in sel:
            q = (e.get("bestOdds") or {}).get("under25")
            if not q or q <= 1:
                continue
            esiti.append((q - 1) if not e["result"]["over25"] else -1.0)
        pl = sum(esiti) if esiti else None
        return {"big": e_big, "n": len(sel),
                "predOver": round(prev, 4), "actualOver": round(reale, 4),
                "gap": round(reale - prev, 4), "err": round(err, 4),
                "under": {"n": len(esiti),
                          "profitUnits": round(pl, 3) if pl is not None else None,
                          "roi": round(pl / len(esiti), 4) if esiti else None,
                          "signal": segnale(esiti)}}

    forze = forza_squadre(graded)
    big_match = None
    if len(forze) >= 10:
        ordinate = sorted(forze.values(), reverse=True)
        soglia = ordinate[int(len(ordinate) / BIG_FRAZIONE)]
        def e_forte(t):
            return forze.get(t, 0) >= soglia
        bb = [e for e in graded if e_forte(e["home"]) and e_forte(e["away"])]
        altre = [e for e in graded if not (e_forte(e["home"]) and e_forte(e["away"]))]
        g_bb, g_al = gruppo_big(bb, True), gruppo_big(altre, False)
        pronto = None
        if g_bb and g_al:
            dif = g_bb["gap"] - g_al["gap"]
            err = (g_bb["err"] ** 2 + g_al["err"] ** 2) ** 0.5
            volte = round(abs(dif) / err, 2) if err else None
            pronto = {"differenza": round(dif, 4), "errore": round(err, 4),
                      "volteErrore": volte,
                      "usabile": bool(volte and volte >= 2.0)}
        big_match = {"soglia": round(soglia, 4), "squadreValutate": len(forze),
                     "squadreForti": sum(1 for t in forze if e_forte(t)),
                     "gruppi": [g for g in (g_bb, g_al) if g], "verdetto": pronto}

    per_ver = {}
    for e in graded:
        per_ver.setdefault(e.get("modelVersion") or "sconosciuta", []).append(e)
    by_version = []
    for v, sub in per_ver.items():
        m = metriche(sub)
        m["version"] = v
        by_version.append(m)
    # la versione con le previsioni piu' recenti per prima: e' quella che conta
    by_version.sort(key=lambda m: (m["al"] or ""), reverse=True)

    track = {
        "graded": len(graded), "pending": len(log["predictions"]) - len(graded),
        "brier": brier, "calibration": bins, "groups": groups, "clv": clv,
        "valueBets": {"n": n_bets, "wins": wins,
                       "profitUnits": round(profit, 3),
                       "roi": round(profit / n_bets, 4) if n_bets else None,
                       "history": bets[-100:]},
        "byVersion": by_version,
        "hitRate": hit,
        "bigMatch": big_match,
    }
    return track


def save_track(track):
    write_json(TRACK_FILE, track, indent=1)


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
