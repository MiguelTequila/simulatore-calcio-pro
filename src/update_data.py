import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from football_data_client import fetch_all_data, COMPETITIONS
from odds_client import OddsAPIClient
from elo import load_state, update_ratings_incremental, save_state
from track_record import load_log, save_log, log_predictions, reconcile_results, build_track_record, save_track
from dixon_coles import (compute_lambdas, calibrate_with_odds, dixon_coles_matrix,
                         compute_value, LEAGUE_RHO, DEFAULT_RHO, MARKET_WEIGHT)


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


def build_output():
    print("=" * 60)
    print("AGGIORNAMENTO DATI SIMULATORE")
    print("=" * 60)

    print("\n[1/5] Scarico dati Football-Data...")
    raw_data, all_matches = fetch_all_data()

    if not raw_data["competitions"]:
        print("[!] Nessun dato. Verifica FDKEY.")
        with open("data/fixtures_processed.json", "w") as f:
            json.dump({"updated": raw_data["updated"], "competitions": {}}, f)
        return

    print("\n[2/5] Aggiorno Elo (persistente)...")
    state = load_state()
    elo_ratings, state, n_new = update_ratings_incremental(all_matches, state)
    save_state(state)
    print(f"    {len(elo_ratings)} squadre in memoria, {n_new} partite nuove conteggiate")

    print("\n[3/5] Scarico quote (solo competizioni con partite in calendario)...")
    active = [cid for cid, c in raw_data["competitions"].items() if c.get("fixtures")]
    odds_client = OddsAPIClient()
    odds_data = {"updated": raw_data["updated"], "odds": odds_client.fetch_all_odds(active_comps=active)}
    with open("data/odds.json", "w", encoding="utf-8") as f:
        json.dump(odds_data, f, ensure_ascii=False, indent=2)

    print("\n[4/5] Calcolo predizioni + valore...")
    output = {"updated": raw_data["updated"], "marketWeight": MARKET_WEIGHT,
              "apiCredits": {"remaining": odds_client.credits_remaining, "used": odds_client.credits_used},
              "competitions": {}}

    for comp_id, comp_data in raw_data["competitions"].items():
        teams = comp_data["teams"]
        fixtures = comp_data.get("fixtures", [])
        if not fixtures:
            continue
        fixtures = merge_odds({comp_id: fixtures}, odds_data)[comp_id]
        rho = LEAGUE_RHO.get(comp_id, DEFAULT_RHO)
        processed = []

        for fix in fixtures:
            hid, aid = fix["homeId"], fix["awayId"]
            hname, aname = fix["homeTeam"], fix["awayTeam"]
            hs = teams.get(hid, {})
            ast = teams.get(aid, {})
            eh = elo_ratings.get(hname, {}).get("elo", 1500)
            ea = elo_ratings.get(aname, {}).get("elo", 1500)

            lam_h, lam_a = compute_lambdas(hs, ast, eh, ea, comp_id)
            odds = fix.get("odds")
            lam_h, lam_a = calibrate_with_odds(lam_h, lam_a, odds, rho=rho, weight=MARKET_WEIGHT)
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
                "prediction": {
                    "lambdaH": round(lam_h, 3), "lambdaA": round(lam_a, 3), "rho": rho,
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
