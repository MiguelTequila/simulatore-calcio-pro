"""
config.py — Configurazione centrale del Simulatore Predittivo.

Le chiavi API vengono lette da variabili d'ambiente per non finire mai
su GitHub. Impostale così (Linux/Mac):
    export API_FOOTBALL_KEY="la_tua_chiave"
    export ODDS_API_KEY="la_tua_chiave"
Su Windows (PowerShell):
    $env:API_FOOTBALL_KEY="la_tua_chiave"
"""

import os

# ---------------------------------------------------------------------------
# CHIAVI API (mai hardcodate nel codice!)
# ---------------------------------------------------------------------------
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# Endpoint base
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# ---------------------------------------------------------------------------
# MAPPATURA COMPETIZIONI -> ID API-Football
# (aggiungi qui altre leghe se ti servono)
# ---------------------------------------------------------------------------
LEAGUE_IDS = {
    "serie a": 135,
    "premier league": 39,
    "laliga": 140,
    "bundesliga": 78,
    "ligue 1": 61,
    "champions league": 2,
}

# ---------------------------------------------------------------------------
# PARAMETRI DEL MODELLO
# ---------------------------------------------------------------------------
N_SIMULAZIONI = 10_000     # iterazioni Monte Carlo
MAX_GOL_MATRICE = 5        # matrice risultati esatti da 0-0 a 5-5

# Peso dato alle quote di mercato vs. modello statistico puro (0..1).
# 0.7 = il mercato pesa il 70%. I bookmaker sono più informati del
# nostro modello sui gol: partire umili è la scelta corretta.
PESO_QUOTE = 0.70

# Fattore di forma: quanto lo stato di forma (ultime 5) può spostare λ.
# 0.10 = al massimo ±10%. Valori più alti rendono il modello isterico.
IMPATTO_FORMA_MAX = 0.10

# Parametro di dispersione per il campionamento Gamma nel Monte Carlo.
# Più basso = più incertezza sui λ = code più grasse (più realismo).
# k=15 replica approssimativamente l'overdispersione osservata nei
# campionati europei top-5.
GAMMA_DISPERSIONE_K = 15.0

# Media gol di lega usata come fallback se non disponibile via API
MEDIA_GOL_CASA_LEGA = 1.50
MEDIA_GOL_FUORI_LEGA = 1.20
