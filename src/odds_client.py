"""Client The Odds API. Aggrega TUTTI i bookmaker: media (per calibrazione)
e quota migliore (per il rilevamento del valore)."""
import os, json, requests, time
from datetime import datetime

BASE_URL = "https://api.the-odds-api.com/v4"

# Solo le 6 leghe scelte (h2h + totals = 2 crediti a lega -> ~372/mese, sotto i 500)
SPORT_KEYS = {
    "PL":  "soccer_epl",
    "FL1": "soccer_france_ligue_one",
    "PD":  "soccer_spain_la_liga",
    "SA":  "soccer_italy_serie_a",
    "PPL": "soccer_portugal_primeira_liga",
    "BL1": "soccer_germany_bundesliga",
}


class OddsAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("ODDSKEY", "")
        if not self.api_key:
            print("[!] ODDSKEY non trovata")

    def get_odds(self, sport_key, regions="eu", markets="h2h,totals"):
        if not self.api_key:
            return []
        url = f"{BASE_URL}/sports/{sport_key}/odds"
        params = {"apiKey": self.api_key, "regions": regions, "markets": markets,
                  "oddsFormat": "decimal", "dateFormat": "iso"}
        try:
            r = requests.get(url, params=params, timeout=30)
            rem = r.headers.get("x-requests-remaining")
            if rem is not None:
                print(f"    crediti Odds API rimasti: {rem}")
            if r.status_code == 429:
                print(f"[!] Rate limit {sport_key}")
                return []
            r.raise_for_status()
            time.sleep(2)
            return r.json()
        except Exception as e:
            print(f"[!] Errore Odds {sport_key}: {e}")
            return []

    def parse_match_odds(self, event):
        home, away = event.get("home_team"), event.get("away_team")
        acc = {"1": [], "X": [], "2": [], "over25": [], "under25": []}
        for bk in event.get("bookmakers", []):
            for market in bk.get("markets", []):
                if market["key"] == "h2h":
                    for o in market["outcomes"]:
                        n, price = o["name"], o["price"]
                        if n == home: acc["1"].append(price)
                        elif n == away: acc["2"].append(price)
                        elif n.lower() in ("draw", "x"): acc["X"].append(price)
                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        if o.get("point") == 2.5:
                            if o["name"].lower() == "over": acc["over25"].append(o["price"])
                            elif o["name"].lower() == "under": acc["under25"].append(o["price"])

        def avg(v): return round(sum(v) / len(v), 3) if v else None
        def best(v): return round(max(v), 3) if v else None

        rec = {"homeTeam": home, "awayTeam": away, "commenceTime": event.get("commence_time"),
               "n_books": len(event.get("bookmakers", [])),
               "1": avg(acc["1"]), "X": avg(acc["X"]), "2": avg(acc["2"]),
               "over25": avg(acc["over25"]), "under25": avg(acc["under25"]),
               "gg": None, "ng": None,
               "best": {"1": best(acc["1"]), "X": best(acc["X"]), "2": best(acc["2"]),
                        "over25": best(acc["over25"]), "under25": best(acc["under25"])}}
        return rec

    def fetch_all_odds(self):
        all_odds = {}
        for comp_id, sport_key in SPORT_KEYS.items():
            print(f"[→] Quote {comp_id}")
            events = self.get_odds(sport_key)
            parsed = []
            for ev in events:
                po = self.parse_match_odds(ev)
                if po["1"] and po["X"] and po["2"]:
                    parsed.append(po)
            all_odds[comp_id] = parsed
            print(f"    ✓ {len(parsed)} match")
        return all_odds


def save_odds():
    client = OddsAPIClient()
    odds = client.fetch_all_odds()
    with open("data/odds.json", "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().isoformat(), "odds": odds}, f, ensure_ascii=False, indent=2)
    print("\n✅ Salvato odds.json")


if __name__ == "__main__":
    save_odds()
