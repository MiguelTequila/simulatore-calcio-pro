"""
monte_carlo.py — Simulazione Monte Carlo con incertezza sui parametri.

PERCHÉ NON un Monte Carlo "ingenuo": campionare 10.000 volte da una
Poisson con λ fisso restituisce (a meno del rumore) la stessa identica
matrice di Poisson analitica. Sarebbe calcolo sprecato.

QUI invece, a ogni iterazione, i λ stessi vengono campionati da una
distribuzione Gamma centrata sul valore stimato:

    λ_i ~ Gamma(shape = λ·k, rate = k)   =>  E[λ_i] = λ, Var cresce con 1/k

La miscela Gamma-Poisson è una Binomiale Negativa: introduce
sovradispersione, cioè code più grasse. È il modo statisticamente
corretto di dire "non siamo certi al 100% dei gol attesi" — e rende i
risultati estremi (0-0, 4-1...) più probabili di quanto dica Poisson
puro, coerentemente con i dati reali del calcio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src import config


@dataclass
class RisultatiSimulazione:
    """Contenitore dei risultati aggregati delle N simulazioni."""
    gol_casa: np.ndarray        # array (N,) gol casa per iterazione
    gol_fuori: np.ndarray       # array (N,) gol fuori per iterazione
    n_iterazioni: int

    # --- Probabilità 1X2 ---
    @property
    def p_1(self) -> float:
        return float(np.mean(self.gol_casa > self.gol_fuori))

    @property
    def p_x(self) -> float:
        return float(np.mean(self.gol_casa == self.gol_fuori))

    @property
    def p_2(self) -> float:
        return float(np.mean(self.gol_casa < self.gol_fuori))

    # --- Under/Over 2.5 ---
    @property
    def p_over25(self) -> float:
        return float(np.mean((self.gol_casa + self.gol_fuori) >= 3))

    @property
    def p_under25(self) -> float:
        return 1.0 - self.p_over25

    # --- Goal / No Goal ---
    @property
    def p_goal(self) -> float:
        """Entrambe le squadre segnano (GG)."""
        return float(np.mean((self.gol_casa >= 1) & (self.gol_fuori >= 1)))

    @property
    def p_nogoal(self) -> float:
        return 1.0 - self.p_goal

    def top_risultati_esatti(self, n: int = 3) -> list[tuple[str, float]]:
        """
        Top-N risultati esatti più frequenti nelle simulazioni.
        Restituisce liste tipo [("1-1", 0.124), ("1-0", 0.101), ...].
        """
        # Codifica compatta: risultato -> intero (casa*100 + fuori)
        codici = self.gol_casa * 100 + self.gol_fuori
        valori, conteggi = np.unique(codici, return_counts=True)
        ordine = np.argsort(conteggi)[::-1][:n]
        out = []
        for idx in ordine:
            c, f = divmod(int(valori[idx]), 100)
            out.append((f"{c}-{f}", conteggi[idx] / self.n_iterazioni))
        return out

    def distribuzione_gol_totali(self, max_gol: int = 7) -> dict[int, float]:
        """Distribuzione dei gol totali (per il grafico testuale)."""
        totali = self.gol_casa + self.gol_fuori
        return {
            g: float(np.mean(totali == g) if g < max_gol
                     else np.mean(totali >= max_gol))
            for g in range(max_gol + 1)
        }


def esegui_monte_carlo(
    lam_casa: float,
    lam_fuori: float,
    n_iter: int = config.N_SIMULAZIONI,
    k_dispersione: float = config.GAMMA_DISPERSIONE_K,
    seed: int | None = None,
) -> RisultatiSimulazione:
    """
    Esegue la simulazione vettorizzata (nessun ciclo Python esplicito:
    10.000 iterazioni in pochi millisecondi grazie a numpy).

    Per ogni iterazione i:
      1. λ_casa_i ~ Gamma(λ_casa·k, k)    (incertezza sul parametro)
      2. λ_fuori_i ~ Gamma(λ_fuori·k, k)
      3. gol_casa_i ~ Poisson(λ_casa_i)
      4. gol_fuori_i ~ Poisson(λ_fuori_i)
    """
    rng = np.random.default_rng(seed)

    # Passo 1-2: campionamento dei parametri (Gamma: shape/scale in numpy)
    lam_c_i = rng.gamma(shape=lam_casa * k_dispersione,
                        scale=1.0 / k_dispersione, size=n_iter)
    lam_f_i = rng.gamma(shape=lam_fuori * k_dispersione,
                        scale=1.0 / k_dispersione, size=n_iter)

    # Passo 3-4: campionamento dei gol condizionati ai parametri
    gol_casa = rng.poisson(lam_c_i)
    gol_fuori = rng.poisson(lam_f_i)

    return RisultatiSimulazione(gol_casa, gol_fuori, n_iter)
