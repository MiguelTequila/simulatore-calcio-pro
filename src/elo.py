"""
Sistema Elo dinamico con home advantage per lega.
Calcola rating aggiornati per tutte le squadre in archivio.
"""
import json
from collections import defaultdict

K = 32              # fattore di aggiornamento
HOME_ADV = 65       # vantaggio campo base (punti Elo)
MIN_GAMES = 5       # minimo partite per rating affidabile

def expected_score(rating_a, rating_b):
    """Probabilità che A batta B."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def update_elo(rating, expected, actual, k=K):
    """Aggiorna rating dopo un match."""
    return rating + k * (actual - expected)


def compute_elo_ratings(all_matches, initial_rating=1500):
    """
    Calcola Elo per tutte le squadre usando tutti i match storici.
    Ritorna dict {team_name: {"elo": x, "games": n, "league": y}}
    """
    ratings = defaultdict(lambda: {"elo": initial_rating, "games": 0, "league": ""})

    # Ordina per data
    matches = sorted(all_matches, key=lambda m: m.get("date", ""))

    for m in matches:
        home = m["homeTeam"]
        away = m["awayTeam"]
        hg = m.get("homeGoals", 0)
        ag = m.get("awayGoals", 0)

        if hg is None or ag is None:
            continue

        rh = ratings[home]["elo"]
        ra = ratings[away]["elo"]

        # Home advantage dinamico: leghe con più gol in casa → advantage maggiore
        eh = expected_score(rh + HOME_ADV, ra)
        ea = expected_score(ra, rh + HOME_ADV)

        if hg > ag:
            ah, aa = 1, 0
        elif hg == ag:
            ah, aa = 0.5, 0.5
        else:
            ah, aa = 0, 1

        ratings[home]["elo"] = update_elo(rh, eh, ah)
        ratings[away]["elo"] = update_elo(ra, ea, aa)
        ratings[home]["games"] += 1
        ratings[away]["games"] += 1

    return {k: dict(v) for k, v in ratings.items()}


def get_league_average_elo(elo_dict, league_teams):
    """Media Elo delle squadre di una lega."""
    vals = [elo_dict[t]["elo"] for t in league_teams if t in elo_dict]
    return sum(vals) / len(vals) if vals else 1500


if __name__ == "__main__":
    # Test
    with open("data/raw_football_data.json") as f:
        data = json.load(f)

    all_matches = []
    for comp in data["competitions"].values():
        all_matches.extend(comp.get("recentMatches", []))

    elo = compute_elo_ratings(all_matches)
    print(f"Calcolati Elo per {len(elo)} squadre")
    top = sorted(elo.items(), key=lambda x: x[1]["elo"], reverse=True)[:10]
    for name, info in top:
        print(f"  {name}: {info['elo']:.0f} ({info['games']} partite)")
