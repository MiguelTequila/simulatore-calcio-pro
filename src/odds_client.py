"""Client The Odds API. Aggrega TUTTI i bookmaker: media (per calibrazione)
e quota migliore (per il rilevamento del valore)."""
import os, json, requests, time
from datetime import datetime, timezone

BASE_URL = "https://api.the-odds-api.com/v4"

# Scarica anche le quote Goal/NoGoal (mercato "btts").
# COSTO: ogni chiamata costa (numero di mercati x numero di regioni) crediti.
# Con 2 mercati siamo a ~370-400 crediti/mese sui 500 gratuiti; con 3 mercati
# si arriva a ~550-600 e si sfora. Metti True SOLO se sei disposto a:
#   - ridurre ODDS_WINDOW_DAYS in update_data.py da 7 a 4, oppure
#   - togliere qualche competizione da SPORT_KEYS.
# Il badge in alto nell'app mostra sempre i crediti residui: controllalo.
INCLUDE_BTTS = False

# Solo le 6 leghe scelte (h2h + totals = 2 crediti a lega -> ~372/mese, sotto i 500)
SPORT_KEYS = {
    "PL":  "soccer_epl",
    "FL1": "soccer_france_ligue_one",
    "PD":  "soccer_spain_la_liga",
    "SA":  "soccer_italy_serie_a",
    "PPL": "soccer_portugal_primeira_liga",
    "BL1": "soccer_germany_bundesliga",
    "DED": "soccer_netherlands_eredivisie",
    "CL":  "soccer_uefa_champs_league",
}


class OddsAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("ODDSKEY", "")
        self.credits_remaining = None
        self.credits_used = None
        if not self.api_key:
            print("[!] ODDSKEY non trovata")

    def get_odds(self, sport_key, regions="eu", markets=None):
        if markets is None:
            markets = "h2h,totals,btts" if INCLUDE_BTTS else "h2h,totals"
        if not self.api_key:
            return []
        url = f"{BASE_URL}/sports/{sport_key}/odds"
        params = {"apiKey": self.api_key, "regions": regions, "markets": markets,
                  "oddsFormat": "decimal", "dateFormat": "iso"}
        try:
            r = requests.get(url, params=params, timeout=30)
            rem = r.headers.get("x-requests-remaining")
            used = r.headers.get("x-requests-used")
            if rem is not None:
                self.credits_remaining = rem
                self.credits_used = used
                print(f"    crediti Odds API rimasti: {rem} (usati: {used})")
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
        acc = {"1": [], "X": [], "2": [], "over25": [], "under25": [], "gg": [], "ng": []}
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
                elif market["key"] == "btts":
                    for o in market["outcomes"]:
                        n = o["name"].lower()
                        if n == "yes": acc["gg"].append(o["price"])
                        elif n == "no": acc["ng"].append(o["price"])

        def avg(v): return round(sum(v) / len(v), 3) if v else None
        def best(v): return round(max(v), 3) if v else None

        rec = {"homeTeam": home, "awayTeam": away, "commenceTime": event.get("commence_time"),
               "n_books": len(event.get("bookmakers", [])),
               "1": avg(acc["1"]), "X": avg(acc["X"]), "2": avg(acc["2"]),
               "over25": avg(acc["over25"]), "under25": avg(acc["under25"]),
               "gg": avg(acc["gg"]), "ng": avg(acc["ng"]),
               "best": {"1": best(acc["1"]), "X": best(acc["X"]), "2": best(acc["2"]),
                        "over25": best(acc["over25"]), "under25": best(acc["under25"]),
                        "gg": best(acc["gg"]), "ng": best(acc["ng"])}}
        return rec

    def fetch_all_odds(self, active_comps=None):
        """Se active_comps e' fornita, chiama l'API solo per quelle competizioni
        (risparmio crediti: le coppe giocano poche settimane)."""
        all_odds = {}
        for comp_id, sport_key in SPORT_KEYS.items():
            if active_comps is not None and comp_id not in active_comps:
                print(f"[→] Quote {comp_id}: saltate (nessuna partita in calendario)")
                all_odds[comp_id] = []
                continue
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
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "odds": odds}, f, ensure_ascii=False, indent=2)
    print("\n✅ Salvato odds.json")


if __name__ == "__main__":
    save_odds()
