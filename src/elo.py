"""Elo dinamico e PERSISTENTE tra un aggiornamento e l'altro.

A differenza della versione precedente, l'Elo NON riparte da 1500 a ogni giro:
carica lo stato salvato, applica solo le partite nuove (per id, mai due volte)
e regredisce verso la media dopo lunghe pause (cambio stagione).
"""
import json, os

K = 32
HOME_ADV = 65
INITIAL = 1500
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "elo_state.json")
GAP_REGRESS_DAYS = 45      # oltre questa pausa -> regressione verso la media
GAP_REGRESS_FACTOR = 0.5   # quanto si torna verso 1500 (0 = niente, 1 = reset)
MAX_PROCESSED = 12000      # tetto agli id memorizzati


def expected_score(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("ratings", {})
        s.setdefault("processed", [])
        s.setdefault("last_date", {})
        return s
    except Exception:
        return {"ratings": {}, "processed": [], "last_date": {}}


def save_state(state):
    state["processed"] = state["processed"][-MAX_PROCESSED:]
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _regress(elo, factor=GAP_REGRESS_FACTOR):
    return INITIAL + (elo - INITIAL) * (1 - factor)


def update_ratings_incremental(all_matches, state, k=K):
    """Applica solo le partite non ancora conteggiate. Ritorna il dict piatto
    {nome_squadra: {'elo':..,'games':..}} compatibile con update_data."""
    ratings = state["ratings"]
    processed = set(state["processed"])
    last_date = state["last_date"]

    def team(name):
        return ratings.setdefault(name, {"elo": INITIAL, "games": 0})

    new = []
    for m in all_matches:
        mid = m.get("id")
        if mid is None or mid in processed:
            continue
        if m.get("homeGoals") is None or m.get("awayGoals") is None:
            continue
        new.append(m)
    new.sort(key=lambda m: m.get("date", ""))

    for m in new:
        home, away = m["homeTeam"], m["awayTeam"]
        hg, ag = m["homeGoals"], m["awayGoals"]
        date = m.get("date", "")
        # regressione verso la media se la squadra e' ferma da tanto (nuova stagione)
        for name in (home, away):
            ld = last_date.get(name)
            if ld and date and _days_between(ld, date) > GAP_REGRESS_DAYS:
                team(name)["elo"] = _regress(team(name)["elo"])

        rh, ra = team(home)["elo"], team(away)["elo"]
        eh = expected_score(rh + HOME_ADV, ra)
        ea = 1 - eh
        if hg > ag: ah, aa = 1, 0
        elif hg == ag: ah, aa = 0.5, 0.5
        else: ah, aa = 0, 1
        # margine di vittoria (goal difference) -> aggiornamento piu' reattivo
        gd = abs(hg - ag)
        mult = 1.0 if gd <= 1 else (1.5 if gd == 2 else (1.75 + (gd - 3) / 8))
        team(home)["elo"] = rh + k * mult * (ah - eh)
        team(away)["elo"] = ra + k * mult * (aa - ea)
        team(home)["games"] += 1
        team(away)["games"] += 1
        last_date[home] = date
        last_date[away] = date
        processed.add(m["id"])

    state["ratings"] = ratings
    state["processed"] = list(processed)
    state["last_date"] = last_date
    return {name: dict(v) for name, v in ratings.items()}, state, len(new)


def _days_between(d1, d2):
    from datetime import date
    try:
        y1, m1, day1 = map(int, d1[:10].split("-"))
        y2, m2, day2 = map(int, d2[:10].split("-"))
        return abs((date(y2, m2, day2) - date(y1, m1, day1)).days)
    except Exception:
        return 0


# Retrocompatibilita': versione "da zero" (non piu' usata dalla pipeline)
def compute_elo_ratings(all_matches, initial_rating=INITIAL):
    st = {"ratings": {}, "processed": [], "last_date": {}}
    ratings, _, _ = update_ratings_incremental(all_matches, st)
    return ratings


if __name__ == "__main__":
    st = load_state()
    print("Squadre in stato:", len(st["ratings"]), "| partite gia' conteggiate:", len(st["processed"]))
