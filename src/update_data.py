"""
Script principale per GitHub Actions.
Orchestra: download dati → Elo → Dixon-Coles → JSON finale per l'app.
"""
import json
import os
import sys

# Aggiungi src al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from football_data_client import fetch_all_data, COMPETITIONS
from odds_client import OddsAPIClient
from elo import compute_elo_ratings
from dixon_coles import compute_lambdas, calibrate_with_odds, dixon_coles_matrix, LEAGUE_RHO


def merge_odds(fixtures, odds_data):
    """Abbina quote ai match per nome squadra (fuzzy matching semplice)."""
    odds_by_comp = odds_data.get("odds", {})

    for comp_id, comp_fixtures in fixtures.items():
        comp_odds = odds_by_comp.get(comp_id, [])
        for fix in comp_fixtures:
            home = fix["homeTeam"].lower().replace("fc ", "").replace("cf ", "")
            away = fix["awayTeam"].lower().replace("fc ", "").replace("cf ", "")

            best_match = None
            for o in comp_odds:
                oh = o.get("homeTeam", "").lower().replace("fc ", "").replace("cf ", "")
                oa = o.get("awayTeam", "").lower().replace("fc ", "").replace("cf ", "")
                # Match semplice: controlla se entrambe le squadre sono contenute
                if (home in oh or oh in home) and (away in oa or oa in away):
                    best_match = o
                    break

            fix["odds"] = best_match

    return fixtures


def build_output():
    print("=" * 60)
    print("🚀 AGGIORNAMENTO DATI SIMULATORE")
    print("=" * 60)

    # 1. Scarica dati Football-Data
    print("\n[1/4] Scarico dati da Football-Data.org...")
    raw_data, all_matches = fetch_all_data()

    if not raw_data["competitions"]:
        print("[!] Nessun dato scaricato. Verifica FOOTBALL_DATA_KEY.")
        # Crea comunque un output vuoto per non rompere l'app
        with open("data/fixtures_processed.json", "w") as f:
            json.dump({"updated": raw_data["updated"], "competitions": {}}, f)
        return

    # 2. Calcola Elo
    print("\n[2/4] Calcolo rating Elo...")
    elo_ratings = compute_elo_ratings(all_matches)
    print(f"    ✓ {len(elo_ratings)} squadre rated")

    # 3. Scarica quote
    print("\n[3/4] Scarico quote da The Odds API...")
    odds_client = OddsAPIClient()
    odds_data = {"updated": raw_data["updated"], "odds": odds_client.fetch_all_odds()}
    with open("data/odds.json", "w") as f:
        json.dump(odds_data, f, ensure_ascii=False, indent=2)

    # 4. Calcola predizioni per ogni fixture
    print("\n[4/4] Calcolo predizioni Dixon-Coles...")

    output = {
        "updated": raw_data["updated"],
        "competitions": {}
    }

    for comp_id, comp_data in raw_data["competitions"].items():
        teams = comp_data["teams"]
        fixtures = comp_data.get("fixtures", [])

        if not fixtures:
            continue

        # Merge quote
        fixtures = merge_odds({comp_id: fixtures}, odds_data)[comp_id]

        processed_fixtures = []
        for fix in fixtures:
            home_id = fix["homeId"]
            away_id = fix["awayId"]
            home_name = fix["homeTeam"]
            away_name = fix["awayTeam"]

            home_stats = teams.get(home_id, {})
            away_stats = teams.get(away_id, {})

            elo_h = elo_ratings.get(home_name, {}).get("elo", 1500)
            elo_a = elo_ratings.get(away_name, {}).get("elo", 1500)

            # Lambda base
            lam_h, lam_a = compute_lambdas(
                home_stats, away_stats, elo_h, elo_a, comp_id
            )

            # Calibra con quote
            odds = fix.get("odds")
            lam_h, lam_a = calibrate_with_odds(lam_h, lam_a, odds, weight=0.60)

            # Modello Dixon-Coles
            rho = LEAGUE_RHO.get(comp_id, -0.07)
            prediction = dixon_coles_matrix(lam_h, lam_a, rho, max_goals=7)

            processed_fixtures.append({
                "id": fix["id"],
                "date": fix["date"],
                "time": fix.get("time", ""),
                "matchday": fix.get("matchday"),
                "homeTeam": home_name,
                "homeId": home_id,
                "awayTeam": away_name,
                "awayId": away_id,
                "homeStats": {
                    "gf_pg": home_stats.get("gf_pg", 0),
                    "ga_pg": home_stats.get("ga_pg", 0),
                    "form": home_stats.get("form", ""),
                    "elo": round(elo_h, 0),
                    "played": home_stats.get("played", 0),
                },
                "awayStats": {
                    "gf_pg": away_stats.get("gf_pg", 0),
                    "ga_pg": away_stats.get("ga_pg", 0),
                    "form": away_stats.get("form", ""),
                    "elo": round(elo_a, 0),
                    "played": away_stats.get("played", 0),
                },
                "odds": odds,
                "prediction": {
                    "lambdaH": round(lam_h, 3),
                    "lambdaA": round(lam_a, 3),
                    "rho": rho,
                    "p1": round(prediction["p1"], 4),
                    "px": round(prediction["px"], 4),
                    "p2": round(prediction["p2"], 4),
                    "pOver25": round(prediction["p_over25"], 4),
                    "pUnder25": round(prediction["p_under25"], 4),
                    "pGG": round(prediction["p_gg"], 4),
                    "pNG": round(prediction["p_ng"], 4),
                    "topExact": [(r, round(p, 4)) for r, p in prediction["top_exact"][:3]],
                    "totalGoalsDist": {str(k): round(v, 4) for k, v in prediction["total_goals_dist"].items()},
                }
            })

        output["competitions"][comp_id] = {
            "name": comp_data["name"],
            "country": comp_data["country"],
            "fixtures": processed_fixtures
        }
        print(f"    ✓ {comp_id}: {len(processed_fixtures)} predizioni calcolate")

    # Salva output finale
    with open("data/fixtures_processed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Salva anche Elo per riferimento
    with open("data/elo_ratings.json", "w", encoding="utf-8") as f:
        json.dump(elo_ratings, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("✅ TUTTO AGGIORNATO!")
    print("   → data/fixtures_processed.json (predizioni)")
    print("   → data/odds.json (quote)")
    print("   → data/elo_ratings.json (rating)")
    print("=" * 60)


if __name__ == "__main__":
    build_output()
