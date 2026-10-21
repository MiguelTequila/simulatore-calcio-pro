import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from football_data_client import fetch_all_data, COMPETITIONS
from odds_client import ODDS_ONLY
from team_match import build_index, find_team
from odds_client import OddsAPIClient
from elo import load_state, update_ratings_incremental, save_state
from track_record import load_log, save_log, log_predictions, reconcile_results, build_track_record, save_track
from dixon_coles import (compute_lambdas, calibrate_with_odds, dixon_coles_matrix,
                         compute_value, league_average, LEAGUE_RHO, DEFAULT_RHO,
                         MARKET_WEIGHT, MODEL_VERSION)


def merge_odds(fixtures, odds_data):
    odds_by_comp = odds_data.get("odds", {})
    for comp_id, comp_fixtures in fixtures.items():
        comp_odds = odds_by_comp.get(comp_id, [])
        for fix in comp_fixtures:
            home = fix["homeTeam"].lower().replace("fc ", "").replace("cf ", "")
            away = fix["awayTeam"].lower().replace("fc ", "").replace("cf ", "")
            best = None
            for o in comp_odds:
                oh = o.get("homeTeam", "").lower().replace("fc ", "").replace("cf ", "")
                oa = o.get("awayTeam", "").lower().replace("fc ", "").replace("cf ", "")
                if (home in oh or oh in home) and (away in oa or oa in away):
                    best = o
                    break
            fix["odds"] = best
    return fixtures


def build_odds_only_competitions(odds_data, team_index, elo_ratings):
    """Europa League e Conference non sono nel piano gratuito di Football-Data.
    Ricostruiamo il calendario dalle quote e prendiamo le statistiche delle
    squadre dai campionati nazionali che gia' seguiamo. Dove una squadra non
    e' coperta (campionati minori) la partita resta segnata come incompleta
    e il consigliere non la propone."""
    out = {}
    for comp_id, meta in ODDS_ONLY.items():
        events = (odds_data.get("odds") or {}).get(comp_id) or []
        if not events:
            continue
        fixtures, full, partial, none = [], 0, 0, 0
        for ev in events:
            ct = ev.get("commenceTime") or ""
            h_raw, a_raw = ev.get("homeTeam"), ev.get("awayTeam")
            if not h_raw or not a_raw:
                continue
            ht = find_team(h_raw, team_index)
            at = find_team(a_raw, team_index)
            quality = "full" if (ht and at) else ("partial" if (ht or at) else "none")
            if quality == "full": full += 1
            elif quality == "partial": partial += 1
            else: none += 1

            hname = ht["name"] if ht else h_raw
            aname = at["name"] if at else a_raw
            # id stabile fra un aggiornamento e l'altro: serve al registro esiti
            fid = "%s-%s-%s-%s" % (comp_id, ct[:10], _slug(hname), _slug(aname))
            fixtures.append({
                "id": fid, "date": ct[:10], "time": ct[11:16], "matchday": None,
                "homeTeam": hname, "homeId": fid + "-h",
                "awayTeam": aname, "awayId": fid + "-a",
                "homeStatsSrc": ht or {}, "awayStatsSrc": at or {},
                "dataQuality": quality,
                "odds": ev,
            })
        if not fixtures:
            continue
        fixtures.sort(key=lambda f: (f["date"], f["time"]))
        out[comp_id] = {"name": meta["name"], "country": meta["country"],
                        "fixtures": fixtures, "quality": {"full": full, "partial": partial, "none": none}}
        print(f"    {comp_id}: {len(fixtures)} partite dalle quote "
              f"(statistiche complete {full}, parziali {partial}, assenti {none})")
    return out


def _slug(name):
    import re, unicodedata
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", s)[:14]


