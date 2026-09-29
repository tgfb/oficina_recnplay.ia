"""Laço autônomo (etapa 3): acorda o agente do opencode de tempos em tempos.

O LLM demora segundos para responder, então ele NÃO troca cada fase aqui.
Ele só ajusta os tempos de verde (modo política) e o daemon roda o ciclo.

Como rodar (com o venv ativo e o `tl daemon` rodando em outro terminal):
    python agente_loop.py

Complete os TODOs.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

# TODO 1: escolha o intervalo entre as rodadas do agente.
# Dica: meça quanto tempo uma rodada do `opencode run` demora com o CENTOPEIA.
INTERVALO_S = 60

# TODO 2: escreva o pedido que o agente recebe em cada rodada.
# O que ele deve olhar? O que ele deve decidir? Como deve ser a resposta?
PEDIDO = """
TODO: escreva aqui o que o agente deve fazer em cada rodada.
"""

TIMEOUT_OPENCODE_S = 180

# O opencode precisa rodar nesta pasta para ler o opencode.json e o AGENTS.md.
PASTA = Path(__file__).resolve().parent


def rodar(cmd, timeout):
    """Roda um comando e devolve (código de saída, texto)."""
    try:
        r = subprocess.run(cmd, cwd=PASTA, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"(tempo esgotado depois de {timeout} s)"


def main():
    opencode = shutil.which("opencode")
    tl = shutil.which("tl")
    if not opencode or not tl:
        print("ERRO: preciso do `opencode` e do `tl` no PATH. O venv está ativo?")
        return 1

    # Na etapa 3 quem roda o ciclo é o daemon.
    print(rodar([tl, "modo", "politica"], 10)[1])

    rodada = 0
    while True:
        rodada += 1
        inicio = time.monotonic()

        # TODO 3 (opcional): coloque o estado atual no pedido, assim o agente
        # economiza uma chamada de ferramenta. Ex.: rodar([tl, "status"], 10)
        pedido = PEDIDO

        print(f"\n=== rodada {rodada} ===")
        codigo, resposta = rodar([opencode, "run", pedido], TIMEOUT_OPENCODE_S)
        print(resposta)
        duracao = time.monotonic() - inicio
        print(f"(agente levou {duracao:.1f} s, código {codigo})")

        # TODO 4: o que fazer se o agente falhar (código diferente de 0)?

        time.sleep(max(0.0, INTERVALO_S - duracao))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nlaço parado.")
