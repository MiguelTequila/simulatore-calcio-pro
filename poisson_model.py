"""
poisson_model.py — Cuore statistico del simulatore.

Passi:
  1. Stima dei λ (gol attesi) di casa e trasferta dalle statistiche
     storiche: forza offensiva x debolezza difensiva avversaria,
     relative alla media di lega.
  2. Calibrazione con le quote di mercato:
     - il totale gol atteso (λ_casa + λ_fuori) viene riconciliato con
       la probabilità implicita dell'Over 2.5;
     - la "supremazia" (λ_casa - λ_fuori) viene riconciliata con le
       probabilità implicite 1X2.
     La fusione usa PESO_QUOTE: il mercato è quasi sempre meglio
     calibrato del modello ingenuo, quindi pesa di più.
  3. Correzione per lo stato di forma (moltiplicatore limitato).
  4. Costruzione della matrice di probabilità dei risultati esatti.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.stats import poisson, skellam

from src import config
from src.data_fetcher import QuoteMatch, StatisticheSquadra


def lambdas_da_statistiche(
    casa: StatisticheSquadra,
    fuori: StatisticheSquadra,
    media_gol_casa_lega: float = config.MEDIA_GOL_CASA_LEGA,
    media_gol_fuori_lega: float = config.MEDIA_GOL_FUORI_LEGA,
) -> tuple[float, float]:
    """
    λ base dal modello classico attacco/difesa (Maher, 1982).

    forza_attacco = gol fatti squadra / media lega
    debolezza_difesa = gol subiti avversario / media lega
    λ = media_lega * forza_attacco * debolezza_difesa
    """
    att_casa = casa.gol_fatti_media / media_gol_casa_lega
    dif_fuori = fuori.gol_subiti_media / media_gol_casa_lega
    lam_casa = media_gol_casa_lega * att_casa * dif_fuori

    att_fuori = fuori.gol_fatti_media / media_gol_fuori_lega
    dif_casa = casa.gol_subiti_media / media_gol_fuori_lega
    lam_fuori = media_gol_fuori_lega * att_fuori * dif_casa

    # Limiti di sanità: λ fuori da [0.2, 4.5] è quasi sempre un errore di input
    return (
        float(np.clip(lam_casa, 0.2, 4.5)),
        float(np.clip(lam_fuori, 0.2, 4.5)),
    )


# ---------------------------------------------------------------------------
# CALIBRAZIONE CON LE QUOTE
# ---------------------------------------------------------------------------

def _totale_gol_da_over25(p_over: float) -> float:
    """
    Inverte la Poisson: trova il λ totale tale che
    P(gol_totali >= 3) = p_over. Risolto numericamente con Brent.
    """
    def f(lam_tot: float) -> float:
        return (1 - poisson.cdf(2, lam_tot)) - p_over
    return brentq(f, 0.3, 8.0)


def _supremazia_da_1x2(p1: float, p2: float, lam_tot: float) -> float:
    """
    Trova la differenza d = λ_casa - λ_fuori coerente con le probabilità
    1X2 di mercato, usando la distribuzione di Skellam (differenza di
    due Poisson). Minimizza lo scarto tra P(casa vince) - P(fuori vince)
    del modello e quello di mercato.
    """
    target = p1 - p2  # asimmetria di mercato

    def f(d: float) -> float:
        lam_c = (lam_tot + d) / 2
        lam_f = (lam_tot - d) / 2
        p_casa = 1 - skellam.cdf(0, lam_c, lam_f)   # diff >= 1
        p_fuori = skellam.cdf(-1, lam_c, lam_f)     # diff <= -1
        return (p_casa - p_fuori) - target

    # d limitato per mantenere entrambi i λ positivi
    lim = lam_tot - 0.1
    return brentq(f, -lim, lim)


def calibra_con_quote(
    lam_casa: float, lam_fuori: float, quote: QuoteMatch | None,
) -> tuple[float, float]:
    """
    Fonde i λ statistici con quelli impliciti nelle quote.
    Se le quote mancano, restituisce i λ statistici invariati.
    """
    if quote is None:
        return lam_casa, lam_fuori

    p1, _px, p2 = quote.probabilita_implicite_1x2()

    # Totale gol: dal mercato Over/Under se disponibile, altrimenti
    # manteniamo il totale del modello statistico
    p_over = quote.probabilita_implicita_over25()
    if p_over is not None:
        tot_mercato = _totale_gol_da_over25(p_over)
    else:
        tot_mercato = lam_casa + lam_fuori

    # Supremazia implicita nel mercato 1X2
    supr_mercato = _supremazia_da_1x2(p1, p2, tot_mercato)
    lam_casa_mkt = (tot_mercato + supr_mercato) / 2
    lam_fuori_mkt = (tot_mercato - supr_mercato) / 2

    # Fusione ponderata modello/mercato
    w = config.PESO_QUOTE
    lam_c = (1 - w) * lam_casa + w * lam_casa_mkt
    lam_f = (1 - w) * lam_fuori + w * lam_fuori_mkt
    return float(max(lam_c, 0.1)), float(max(lam_f, 0.1))


def applica_forma(
    lam_casa: float, lam_fuori: float,
    casa: StatisticheSquadra, fuori: StatisticheSquadra,
) -> tuple[float, float]:
    """Applica il moltiplicatore di forma (limitato da IMPATTO_FORMA_MAX)."""
    return lam_casa * casa.punteggio_forma(), lam_fuori * fuori.punteggio_forma()


# ---------------------------------------------------------------------------
# MATRICE RISULTATI ESATTI
# ---------------------------------------------------------------------------

def matrice_risultati(
    lam_casa: float, lam_fuori: float, max_gol: int = config.MAX_GOL_MATRICE,
) -> np.ndarray:
    """
    Matrice (max_gol+1) x (max_gol+1): cella [i, j] = P(casa=i, fuori=j)
    sotto ipotesi di indipendenza delle due Poisson.
    Limite noto: il modello base sottostima leggermente i pareggi
    (correlazione tra i gol); il Monte Carlo con λ campionati mitiga.
    """
    gol = np.arange(max_gol + 1)
    p_casa = poisson.pmf(gol, lam_casa)
    p_fuori = poisson.pmf(gol, lam_fuori)
    return np.outer(p_casa, p_fuori)
