"""
render.py — Presentazione dei risultati a schermo (CLI).

Stampa: probabilità 1X2, top 3 risultati esatti, Under/Over 2.5,
Goal/No Goal e un istogramma testuale della distribuzione dei gol.
"""

from __future__ import annotations

from src.models.monte_carlo import RisultatiSimulazione

LARGHEZZA_BARRA = 40  # caratteri massimi dell'istogramma


def _barra(prob: float, max_prob: float) -> str:
    """Barra proporzionale in caratteri pieni."""
    n = int(round((prob / max_prob) * LARGHEZZA_BARRA)) if max_prob > 0 else 0
    return "█" * n


def stampa_report(
    nome_casa: str,
    nome_fuori: str,
    competizione: str,
    data_match: str,
    lam_casa: float,
    lam_fuori: float,
    ris: RisultatiSimulazione,
) -> None:
    """Report completo del match simulato."""
    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  {nome_casa.upper()}  vs  {nome_fuori.upper()}")
    print(f"  {competizione} — {data_match}")
    print(f"  Simulazioni Monte Carlo: {ris.n_iterazioni:,}".replace(",", "."))
    print(sep)

    # --- Gol attesi (i λ finali dopo calibrazione e forma) ---
    print(f"\n  Gol attesi (xG modello):  {nome_casa} {lam_casa:.2f}  |  "
          f"{nome_fuori} {lam_fuori:.2f}")

    # --- Probabilità 1X2 ---
    print("\n  ESITO FINALE (1X2)")
    print(f"    1  ({nome_casa:<15}) : {ris.p_1:6.1%}")
    print(f"    X  ({'Pareggio':<15}) : {ris.p_x:6.1%}")
    print(f"    2  ({nome_fuori:<15}) : {ris.p_2:6.1%}")

    # --- Top 3 risultati esatti ---
    print("\n  TOP 3 RISULTATI ESATTI")
    for i, (score, p) in enumerate(ris.top_risultati_esatti(3), start=1):
        print(f"    {i}. {score:<5} : {p:6.1%}")

    # --- Under/Over e GG/NG ---
    print("\n  MERCATI GOL")
    print(f"    Over  2.5 : {ris.p_over25:6.1%}")
    print(f"    Under 2.5 : {ris.p_under25:6.1%}")
    print(f"    Goal (GG) : {ris.p_goal:6.1%}")
    print(f"    NoGoal(NG): {ris.p_nogoal:6.1%}")

    # --- Istogramma gol totali ---
    print("\n  DISTRIBUZIONE GOL TOTALI")
    dist = ris.distribuzione_gol_totali()
    max_p = max(dist.values())
    for gol, p in dist.items():
        etichetta = f"{gol}+" if gol == max(dist) else f"{gol} "
        print(f"    {etichetta} | {_barra(p, max_p):<{LARGHEZZA_BARRA}} {p:5.1%}")

    print(f"\n{sep}")
    print("  NOTA: probabilità descrittive, non consigli di scommessa.")
    print("  Il modello incorpora le quote di mercato: non può batterle.")
    print(sep + "\n")
