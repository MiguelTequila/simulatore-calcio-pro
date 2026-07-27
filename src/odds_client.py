"""
Client per The Odds API v4.
Free tier: 500 richieste/mese.
Copre tutte le leghe principali europee + Brasile, Scandinavia.
"""
import os
import json
import requests
from datetime import datetime

BASE_URL = "https://api.the-odds-api.com/v4"

# Mappa sport keys Odds API
SPORT_KEYS = {
    "PL":   "soccer_epl",
    "ELC":  "soccer_england_efl",
    "SA":   "soccer_italy_serie_a",
    "PD":   "soccer_spain_la_liga",
    "BL1":  "soccer_germany_bundesliga",
    "FL1":  "soccer_france_ligue_one",
    "DED":  "soccer_netherlands_eredivisie",
    "PPL":  "soccer_portugal_primeira_liga",
    "CL":   "soccer_uefa_champs_league",
    "EL":   "soccer_uefa_europa_league",
    "ECL":  "soccer_uefa_europa_conference_league",
    "BSA":  "soccer_brazil_campeonato",
    "ALL":  "soccer_sweden_allsvenskan",
    "ELI":  "soccer_norway_eliteserien",
    "VEIK": "soccer_finland_veikkausliiga",
}

class OddsAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("ODDSKEY", "")
        if not self.api_key:
            print("[!] ODDS_API_KEY non trovata — quote non disponibili")

    def get_odds(self, sport_key, regions="eu", markets="h2h,totals"):
        """Scarica quote per uno sport."""
        if not self.api_key:
            return []
        url = f"{BASE_URL}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                print(f"[!] Rate limit Odds API per {sport_key}")
                return []
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[!] Errore Odds API {sport_key}: {e}")
            return []

    def parse_match_odds(self, event):
        """Estrae quote 1X2, Over/Under 2.5, GG/NG da un evento."""
        result = {
            "homeTeam": event.get("home_team"),
            "awayTeam": event.get("away_team"),
            "commenceTime": event.get("commence_time"),
            "1": None, "X": None, "2": None,
            "over25": None, "under25": None,
            "gg": None, "ng": None,
        }

        for bookmaker in event.get("bookmakers", [])[:3]:  # top 3 bookmaker
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        name = outcome["name"]
                        price = outcome["price"]
                        if name == event.get("home_team"):
                            result["1"] = price
                        elif name == event.get("away_team"):
                            result["2"] = price
                        elif name.lower() in ("draw", "x", "pareggio"):
                            result["X"] = price

                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome["name"].lower() == "over" and outcome.get("point") == 2.5:
                            result["over25"] = outcome["price"]
                        elif outcome["name"].lower() == "under" and outcome.get("point") == 2.5:
                            result["under25"] = outcome["price"]

                elif market["key"] == "btts":  # Both Teams To Score = GG/NG
                    for outcome in market["outcomes"]:
                        if outcome["name"].lower() in ("yes", "true"):
                            result["gg"] = outcome["price"]
                        elif outcome["name"].lower() in ("no", "false"):
                            result["ng"] = outcome["price"]

        return result

    def fetch_all_odds(self):
        """Scarica quote per tutte le competizioni mappate."""
        all_odds = {}
        for comp_id, sport_key in SPORT_KEYS.items():
            print(f"[→] Quote per {comp_id} ({sport_key})...")
            events = self.get_odds(sport_key)
            parsed = []
            for ev in events:
                po = self.parse_match_odds(ev)
                if po["1"] and po["X"] and po["2"]:
                    parsed.append(po)
            all_odds[comp_id] = parsed
            print(f"    ✓ {len(parsed)} match con quote")
        return all_odds


def save_odds():
    client = OddsAPIClient()
    odds = client.fetch_all_odds()
    with open("data/odds.json", "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().isoformat(), "odds": odds}, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Salvato odds.json")


if __name__ == "__main__":
    save_odds()
