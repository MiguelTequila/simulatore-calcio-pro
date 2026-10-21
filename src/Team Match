"""Riconoscimento delle squadre fra fonti diverse.

Football-Data scrive "Sport Lisboa e Benfica", The Odds API scrive "Benfica".
Per le coppe europee serve agganciare le due cose: le statistiche arrivano dal
campionato nazionale, il calendario e le quote dall'API delle quote.
"""
import re, unicodedata, difflib

# Parole che non distinguono una squadra dall'altra
NOISE = {
    # Solo sigle societarie e parole legali: tutto cio' che NON distingue una
    # squadra da un'altra della stessa citta'. Attenzione: "real", "atletico",
    # "sporting", "club" fanno parte del nome e NON vanno qui, altrimenti
    # "Real Madrid" e "Club Atletico de Madrid" diventano lo stesso club.
    "fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "us", "ud", "cd", "rc", "rcd",
    "sv", "tsv", "vfb", "vfl", "fsv", "bsc", "kv", "rsc", "ogc", "bk", "if", "ff",
    "fk", "sk", "nk", "hk", "ac", "cp", "sad", "ks", "mk",
    "calcio", "futbol", "football", "fussball", "futebol", "voetbal",
    "de", "do", "da", "di", "del", "della", "e", "y", "i", "the", "and", "den",
    "1", "04", "05", "07", "09", "1846", "1899", "1900", "1902", "1907", "1909", "1913",
}

# Casi che nessuna regola automatica risolve
ALIASES = {
    "internazionale": "inter", "internazionalemilano": "inter", "intermilan": "inter",
    "sportlisboabenfica": "benfica", "lisboabenfica": "benfica", "slbenfica": "benfica",
    "sportingclubeportugal": "sportinglisbon", "sportinglisbon": "sportinglisbon",
    "sportingcpportugal": "sportinglisbon", "portugal": "sportinglisbon",
    "sportingcp": "sportinglisbon", "sportingclubebraga": "braga", "scbraga": "braga",
    "borussiamonchengladbach": "gladbach", "borussiamgladbach": "gladbach",
    "bayernmunchen": "bayernmunich", "bayern": "bayernmunich",
    "parissaintgermain": "psg", "paris": "psg",
    "manchesterutd": "manchesterunited", "manutd": "manchesterunited",
    "manunited": "manchesterunited", "manchesterunited": "manchesterunited",
    "manchestercity": "mancity", "mancity": "mancity",
    "tottenhamhotspur": "tottenham", "spurs": "tottenham",
    "wolverhamptonwanderers": "wolves", "wolverhampton": "wolves",
    "brightonhovealbion": "brighton", "westhamunited": "westham",
    "newcastleunited": "newcastle", "leedsunited": "leeds",
    "nottinghamforest": "forest", "notunghamforest": "forest",
    "atleticomadrid": "atleticomadrid", "atleticodemadrid": "atleticomadrid",
    "realsociedaddefutbol": "realsociedad",
    "bayerleverkusen": "leverkusen", "bayer04leverkusen": "leverkusen",
    "eintrachtfrankfurt": "frankfurt", "rbleipzig": "leipzig", "rasenballsportleipzig": "leipzig",
    "olympiquemarseille": "marseille", "olympiquedemarseille": "marseille",
    "olympiquelyonnais": "lyon", "olympiquelyon": "lyon",
    "shakhtardonetsk": "shakhtar", "fkshakhtardonetsk": "shakhtar",
    "bodoglimt": "bodo", "fkbodoglimt": "bodo",
    "clubbruggekv": "clubbrugge", "clubbrugge": "clubbrugge",
    "galatasarays": "galatasaray", "fenerbahces": "fenerbahce",
    "ajaxamsterdam": "ajax", "afcajax": "ajax",
    "feyenoordrotterdam": "feyenoord",
    "psveindhoven": "psv", "psv": "psv",
    "azalkmaar": "az", "az": "az",
    "realmadridcf": "realmadrid", "realmadrid": "realmadrid",
    "clubatleticomadrid": "atleticomadrid", "clubatleticodemadrid": "atleticomadrid",
}


def normalize(name):
    """Riduce un nome squadra alla sua forma confrontabile."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("ø", "o").replace("ß", "ss").replace("æ", "ae")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [w for w in s.split() if w]
    # Gli alias si provano PRIMA sulla forma completa: "sportlisboabenfica"
    # sparirebbe dopo la rimozione di "sport" e non verrebbe piu' riconosciuto.
    full = "".join(words)
    if full in ALIASES:
        return ALIASES[full]
    parts = [w for w in words if w not in NOISE]
    if not parts:                       # era fatto solo di rumore: tieni tutto
        parts = words
    key = "".join(parts)
    return ALIASES.get(key, key)


def build_index(teams_by_league):
    """Da {lega: {id: dati_squadra}} costruisce {chiave_normalizzata: dati}.
    Se una squadra compare in piu' leghe vince quella con piu' partite giocate."""
    idx = {}
    for league, teams in (teams_by_league or {}).items():
        for t in (teams or {}).values():
            k = normalize(t.get("name"))
            if not k:
                continue
            prev = idx.get(k)
            if prev is None or (t.get("played") or 0) > (prev.get("played") or 0):
                e = dict(t)
                e["_league"] = league
                idx[k] = e
    return idx


def find_team(name, index, cutoff=0.86):
    """Cerca una squadra nell'indice: prima esatta, poi somiglianza alta."""
    k = normalize(name)
    if not k:
        return None
    if k in index:
        return index[k]
    # contenimento: "atalanta" dentro "atalantabergamascacalcio"
    best = None
    for key in index:
        if len(k) < 4 or len(key) < 4:
            continue
        if k in key or key in k:
            short, long_ = (k, key) if len(k) <= len(key) else (key, k)
            if len(short) / len(long_) >= 0.45:   # evita agganci su frammenti
                if best is None or len(key) < len(best):
                    best = key
    if best:
        return index[best]
    m = difflib.get_close_matches(k, list(index.keys()), n=1, cutoff=cutoff)
    return index[m[0]] if m else None
