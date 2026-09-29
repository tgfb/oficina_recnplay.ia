"""`tl watch`: painel ao vivo no terminal (rich)."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .client import ApiError, Client, DaemonOffline

CORES = {"vermelho": "bold red", "amarelo": "bold yellow", "verde": "bold green"}
LAMPADA = "●"
APAGADA = "○"
MAX_CARROS = 30


def _semaforo(titulo: str, cor: str, piscando: bool = False) -> Panel:
    linhas = []
    for nome in ("vermelho", "amarelo", "verde"):
        acesa = nome == cor
        if piscando:
            acesa = nome == "amarelo" and int(time.monotonic() * 2) % 2 == 0
        estilo = CORES[nome] if acesa else "grey30"
        linhas.append(Text(f"  {LAMPADA if acesa else APAGADA}  ", style=estilo, justify="center"))
    rotulo = "amarelo piscante" if piscando else cor
    linhas.append(Text(rotulo, style=CORES.get(cor, "yellow"), justify="center"))
    return Panel(Group(*linhas), title=titulo, width=24)


def _barra(valor: float, maximo: float, largura: int = 20, estilo: str = "cyan") -> Text:
    cheio = int(round(largura * min(1.0, valor / maximo))) if maximo else 0
    return Text("█" * cheio + "·" * (largura - cheio), style=estilo)


def _fila(n: int) -> Text:
    mostra = min(n, MAX_CARROS)
    t = Text("■ " * mostra, style="magenta")
    if n > MAX_CARROS:
        t.append(f"+{n - MAX_CARROS}", style="bold magenta")
    if n == 0:
        t.append("(vazia)", style="grey50")
    return t


def montar_painel(e: dict, chamadas: deque, max_comandos: int = 8) -> Group:
    piscando = e.get("led_simulado") == "B" or not e["conexao"]["conectado"]
    luzes = Table.grid(padding=(0, 2))
    luzes.add_row(
        _semaforo("A (LED físico)", e["semaforo_a"], piscando=piscando),
        _semaforo("B (virtual)", e["semaforo_b"]),
    )

    info = Table.grid(padding=(0, 1))
    info.add_column(style="bold")
    info.add_column()
    seg = Text("LIGADA", style="bold green") if e["seguranca"] else Text("DESLIGADA", style="bold red reverse")
    info.add_row("Modo", Text(e["modo"], style="bold cyan"))
    info.add_row("Segurança", seg)
    fase = f"{e['fase']}  ({e['fase_decorrido_s']:.1f} s)"
    info.add_row("Fase", fase)
    if e["modo"] == "politica":
        p = e["politica"]
        info.add_row("Política", f"verde A {p['verde_a']:g} s | verde B {p['verde_b']:g} s")
        info.add_row("Próx. troca", f"{e.get('proxima_troca_em_s', 0):.1f} s")
    else:
        espera = e["pode_mudar_em_s"]
        info.add_row("Próx. legal", f"{e['proxima_fase_legal']} " + ("(liberada)" if espera <= 0 else f"(em {espera:.1f} s)"))
    c = e["conexao"]
    conexao = Text(c["descricao"], style="green") if c["conectado"] else Text(f"DESCONECTADO: {c.get('erro')}", style="bold red")
    info.add_row("Conexão", conexao)
    if e.get("desafio"):
        d = e["desafio"]
        info.add_row("DESAFIO", Text(f"'{d['perfil']}' faltam {d['restante_s']:.0f} s", style="bold yellow"))

    topo = Table.grid(padding=(0, 2))
    topo.add_row(luzes, info)

    transito = Table(title="Trânsito", expand=True, show_edge=False)
    transito.add_column("Dir.", style="bold", width=4)
    transito.add_column("Sensor")
    transito.add_column("Fluxo", justify="right")
    transito.add_column("Fila")
    for d in ("a", "b"):
        transito.add_row(
            d.upper(),
            Text.assemble(_barra(e["sensores"][d], 1023), f" {e['sensores'][d]:>4}"),
            f"{e['fluxo_carros_por_s'][d]:.2f}/s",
            Text.assemble(f"{e['filas'][d]:>3} ", _fila(e["filas"][d])),
        )

    p = e["placar"]
    placar = Text.assemble(
        ("Pontuação ", "bold"), (f"{p['pontuacao']:g}", "bold cyan"), "  (menor é melhor)   ",
        ("Espera total ", "bold"), f"{p['espera_total_s']:g} carro·s   ",
        ("Média ", "bold"), f"{p['espera_media_s']:g} s   ",
        ("Violações ", "bold"), (str(p["violacoes"]), "bold red" if p["violacoes"] else "green"),
    )
    if e.get("ultimo_desafio"):
        u = e["ultimo_desafio"]
        placar.append(f"\nÚltimo desafio '{u['perfil']}': pontuação {u['placar']['pontuacao']:g}", style="yellow")

    cmds = Table(title="Últimos comandos (tl ...)", expand=True, show_edge=False)
    cmds.add_column("Hora", width=8)
    cmds.add_column("Comando")
    cmds.add_column("Resultado")
    for ch in list(chamadas)[-max_comandos:] if max_comandos > 0 else []:
        estilo = {"ok": "green", "rejeitado": "bold red", "erro": "red"}.get(ch["resultado"], "")
        res = Text(ch["resultado"].upper(), style=estilo)
        if ch.get("mensagem"):
            res.append(f" {ch['mensagem'][:70]}", style="grey70")
        cmds.add_row(ch["hora"], f"tl {ch['comando']}", res)

    return Group(
        Panel(topo, title="Semáforo da oficina", subtitle="Ctrl+C para sair"),
        transito,
        Panel(placar, title="Placar"),
        cmds,
    )


def rodar_watch(cli: Client, intervalo: float = 0.25) -> int:
    chamadas: deque = deque(maxlen=50)
    ultimo = 0
    try:
        with Live(Text("conectando ao daemon..."), refresh_per_second=8, screen=False) as live:
            while True:
                try:
                    e = cli.get("/status")
                    r = cli.get("/chamadas", desde=ultimo)
                    chamadas.extend(r["chamadas"])
                    ultimo = r["ultimo"]
                    # ~22 linhas são fixas; o resto do terminal mostra comandos.
                    livres = max(0, min(15, live.console.height - 23))
                    live.update(montar_painel(e, chamadas, max_comandos=livres))
                except DaemonOffline:
                    live.update(Panel(Text(
                        "O daemon não está rodando.\nRode `tl daemon` ou `tl daemon --sim` em outro terminal.",
                        style="bold red"), title="Semáforo da oficina"))
                except ApiError as e:
                    live.update(Text(f"ERRO: {e.mensagem}", style="red"))
                time.sleep(intervalo)
    except KeyboardInterrupt:
        pass
    return 0
