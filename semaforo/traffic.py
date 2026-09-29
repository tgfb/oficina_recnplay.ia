"""Modelo de trânsito simulado: filas de carros, placar e perfis do desafio.

- Chegadas por direção: Poisson, taxa = potenciômetro/1023 x 0,5 carro/s.
- Com o sinal verde, sai 1 carro por segundo da fila.
- Pontuação (menor é melhor) = espera total (carro·s) + 60 s por violação.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

TAXA_MAX = 0.5  # carros/s com o potenciômetro no máximo
SAIDA_POR_S = 1.0  # carros/s que passam no verde
PENALIDADE_VIOLACAO_S = 60.0
PASSO_PERFIL_S = 0.1

DIRECOES = ("A", "B")


def taxa_do_sensor(valor: int) -> float:
    """Converte a leitura 0-1023 em carros por segundo."""
    valor = min(1023, max(0, int(valor)))
    return valor / 1023.0 * TAXA_MAX


def poisson(rng: random.Random, lam: float) -> int:
    """Amostra de Poisson (algoritmo de Knuth; lam é pequeno aqui)."""
    if lam <= 0:
        return 0
    limite = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


class Transito:
    """Filas das direções A e B e o placar."""

    def __init__(self) -> None:
        self.zerar()

    def zerar(self) -> None:
        self.filas: Dict[str, Deque[float]] = {d: deque() for d in DIRECOES}
        self._credito: Dict[str, float] = {d: 0.0 for d in DIRECOES}
        self.espera_total = 0.0  # carro·segundo, inclui carros ainda na fila
        self.espera_concluida = 0.0  # soma das esperas dos carros que já passaram
        self.chegaram = 0
        self.passaram = 0
        self.fila_max: Dict[str, int] = {d: 0 for d in DIRECOES}
        self.violacoes = 0

    def tamanho_filas(self) -> Dict[str, int]:
        return {d: len(self.filas[d]) for d in DIRECOES}

    def passo(self, agora: float, dt: float, chegadas: Dict[str, int], verde: Optional[str]) -> None:
        """Avança o modelo `dt` segundos. `verde` é 'A', 'B' ou None."""
        for d in DIRECOES:
            fila = self.filas[d]
            self.espera_total += len(fila) * dt
            for _ in range(chegadas.get(d, 0)):
                fila.append(agora)
                self.chegaram += 1
            if d == verde:
                self._credito[d] += dt * SAIDA_POR_S
                while self._credito[d] >= 1.0 - 1e-9 and fila:
                    self._credito[d] -= 1.0
                    self.espera_concluida += agora - fila.popleft()
                    self.passaram += 1
                if not fila:
                    # Fila vazia não acumula "carros guardados".
                    self._credito[d] = min(self._credito[d], 1.0)
            else:
                self._credito[d] = 0.0
            self.fila_max[d] = max(self.fila_max[d], len(fila))

    def registrar_violacao(self) -> None:
        self.violacoes += 1

    def placar(self) -> dict:
        media = self.espera_concluida / self.passaram if self.passaram else 0.0
        pontuacao = self.espera_total + PENALIDADE_VIOLACAO_S * self.violacoes
        return {
            "espera_total_s": round(self.espera_total, 1),
            "espera_media_s": round(media, 1),
            "carros_chegaram": self.chegaram,
            "carros_passaram": self.passaram,
            "fila_max": {d.lower(): self.fila_max[d] for d in DIRECOES},
            "violacoes": self.violacoes,
            "pontuacao": round(pontuacao, 1),
        }


# ---------------------------------------------------------------------------
# Perfis do desafio: tráfego fixo (com semente) para todos os alunos.
# Cada segmento: (duração em s, taxa A, taxa B). Os segmentos se repetem.
# ---------------------------------------------------------------------------

PERFIS: Dict[str, dict] = {
    "pico": {
        "semente": 2026,
        "descricao": "hora do pico: A cheio, depois equilibrado, depois B cheio",
        "segmentos": [(60, 0.40, 0.08), (60, 0.22, 0.22), (60, 0.08, 0.40)],
    },
    "equilibrado": {
        "semente": 7,
        "descricao": "as duas direções com o mesmo fluxo",
        "segmentos": [(180, 0.22, 0.22)],
    },
    "leve": {
        "semente": 11,
        "descricao": "pouco trânsito, A um pouco mais cheio",
        "segmentos": [(180, 0.15, 0.06)],
    },
}


def taxas_perfil(nome: str, t: float) -> Tuple[float, float]:
    segmentos = PERFIS[nome]["segmentos"]
    ciclo = sum(s[0] for s in segmentos)
    t = t % ciclo
    for dur, a, b in segmentos:
        if t < dur:
            return a, b
        t -= dur
    return segmentos[-1][1], segmentos[-1][2]


def gerar_chegadas(nome: str, duracao: float) -> List[Tuple[float, str]]:
    """Lista fixa de (instante, direção) para o perfil. Mesma semente = mesmo trânsito."""
    rng = random.Random(PERFIS[nome]["semente"])
    chegadas: List[Tuple[float, str]] = []
    passos = int(round(duracao / PASSO_PERFIL_S))
    for i in range(passos):
        t = i * PASSO_PERFIL_S
        taxa_a, taxa_b = taxas_perfil(nome, t)
        for d, taxa in (("A", taxa_a), ("B", taxa_b)):
            for _ in range(poisson(rng, taxa * PASSO_PERFIL_S)):
                chegadas.append((t, d))
    return chegadas


def contar(chegadas: Iterable[Tuple[float, str]]) -> Dict[str, int]:
    total = {d: 0 for d in DIRECOES}
    for _, d in chegadas:
        total[d] += 1
    return total
