import json
from collections import defaultdict

K = 32
HOME_ADV = 65

def expected_score(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))

def update_elo(rating, expected, actual, k=K):
    return rating + k * (actual - expected)

def compute_elo_ratings(all_matches, initial_rating=1500):
    ratings = defaultdict(lambda: {"elo": initial_rating, "games": 0})
    matches = sorted(all_matches, key=lambda m: m.get("date", ""))

    for m in matches:
        home, away = m["homeTeam"], m["awayTeam"]
        hg, ag = m.get("homeGoals", 0), m.get("awayGoals", 0)
        if hg is None or ag is None:
            continue
        rh, ra = ratings[home]["elo"], ratings[away]["elo"]
        eh = expected_score(rh + HOME_ADV, ra)
        ea = expected_score(ra, rh + HOME_ADV)
        if hg > ag: ah, aa = 1, 0
        elif hg == ag: ah, aa = 0.5, 0.5
        else: ah, aa = 0, 1
        ratings[home]["elo"] = update_elo(rh, eh, ah)
        ratings[away]["elo"] = update_elo(ra, ea, aa)
        ratings[home]["games"] += 1
        ratings[away]["games"] += 1

    return {k: dict(v) for k, v in ratings.items()}


if __name__ == "__main__":
    with open("data/raw_football_data.json") as f:
        data = json.load(f)
    all_matches = []
    for comp in data["competitions"].values():
        all_matches.extend(comp.get("recentMatches", []))
    elo = compute_elo_ratings(all_matches)
    print(f"Elo per {len(elo)} squadre")