def build_output():
    print("=" * 60)
    print("AGGIORNAMENTO DATI SIMULATORE")
    print("=" * 60)

    print("\n[1/5] Scarico dati Football-Data...")
    raw_data, all_matches = fetch_all_data()

    if not raw_data["competitions"]:
        # PROTEZIONE DATI: se Football-Data non risponde (403, rate limit, disservizio)
        # NON sovrascriviamo il file buono con uno vuoto, altrimenti il sito si svuota.
        # Lasciamo i dati precedenti e usciamo senza errore (niente mail di fallimento).
        print("[!] Nessun dato ricevuto da Football-Data (chiave, quota o disservizio).")
        if os.path.exists("data/fixtures_processed.json"):
            print("[=] Dati precedenti CONSERVATI: nessuna modifica al file.")
        else:
            os.makedirs("data", exist_ok=True)
            with open("data/fixtures_processed.json", "w", encoding="utf-8") as f:
                json.dump({"updated": raw_data["updated"], "competitions": {},
                           "error": "nessun dato disponibile al primo avvio"}, f)
        return

    print("\n[2/5] Aggiorno Elo (persistente)...")
    state = load_state()
    elo_ratings, state, n_new = update_ratings_incremental(all_matches, state)
    save_state(state)
    print(f"    {len(elo_ratings)} squadre in memoria, {n_new} partite nuove conteggiate")

    print("\n[3/5] Scarico quote (solo competizioni con partite in calendario)...")
    # Le quote servono solo per le partite imminenti: chiediamo l'API solo per le
    # competizioni che giocano entro ODDS_WINDOW_DAYS. Le fixture restano a 45 giorni
    # (quelle costano Football-Data, che e' gratis), ma i crediti Odds si spendono
    # solo dove servono davvero.
    ODDS_WINDOW_DAYS = 7
    from datetime import datetime as _dt, timedelta as _td
    _limit = (_dt.now() + _td(days=ODDS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    active = [cid for cid, c in raw_data["competitions"].items()
              if not COMPETITIONS.get(cid, {}).get("statsOnly")          # la Primeira Liga serve
              and any(f.get("date", "9999") <= _limit for f in c.get("fixtures", []))]  # solo per le statistiche
    # Europa League e Conference non esistono in Football-Data: senza questa riga
    # non finirebbero mai fra le competizioni attive e non verrebbero scaricate.
    active += [cid for cid in ODDS_ONLY if cid not in active]
    odds_client = OddsAPIClient()
    odds_data = {"updated": raw_data["updated"], "odds": odds_client.fetch_all_odds(active_comps=active)}
    with open("data/odds.json", "w", encoding="utf-8") as f:
        json.dump(odds_data, f, ensure_ascii=False, indent=2)

    print("\n[4/5] Calcolo predizioni + valore...")
    # Crediti: se in questo giro non abbiamo interrogato l'API (nessuna partita
    # entro la finestra), gli header non arrivano. In quel caso conserviamo
    # l'ultimo valore noto invece di mostrare "n/d".
    _cred = {"remaining": odds_client.credits_remaining, "used": odds_client.credits_used,
             "checkedAt": raw_data["updated"], "stale": False}
    if _cred["remaining"] is None:
        try:
            with open("data/fixtures_processed.json", encoding="utf-8") as _f:
                _prev = json.load(_f).get("apiCredits") or {}
            if _prev.get("remaining") is not None:
                _cred = {"remaining": _prev["remaining"], "used": _prev.get("used"),
                         "checkedAt": _prev.get("checkedAt"), "stale": True}
        except Exception:
            pass
        if _cred["remaining"] is None:
            _cred["note"] = "nessuna chiamata effettuata (nessuna partita entro la finestra quote)"

    output = {"updated": raw_data["updated"], "modelVersion": MODEL_VERSION, "marketWeight": MARKET_WEIGHT,
              "oddsWindowDays": ODDS_WINDOW_DAYS,
              "apiCredits": _cred,
              "competitions": {}}

    for comp_id, comp_data in raw_data["competitions"].items():
        if COMPETITIONS.get(comp_id, {}).get("statsOnly"):
            print(f"    {comp_id}: usata solo come fonte di statistiche, non pubblicata")
            continue
        teams = comp_data["teams"]
        fixtures = comp_data.get("fixtures", [])
        if not fixtures:
            continue
        fixtures = merge_odds({comp_id: fixtures}, odds_data)[comp_id]
        rho = LEAGUE_RHO.get(comp_id, DEFAULT_RHO)
        # media gol della lega ricalcolata dai dati veri di questa stagione
        lg_avg = league_average(teams, comp_id)
        print(f"    {comp_id}: media gol/partita della lega = {lg_avg:.3f}")
        processed = []

        for fix in fixtures:
            hid, aid = fix["homeId"], fix["awayId"]
            hname, aname = fix["homeTeam"], fix["awayTeam"]
            hs = teams.get(hid, {})
            ast = teams.get(aid, {})
            eh = elo_ratings.get(hname, {}).get("elo", 1500)
            ea = elo_ratings.get(aname, {}).get("elo", 1500)

            raw_h, raw_a = compute_lambdas(hs, ast, eh, ea, comp_id, league_avg=lg_avg)
            odds = fix.get("odds")
            lam_h, lam_a = calibrate_with_odds(raw_h, raw_a, odds, rho=rho, weight=MARKET_WEIGHT)
            pred = dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7)
            value = compute_value(pred, odds)

            processed.append({
                "id": fix["id"], "date": fix["date"], "time": fix.get("time", ""),
                "matchday": fix.get("matchday"),
                "homeTeam": hname, "homeId": hid, "awayTeam": aname, "awayId": aid,
                "homeStats": {"gf_pg": hs.get("gf_pg", 0), "ga_pg": hs.get("ga_pg", 0),
                              "form": hs.get("form", ""), "elo": round(eh, 0), "played": hs.get("played", 0)},
                "awayStats": {"gf_pg": ast.get("gf_pg", 0), "ga_pg": ast.get("ga_pg", 0),
                              "form": ast.get("form", ""), "elo": round(ea, 0), "played": ast.get("played", 0)},
                "odds": odds,
                "dataQuality": "full" if (hs.get("played") and ast.get("played")) else "partial",
                "prediction": {
                    "lambdaH": round(lam_h, 3), "lambdaA": round(lam_a, 3), "rho": rho,
                    "lambdaHRaw": round(raw_h, 3), "lambdaARaw": round(raw_a, 3),
                    "modelVersion": MODEL_VERSION, "leagueAvg": round(lg_avg, 3),
                    "marketWeight": MARKET_WEIGHT,
                    "p1": round(pred["p1"], 4), "px": round(pred["px"], 4), "p2": round(pred["p2"], 4),
                    "pOver25": round(pred["p_over25"], 4), "pUnder25": round(pred["p_under25"], 4),
                    "pGG": round(pred["p_gg"], 4), "pNG": round(pred["p_ng"], 4),
                    "topExact": [(r, round(p, 4)) for r, p in pred["top_exact"][:3]],
                    "totalGoalsDist": {str(k): round(v, 4) for k, v in pred["total_goals_dist"].items()},
                    "value": value,
                }
            })

        output["competitions"][comp_id] = {
            "name": comp_data["name"], "country": comp_data["country"], "fixtures": processed
        }
        n_val = sum(1 for p in processed if p["prediction"]["value"] and p["prediction"]["value"]["bestBet"])
        print(f"    {comp_id}: {len(processed)} predizioni, {n_val} con valore")

    # --- Coppe europee senza Football-Data: calendario dalle quote ---
    team_index = build_index({cid: c.get("teams", {}) for cid, c in raw_data["competitions"].items()})
    print(f"\n    Indice squadre per le coppe: {len(team_index)} squadre da {len(raw_data['competitions'])} competizioni")
    for comp_id, comp in build_odds_only_competitions(odds_data, team_index, elo_ratings).items():
        rho = LEAGUE_RHO.get(comp_id, DEFAULT_RHO)
        pool = {i: f["homeStatsSrc"] for i, f in enumerate(comp["fixtures"]) if f["homeStatsSrc"]}
        pool.update({-i - 1: f["awayStatsSrc"] for i, f in enumerate(comp["fixtures"]) if f["awayStatsSrc"]})
        lg_avg = league_average(pool, comp_id)
        processed = []
        for fix in comp["fixtures"]:
            hs, ast = fix["homeStatsSrc"], fix["awayStatsSrc"]
            hname, aname = fix["homeTeam"], fix["awayTeam"]
            eh = elo_ratings.get(hname, {}).get("elo", 1500)
            ea = elo_ratings.get(aname, {}).get("elo", 1500)
            raw_h, raw_a = compute_lambdas(hs, ast, eh, ea, comp_id, league_avg=lg_avg)
            odds = fix.get("odds")
            lam_h, lam_a = calibrate_with_odds(raw_h, raw_a, odds, rho=rho, weight=MARKET_WEIGHT)
            pred = dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7)
            # Il valore si calcola solo se conosciamo DAVVERO entrambe le squadre:
            # altrimenti staremmo confrontando il mercato con una media di lega.
            value = compute_value(pred, odds) if fix["dataQuality"] == "full" else None
            processed.append({
                "id": fix["id"], "date": fix["date"], "time": fix.get("time", ""),
                "matchday": None, "homeTeam": hname, "homeId": fix["homeId"],
                "awayTeam": aname, "awayId": fix["awayId"],
                "homeStats": {"gf_pg": hs.get("gf_pg", 0), "ga_pg": hs.get("ga_pg", 0),
                              "form": hs.get("form", ""), "elo": round(eh, 0), "played": hs.get("played", 0),
                              "src": hs.get("_league", "")},
                "awayStats": {"gf_pg": ast.get("gf_pg", 0), "ga_pg": ast.get("ga_pg", 0),
                              "form": ast.get("form", ""), "elo": round(ea, 0), "played": ast.get("played", 0),
                              "src": ast.get("_league", "")},
                "odds": odds, "dataQuality": fix["dataQuality"],
                "prediction": {
                    "lambdaH": round(lam_h, 3), "lambdaA": round(lam_a, 3), "rho": rho,
                    "lambdaHRaw": round(raw_h, 3), "lambdaARaw": round(raw_a, 3),
                    "modelVersion": MODEL_VERSION, "leagueAvg": round(lg_avg, 3),
                    "marketWeight": MARKET_WEIGHT,
                    "p1": round(pred["p1"], 4), "px": round(pred["px"], 4), "p2": round(pred["p2"], 4),
                    "pOver25": round(pred["p_over25"], 4), "pUnder25": round(pred["p_under25"], 4),
                    "pGG": round(pred["p_gg"], 4), "pNG": round(pred["p_ng"], 4),
                    "topExact": [(r, round(p, 4)) for r, p in pred["top_exact"][:3]],
                    "totalGoalsDist": {str(k): round(v, 4) for k, v in pred["total_goals_dist"].items()},
                    "value": value,
                }
            })
        output["competitions"][comp_id] = {"name": comp["name"], "country": comp["country"],
                                           "fixtures": processed, "quality": comp["quality"]}

    print("\n[5/5] Registro esiti e calibrazione...")
    plog = load_log()
    n_rec = reconcile_results(plog, raw_data["competitions"])
    for comp_id, comp in output["competitions"].items():
        log_predictions(plog, comp_id, comp["name"], comp["fixtures"])
    save_log(plog)
    track = build_track_record(plog)
    save_track(track)
    print(f"    {n_rec} risultati agganciati | {track['graded']} valutate, {track['pending']} in attesa | value bet: {track['valueBets']['n']} (P&L {track['valueBets']['profitUnits']:+.2f} u)")

    with open("data/fixtures_processed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open("data/elo_ratings.json", "w", encoding="utf-8") as f:
        json.dump(elo_ratings, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("COMPLETATO!")
    print("=" * 60)


if __name__ == "__main__":
    build_output()
