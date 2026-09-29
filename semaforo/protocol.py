"""Protocolo serial v1 entre o PC e o Arduino.

Linhas de texto terminadas em '\\n', 115200 baud.

    PC -> Arduino        Resposta             Significado
    (no boot)            READY semaforo v1    placa pronta
    PING                 PONG                 heartbeat (1 por segundo)
    L R | L Y | L G | L O  OK L R             acende um LED (O = todos apagados)
    B                    OK B                 amarelo piscante
    S?                   S <a> <b>            potenciômetros 0-1023 (A0, A1)
    outro                ERR <msg>            comando desconhecido
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

BAUD = 115200
VERSAO = "v1"

LEDS = ("R", "Y", "G", "O")


class ProtocolError(ValueError):
    """Linha recebida que não segue o protocolo."""


def cmd_ping() -> str:
    return "PING"


def cmd_led(led: str) -> str:
    if led not in LEDS:
        raise ValueError(f"LED inválido: {led!r} (use R, Y, G ou O)")
    return f"L {led}"


def cmd_piscar() -> str:
    return "B"


def cmd_sensores() -> str:
    return "S?"


@dataclass
class Resposta:
    tipo: str  # READY, PONG, OK, S, ERR
    args: List[str] = field(default_factory=list)
    linha: str = ""

    @property
    def ok(self) -> bool:
        return self.tipo != "ERR"


def parse(linha: str) -> Resposta:
    """Interpreta uma linha enviada pelo Arduino."""
    texto = linha.strip()
    if not texto:
        raise ProtocolError("linha vazia")
    partes = texto.split()
    tipo, args = partes[0], partes[1:]
    if tipo == "READY":
        return Resposta("READY", args, texto)
    if tipo == "PONG" and not args:
        return Resposta("PONG", [], texto)
    if tipo == "OK" and args:
        return Resposta("OK", args, texto)
    if tipo == "S" and len(args) == 2:
        try:
            a, b = int(args[0]), int(args[1])
        except ValueError:
            raise ProtocolError(f"valores de sensor inválidos: {texto!r}")
        if not (0 <= a <= 1023 and 0 <= b <= 1023):
            raise ProtocolError(f"sensor fora da faixa 0-1023: {texto!r}")
        return Resposta("S", args, texto)
    if tipo == "ERR":
        return Resposta("ERR", args, texto)
    raise ProtocolError(f"resposta desconhecida: {texto!r}")


def parse_sensores(resp: Resposta) -> tuple:
    if resp.tipo != "S":
        raise ProtocolError(f"esperava 'S <a> <b>', recebi {resp.linha!r}")
    return int(resp.args[0]), int(resp.args[1])
