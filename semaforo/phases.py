"""Máquina de fases do cruzamento e regras de segurança.

Ciclo legal:
    A-verde -> A-amarelo -> vermelho-total -> B-verde -> B-amarelo -> vermelho-total -> A-verde

O LED físico mostra a direção A. A direção B é virtual (derivada da fase).
"""

from __future__ import annotations

from typing import Dict, List, Optional

A_VERDE = "A-verde"
A_AMARELO = "A-amarelo"
VERMELHO_TOTAL = "vermelho-total"
B_VERDE = "B-verde"
B_AMARELO = "B-amarelo"

FASES = (A_VERDE, A_AMARELO, VERMELHO_TOTAL, B_VERDE, B_AMARELO)

VERDE_MIN_S = 5.0
AMARELO_S = 3.0
VERMELHO_TOTAL_S = 1.0

TEMPO_MINIMO_S: Dict[str, float] = {
    A_VERDE: VERDE_MIN_S,
    B_VERDE: VERDE_MIN_S,
    A_AMARELO: AMARELO_S,
    B_AMARELO: AMARELO_S,
    VERMELHO_TOTAL: VERMELHO_TOTAL_S,
}

# Cor de cada direção em cada fase.
_CORES = {
    A_VERDE: ("verde", "vermelho"),
    A_AMARELO: ("amarelo", "vermelho"),
    VERMELHO_TOTAL: ("vermelho", "vermelho"),
    B_VERDE: ("vermelho", "verde"),
    B_AMARELO: ("vermelho", "amarelo"),
}

_LED = {"verde": "G", "amarelo": "Y", "vermelho": "R"}


def normalizar_fase(nome: str) -> Optional[str]:
    """Aceita variações como 'a-verde', 'A_VERDE' ou 'vermelho'."""
    chave = nome.strip().lower().replace("_", "-").replace(" ", "-")
    for fase in FASES:
        if fase.lower() == chave:
            return fase
    if chave in ("vermelho", "vermelho-todos", "todos-vermelho"):
        return VERMELHO_TOTAL
    return None


def cor(fase: str, direcao: str) -> str:
    """Cor do semáforo da direção 'A' ou 'B' na fase dada."""
    a, b = _CORES[fase]
    return a if direcao.upper() == "A" else b


def led_fisico(fase: str) -> str:
    """Comando de LED (R/Y/G) para o semáforo físico (direção A)."""
    return _LED[cor(fase, "A")]


def direcao_verde(fase: str) -> Optional[str]:
    if fase == A_VERDE:
        return "A"
    if fase == B_VERDE:
        return "B"
    return None


class Cruzamento:
    """Estado das fases. O tempo vem de fora (argumento `agora`)."""

    def __init__(self, agora: float, fase: str = VERMELHO_TOTAL, proximo_verde: str = "A"):
        self.fase = fase
        self.desde = agora
        # Qual direção fica verde depois do próximo vermelho-total.
        self.proximo_verde = proximo_verde
        if fase in (A_VERDE, A_AMARELO):
            self.proximo_verde = "B"
        elif fase in (B_VERDE, B_AMARELO):
            self.proximo_verde = "A"

    def decorrido(self, agora: float) -> float:
        return max(0.0, agora - self.desde)

    def proxima_legal(self) -> str:
        if self.fase == A_VERDE:
            return A_AMARELO
        if self.fase == B_VERDE:
            return B_AMARELO
        if self.fase in (A_AMARELO, B_AMARELO):
            return VERMELHO_TOTAL
        return A_VERDE if self.proximo_verde == "A" else B_VERDE

    def falta_para_mudar(self, agora: float) -> float:
        """Segundos até a fase atual cumprir o tempo mínimo."""
        return max(0.0, TEMPO_MINIMO_S[self.fase] - self.decorrido(agora))

    def verificar(self, destino: str, agora: float) -> List[str]:
        """Lista de violações (mensagens em pt-BR) se mudar para `destino` agora."""
        violacoes = []
        legal = self.proxima_legal()
        if destino != legal:
            violacoes.append(
                f"Transição proibida: {self.fase} -> {destino}. "
                f"A próxima fase legal é {legal}."
            )
        falta = self.falta_para_mudar(agora)
        if falta > 0:
            minimo = TEMPO_MINIMO_S[self.fase]
            violacoes.append(
                f"A fase {self.fase} precisa durar pelo menos {minimo:g} s "
                f"(durou {self.decorrido(agora):.1f} s). Espere mais {falta:.1f} s."
            )
        return violacoes

    def aplicar(self, destino: str, agora: float) -> None:
        if destino in (A_VERDE, A_AMARELO):
            self.proximo_verde = "B"
        elif destino in (B_VERDE, B_AMARELO):
            self.proximo_verde = "A"
        self.fase = destino
        self.desde = agora


def duracao_politica(fase: str, verde_a: float, verde_b: float) -> float:
    """Duração de cada fase no modo política."""
    if fase == A_VERDE:
        return verde_a
    if fase == B_VERDE:
        return verde_b
    if fase in (A_AMARELO, B_AMARELO):
        return AMARELO_S
    return VERMELHO_TOTAL_S


def passo_politica(cruz: Cruzamento, agora: float, verde_a: float, verde_b: float) -> Optional[str]:
    """Próxima fase se a fase atual já durou o tempo da política; senão None."""
    if cruz.decorrido(agora) >= duracao_politica(cruz.fase, verde_a, verde_b):
        return cruz.proxima_legal()
    return None
