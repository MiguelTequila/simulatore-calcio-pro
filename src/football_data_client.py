import os, json, requests, time
from datetime import datetime, timedelta

BASE_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "PL":  {"name": "Premier League", "country": "England"},
    "FL1": {"name": "Ligue 1", "country": "France"},
    "PD":  {"name": "La Liga", "country": "Spain"},
    "SA":  {"name": "Serie A", "country": "Italy"},
    "PPL": {"name": "Primeira Liga", "country": "Portugal"},
    "BL1": {"name": "Bundesliga", "country": "Germany"},
    "CL": {"name": "Champions League", "country": "Europe"},
    "EL": {"name": "Europa League", "country": "Europe"},
    "ECL": {"name": "Conference League", "country": "Europe"},
    "BSA": {"name": "Brasileirão", "country": "Brazil"},
    "ALL": {"name": "Allsvenskan", "country": "Sweden"},
    "ELI": {"name": "Eliteserien", "country": "Norway"},
    "VEIK": {"name": "Veikkausliiga", "country": "Finland"},
}

class FootballDataClient:
    def __init__(self):
        self.api_key = os.environ.get("FDKEY", "")
        self.headers = {"X-Auth-Token": self.api_key} if self.api_key else {}
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get(self, endpoint, params=None):
        url = f"{BASE_URL}{endpoint}"
        try:
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                print(f"[!] Rate limit {endpoint}")
                return None
            r.raise_for_status()
            time.sleep(7)  # Rate limit piano free: max 10 req/min
            return r.json()
        except Exception as e:
            print(f"[!] Errore {endpoint}: {e}")
            return None

    def get_standings(self, comp_id):
        data = self._get(f"/competitions/{comp_id}/standings")
        if not data or "standings" not in data:
            return None
        teams = {}
        for table in data.get("standings", []):
            for row in table.get("table", []):
                t = row["team"]
                tid = t["id"]
                played = row.get("playedGames", 0)
                if played == 0:
                    continue
                teams[tid] = {
                    "id": tid, "name": t["name"], "shortName": t.get("shortName", t["name"]),
                    "crest": t.get("crest", ""), "played": played,
                    "won": row.get("won", 0), "draw": row.get("draw", 0), "lost": row.get("lost", 0),
                    "gf": row.get("goalsFor", 0), "ga": row.get("goalsAgainst", 0),
                    "gd": row.get("goalDifference", 0), "points": row.get("points", 0),
                    "gf_pg": round(row.get("goalsFor", 0) / played, 2),
                    "ga_pg": round(row.get("goalsAgainst", 0) / played, 2),
                }
        return teams

    def get_recent_matches(self, comp_id, days_back=60):
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        data = self._get(f"/competitions/{comp_id}/matches", {
            "dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"
        })
        if not data:
            return []
        matches = []
        for m in data.get("matches", []):
            matches.append({
                "id": m["id"], "date": m["utcDate"][:10],
                "homeTeam": m["homeTeam"]["name"], "homeId": m["homeTeam"]["id"],
                "awayTeam": m["awayTeam"]["name"], "awayId": m["awayTeam"]["id"],
                "homeGoals": m["score"]["fullTime"]["home"],
                "awayGoals": m["score"]["fullTime"]["away"],
                "winner": m["score"]["winner"],
            })
        return matches

    def get_upcoming(self, comp_id, days_ahead=14):
        date_from = datetime.now().strftime("%Y-%m-%d")
        date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        data = self._get(f"/competitions/{comp_id}/matches", {
            "dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"
        })
        if not data:
            return []
        fixtures = []
        for m in data.get("matches", []):
            fixtures.append({
                "id": m["id"], "date": m["utcDate"][:10], "time": m["utcDate"][11:16],
                "matchday": m.get("matchday"),
                "homeTeam": m["homeTeam"]["name"], "homeId": m["homeTeam"]["id"],
                "awayTeam": m["awayTeam"]["name"], "awayId": m["awayTeam"]["id"],
            })
        return fixtures

    def get_team_matches(self, team_id, limit=10):
        # Disabilitato per evitare rate limit su piano free
        return []

    def compute_form_from_matches(self, team_id, matches, limit=5):
        """Calcola forma W/D/L dai match già in memoria (zero chiamate API)."""
        team_matches = [m for m in matches if m["homeId"] == team_id or m["awayId"] == team_id]
        team_matches.sort(key=lambda x: x["date"], reverse=True)
        results = []
        for m in team_matches[:limit]:
            home = m["homeId"] == team_id
            hg = m.get("homeGoals")
            ag = m.get("awayGoals")
            if hg is None or ag is None:
                continue
            if home:
                res = "W" if hg > ag else ("D" if hg == ag else "L")
            else:
                res = "W" if ag > hg else ("D" if ag == hg else "L")
            results.append(res)
        return results


def fetch_all_data():
    client = FootballDataClient()
    output = {"updated": datetime.now().isoformat(), "competitions": {}}
    all_matches = []

    for comp_id, meta in COMPETITIONS.items():
        print(f"[→] {meta['name']} ({comp_id})")
        teams = client.get_standings(comp_id)
        recent = client.get_recent_matches(comp_id, days_back=90)
        upcoming = client.get_upcoming(comp_id, days_ahead=45)

        if not teams:
            print(f"    [!] Nessun dato squadre")
            continue

        for tid, tinfo in teams.items():
            form = client.compute_form_from_matches(tid, recent, limit=5)
            tinfo["form"] = "".join(form) if form else ""

        output["competitions"][comp_id] = {
            "name": meta["name"], "country": meta["country"],
            "teams": teams, "recentMatches": recent, "fixtures": upcoming
        }
        all_matches.extend(recent)
        print(f"    ✓ {len(teams)} squadre, {len(recent)} recenti, {len(upcoming)} upcoming")

    return output, all_matches


if __name__ == "__main__":
    data, matches = fetch_all_data()
    with open("data/raw_football_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Salvato raw_football_data.json")
