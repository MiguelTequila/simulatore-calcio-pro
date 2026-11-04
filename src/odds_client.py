"""Client The Odds API. Aggrega TUTTI i bookmaker: media (per calibrazione)
e quota migliore (per il rilevamento del valore)."""
import os, json, requests, time
from datetime import datetime, timezone

BASE_URL = "https://api.the-odds-api.com/v4"

# Scarica anche le quote Goal/NoGoal (mercato "btts"), cosi' GG e NG non vanno
# piu' digitati a mano nel riquadro "Quote tue".
# COSTO: ogni chiamata costa (numero di mercati x numero di regioni) crediti.
# Con la sola Serie A: 3 mercati x 1 regione = 3 crediti per giro, un giro al
# giorno = circa 90 crediti al mese sui 500 gratuiti. Largo margine.
# Se riattivi altre competizioni, ricontrolla il conto: 3 crediti a
# competizione per giro, quindi 5 competizioni con giro giornaliero fanno 450.
# Il badge in alto nell'app mostra sempre i crediti residui: controllalo.
INCLUDE_BTTS = True

# Bookmaker su cui scommetti davvero. Il valore di una giocata si calcola su
# QUESTE quote, non sulla migliore del mercato: una quota che non puoi giocare
# gonfia il vantaggio e ti fa sembrare buona una scommessa che non lo e'.
# Eurobet NON e' nel catalogo di The Odds API: gli unici bookmaker italiani
# disponibili sono questi due. Per aggiungerne o togliere, modifica la riga.
# Lista completa: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
# Lasciandola vuota si torna a usare la migliore quota del mercato.
BOOK_PREF = ("unibet_it", "codere_it")

# Blocco di sicurezza: sotto questa soglia di crediti residui si smette di
# chiamare l'API per il resto del giro. Serve a non restare a secco a meta'
# mese senza accorgersene, e a lasciare un margine per i giri manuali.
CREDIT_FLOOR = 25

# Solo le 6 leghe scelte (h2h + totals = 2 crediti a lega -> ~372/mese, sotto i 500)
SPORT_KEYS = {
    # Stagione di prova: solo Serie A. Riattivando una riga qui va riattivata
    # anche la competizione corrispondente in football_data_client.COMPETITIONS,
    # altrimenti le quote arrivano ma non ci sono squadre su cui applicarle.
    "SA":  "soccer_italy_serie_a",
    # "PL":  "soccer_epl",
    # "FL1": "soccer_france_ligue_one",
    # "PD":  "soccer_spain_la_liga",
    # "BL1": "soccer_germany_bundesliga",
    # "DED": "soccer_netherlands_eredivisie",
    # "CL":  "soccer_uefa_champs_league",
    # "EL":  "soccer_uefa_europa_league",
    # "ECL": "soccer_uefa_europa_conference_league",
}

# Competizioni che esistono SOLO grazie alle quote (niente Football-Data)
# Competizioni che esistono SOLO grazie alle quote (niente Football-Data).
# Vuoto nella stagione di prova: Europa League e Conference costavano 6 crediti
# a giro e restituivano pochissime partite usabili, perche' delle loro squadre
# conoscevamo le statistiche di troppo poche.
ODDS_ONLY = {
    # "EL":  {"name": "Europa League", "country": "Europe"},
    # "ECL": {"name": "Conference League", "country": "Europe"},
}


class OddsAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("ODDSKEY", "")
        self.credits_remaining = None
        self.credits_used = None
        self.halted = False          # True se il blocco di sicurezza e' scattato
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
                try:
                    if int(rem) < CREDIT_FLOOR:
                        self.halted = True
                        print(f"    [!] CREDITI QUASI ESAURITI: {rem} rimasti. "
                              f"Stop alle chiamate per non restare a secco.")
                except ValueError:
                    pass
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
        MKT = ("1", "X", "2", "over25", "under25", "gg", "ng")
        acc = {k: [] for k in MKT}       # tutti i bookmaker: media e quota migliore
        pref = {k: [] for k in MKT}      # solo i bookmaker su cui giochi
        libri_pref = []
        for bk in event.get("bookmakers", []):
            e_pref = bk.get("key") in BOOK_PREF
            if e_pref:
                libri_pref.append(bk.get("title") or bk.get("key"))
            for market in bk.get("markets", []):
                def metti(chiave, prezzo):
                    acc[chiave].append(prezzo)
                    if e_pref:
                        pref[chiave].append(prezzo)

                if market["key"] == "h2h":
                    for o in market["outcomes"]:
                        n, price = o["name"], o["price"]
                        if n == home: metti("1", price)
                        elif n == away: metti("2", price)
                        elif n.lower() in ("draw", "x"): metti("X", price)
                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        if o.get("point") == 2.5:
                            if o["name"].lower() == "over": metti("over25", o["price"])
                            elif o["name"].lower() == "under": metti("under25", o["price"])
                elif market["key"] == "btts":
                    for o in market["outcomes"]:
                        n = o["name"].lower()
                        if n == "yes": metti("gg", o["price"])
                        elif n == "no": metti("ng", o["price"])

        def avg(v): return round(sum(v) / len(v), 3) if v else None
        def best(v): return round(max(v), 3) if v else None

        rec = {"homeTeam": home, "awayTeam": away, "commenceTime": event.get("commence_time"),
               "n_books": len(event.get("bookmakers", [])),
               "1": avg(acc["1"]), "X": avg(acc["X"]), "2": avg(acc["2"]),
               "over25": avg(acc["over25"]), "under25": avg(acc["under25"]),
               "gg": avg(acc["gg"]), "ng": avg(acc["ng"]),
               "best": {"1": best(acc["1"]), "X": best(acc["X"]), "2": best(acc["2"]),
                        "over25": best(acc["over25"]), "under25": best(acc["under25"]),
                        "gg": best(acc["gg"]), "ng": best(acc["ng"])},
               # Quota giocabile: la migliore fra i bookmaker di BOOK_PREF.
               # Su questa si calcola il vantaggio, perche' e' quella che puoi
               # prendere davvero. Le medie di tutti i bookmaker restano e
               # servono alla calibrazione: il consenso di venti operatori e'
               # una stima di probabilita' molto migliore di quella di uno solo.
               "playable": {k: best(pref[k]) for k in MKT} if BOOK_PREF else {},
               "playableBooks": sorted(set(libri_pref))}
        return rec

    def fetch_all_odds(self, active_comps=None):
        """Se active_comps e' fornita, chiama l'API solo per quelle competizioni
        (risparmio crediti: le coppe giocano poche settimane)."""
        all_odds = {}
        for comp_id, sport_key in SPORT_KEYS.items():
            if self.halted:
                print(f"[→] Quote {comp_id}: saltate (crediti sotto la soglia di sicurezza)")
                all_odds[comp_id] = []
                continue
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
