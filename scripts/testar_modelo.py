"""Teste rápido: o CENTOPEIA chama ferramentas no opencode?

Pede ao agente para rodar `tl status` e confere no log do daemon se a chamada chegou.

Como rodar (venv ativo, `tl daemon --sim` ou `tl daemon` em outro terminal):
    python scripts/testar_modelo.py
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from semaforo.client import Client, DaemonOffline  # noqa: E402

PEDIDO = (
    "Use a ferramenta bash para executar exatamente o comando `tl status`. "
    "Depois responda em uma frase: qual é a fase atual do semáforo?"
)
TIMEOUT_S = 180


def main() -> int:
    print("1) Variáveis de ambiente do CENTOPEIA")
    faltando = [v for v in ("CLUSTER_BASE_URL", "CLUSTER_API_KEY", "CLUSTER_MODEL") if not os.environ.get(v)]
    if faltando:
        print(f"   AVISO: faltam {', '.join(faltando)}. O opencode.json usa essas variáveis.")
    else:
        print(f"   ok: modelo {os.environ['CLUSTER_MODEL']} em {os.environ['CLUSTER_BASE_URL']}")

    print("2) opencode no PATH")
    opencode = shutil.which("opencode")
    if not opencode:
        print("   FALHA: `opencode` não encontrado. Instale o opencode (veja docs/guia-aluno.md).")
        return 1
    print(f"   ok: {opencode}")

    print("3) Daemon rodando")
    cli = Client()
    try:
        estado = cli.get("/status")
        ultimo = cli.get("/chamadas", desde=10**12)["ultimo"]
    except DaemonOffline:
        print("   FALHA: o daemon não responde. Rode `tl daemon --sim` em outro terminal.")
        return 1
    print(f"   ok: fase atual {estado['fase']} ({estado['conexao']['descricao']})")

    print(f"4) Pedindo ao agente para rodar `tl status` (até {TIMEOUT_S} s)...")
    inicio = time.monotonic()
    try:
        r = subprocess.run([opencode, "run", PEDIDO], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
        saida = (r.stdout + r.stderr).strip()
        codigo = r.returncode
    except subprocess.TimeoutExpired:
        saida, codigo = f"(tempo esgotado depois de {TIMEOUT_S} s)", -1
    duracao = time.monotonic() - inicio
    print("   --- resposta do opencode ---")
    for linha in saida.splitlines()[-30:]:
        print(f"   | {linha}")
    print(f"   --- fim ({duracao:.1f} s, código {codigo}) ---")

    print("5) O daemon recebeu a chamada?")
    chamadas = cli.get("/chamadas", desde=ultimo)["chamadas"]
    status = [c for c in chamadas if c["comando"].startswith("status")]
    if status:
        print(f"   PASSOU: o agente chamou `tl {status[0]['comando']}` às {status[0]['hora']}.")
        print(f"   O modelo usa ferramentas no opencode. Tempo da rodada: {duracao:.1f} s.")
        if estado["fase"] not in saida:
            print("   AVISO: a resposta não cita a fase atual. Leia a resposta acima.")
        return 0
    print("   FALHOU: nenhuma chamada `tl status` chegou ao daemon.")
    if chamadas:
        print(f"   Chamadas que chegaram: {', '.join('tl ' + c['comando'] for c in chamadas)}")
    print("   Causas prováveis:")
    print("   - o modelo não suporta tool calling (ou o servidor não ativa tool calling);")
    print("   - baseURL/modelo/chave errados no ambiente (veja o erro na resposta acima);")
    print("   - `tl` não está no PATH do opencode (ative o venv antes);")
    print("   - a permissão do bash no opencode.json bloqueou o comando.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
