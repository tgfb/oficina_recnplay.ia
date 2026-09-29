"""CLI `tl`: controla o semáforo por meio do `tl daemon`.

Códigos de saída:
    0  ok
    1  erro (argumento inválido, Arduino desconectado, ...)
    2  comando rejeitado pela segurança ou pelo modo atual
    3  o daemon não está rodando
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
from typing import List, Optional

from . import PORTA_HTTP_PADRAO, __version__
from . import phases as ph
from . import traffic as tr
from .client import ApiError, Client, DaemonOffline

SAIDA_OK = 0
SAIDA_ERRO = 1
SAIDA_REJEITADO = 2
SAIDA_OFFLINE = 3

MSG_OFFLINE = (
    "ERRO: o daemon não está rodando (ou não responde). "
    "Abra outro terminal, ative o venv e rode `tl daemon` (com a placa) ou `tl daemon --sim` (simulador)."
)


def _json(dados) -> None:
    print(json.dumps(dados, ensure_ascii=False, indent=2))


def _fmt_s(v: float) -> str:
    return f"{v:.1f} s"


# ------------------------------------------------------------------ textos

def texto_status(e: dict) -> str:
    linhas = []
    seg = "LIGADA" if e["seguranca"] else "DESLIGADA"
    linhas.append(f"Modo: {e['modo']} | Segurança: {seg}")
    fase = f"Fase: {e['fase']} há {_fmt_s(e['fase_decorrido_s'])}"
    if e["modo"] == "politica":
        fase += f" (próxima troca automática em {_fmt_s(e.get('proxima_troca_em_s', 0))})"
    else:
        espera = e["pode_mudar_em_s"]
        quando = "liberada agora" if espera <= 0 else f"liberada em {_fmt_s(espera)}"
        fase += f" | próxima fase legal: {e['proxima_fase_legal']} ({quando})"
    linhas.append(fase)
    linhas.append(f"Semáforo A (LED físico): {e['semaforo_a']} | Semáforo B (virtual): {e['semaforo_b']}")
    s, f, q = e["sensores"], e["fluxo_carros_por_s"], e["filas"]
    linhas.append(
        f"Sensores: A={s['a']} ({f['a']:.2f} carro/s) | B={s['b']} ({f['b']:.2f} carro/s)"
    )
    linhas.append(f"Filas: A={q['a']} carros | B={q['b']} carros")
    pol = e["politica"]
    linhas.append(f"Política: verde A {pol['verde_a']:g} s, verde B {pol['verde_b']:g} s")
    linhas.append(texto_placar_curto(e["placar"]))
    if e.get("desafio"):
        d = e["desafio"]
        linhas.append(
            f"DESAFIO '{d['perfil']}' em andamento: faltam {_fmt_s(d['restante_s'])} "
            "(os sensores estão sendo ignorados)"
        )
    c = e["conexao"]
    if c["conectado"]:
        linhas.append(f"Conexão: {c['descricao']} (ok)")
    else:
        linhas.append(f"Conexão: DESCONECTADO - {c.get('erro') or '?'}")
    return "\n".join(linhas)


def texto_placar_curto(p: dict) -> str:
    return (
        f"Placar: pontuação {p['pontuacao']:g} (menor é melhor) | espera total {p['espera_total_s']:g} carro·s | "
        f"espera média {p['espera_media_s']:g} s | violações {p['violacoes']}"
    )


def texto_placar(p: dict) -> str:
    return "\n".join([
        f"Pontuação: {p['pontuacao']:g}  (menor é melhor = espera total + {tr.PENALIDADE_VIOLACAO_S:g} por violação)",
        f"Espera total: {p['espera_total_s']:g} carro·s",
        f"Espera média por carro: {p['espera_media_s']:g} s",
        f"Carros: {p['carros_chegaram']} chegaram, {p['carros_passaram']} passaram",
        f"Fila máxima: A={p['fila_max']['a']} B={p['fila_max']['b']}",
        f"Violações: {p['violacoes']}",
    ])


# ---------------------------------------------------------------- comandos

def cmd_status(cli: Client, args) -> int:
    e = cli.get("/status")
    if args.json:
        _json(e)
    else:
        print(texto_status(e))
    return SAIDA_OK


def cmd_historico(cli: Client, args) -> int:
    h = cli.get("/historico", segundos=args.segundos)
    if args.json:
        _json(h)
        return SAIDA_OK
    print(f"Histórico dos últimos {args.segundos:g} s")
    print("Eventos:")
    if not h["eventos"]:
        print("  (nenhum)")
    for ev in h["eventos"]:
        print(f"  há {ev['ha_s']:>5.1f} s  {ev['texto']}")
    print("Amostras (a cada 5 s): há | fase | fila A | fila B | sensor A | sensor B")
    amostras = h["amostras"]
    for i, a in enumerate(reversed(amostras)):
        if i % 5:
            continue
        print(
            f"  há {a['ha_s']:>5.1f} s | {a['fase']:<14} | {a['filas']['a']:>3} | {a['filas']['b']:>3} "
            f"| {a['sensores']['a']:>4} | {a['sensores']['b']:>4}"
        )
    return SAIDA_OK


def cmd_sensores(cli: Client, args) -> int:
    s = cli.get("/sensores")
    if args.json:
        _json(s)
        return SAIDA_OK
    sen, f, q = s["sensores"], s["fluxo_carros_por_s"], s["filas"]
    print(f"Sensor A: {sen['a']:>4} / 1023  -> {f['a']:.2f} carro/s  | fila A: {q['a']} carros")
    print(f"Sensor B: {sen['b']:>4} / 1023  -> {f['b']:.2f} carro/s  | fila B: {q['b']} carros")
    if s.get("desafio"):
        print("(desafio em andamento: o fluxo vem do perfil fixo, não dos potenciômetros)")
    return SAIDA_OK


def cmd_fase(cli: Client, args) -> int:
    r = cli.post("/fase", {"fase": args.fase})
    if r.get("mensagem"):
        print(f"OK: {r['mensagem']}")
    else:
        print(f"OK: fase {r['fase']}")
    for aviso in r.get("avisos", []):
        print(f"AVISO (segurança desligada, violação registrada): {aviso}")
    return SAIDA_OK


def cmd_modo(cli: Client, args) -> int:
    r = cli.post("/modo", {"modo": args.modo})
    if r["modo"] == "politica":
        p = r["politica"]
        print(f"OK: modo política. O daemon roda o ciclo: verde A {p['verde_a']:g} s, verde B {p['verde_b']:g} s.")
    else:
        print("OK: modo direto. Use `tl fase <FASE>` para cada troca.")
    return SAIDA_OK


def cmd_politica(cli: Client, args) -> int:
    r = cli.post("/politica", {"verde_a": args.verde_a, "verde_b": args.verde_b})
    p = r["politica"]
    print(f"OK: política verde A {p['verde_a']:g} s, verde B {p['verde_b']:g} s "
          f"(amarelo {ph.AMARELO_S:g} s e vermelho-total {ph.VERMELHO_TOTAL_S:g} s são fixos)")
    if r.get("mensagem"):
        print(r["mensagem"])
    for aviso in r.get("avisos", []):
        print(f"AVISO: {aviso}")
    return SAIDA_OK


def cmd_placar(cli: Client, args) -> int:
    r = cli.post("/placar/zerar") if args.zerar else cli.get("/placar")
    if args.json:
        _json(r)
        return SAIDA_OK
    if args.zerar:
        print("OK: placar zerado.")
        return SAIDA_OK
    print(texto_placar(r["placar"]))
    if r.get("desafio"):
        print(f"(desafio '{r['desafio']['perfil']}' em andamento: faltam {_fmt_s(r['desafio']['restante_s'])})")
    if r.get("ultimo_desafio"):
        u = r["ultimo_desafio"]
        print(f"Último desafio: perfil '{u['perfil']}', {u['duracao_s']} s, pontuação {u['placar']['pontuacao']:g} "
              f"(terminou às {u['hora_fim']})")
    return SAIDA_OK


def cmd_desafio(cli: Client, args) -> int:
    r = cli.post("/desafio", {"perfil": args.perfil, "duracao": args.duracao})
    duracao = r["desafio"]["duracao_s"]
    print(f"Desafio '{args.perfil}' começou: {duracao} s. {tr.PERFIS[args.perfil]['descricao']}.")
    print("O placar foi zerado. Os potenciômetros estão sendo ignorados. Ctrl+C cancela.")
    cli = Client(cli.url)  # as consultas de progresso não entram no log de comandos
    try:
        while True:
            time.sleep(1.0)
            e = cli.get("/status")
            d = e.get("desafio")
            if not d:
                break
            p = e["placar"]
            linha = (f"\r  faltam {d['restante_s']:>5.0f} s | fase {e['fase']:<14} | filas A={e['filas']['a']:>2} "
                     f"B={e['filas']['b']:>2} | pontuação {p['pontuacao']:>7.1f} | violações {p['violacoes']}")
            print(linha, end="", flush=True)
    except KeyboardInterrupt:
        print()
        cli.post("/desafio/cancelar")
        print("Desafio cancelado.")
        return SAIDA_ERRO
    print()
    u = cli.get("/placar").get("ultimo_desafio")
    if not u:
        print("O desafio foi cancelado.")
        return SAIDA_ERRO
    print("=" * 60)
    print(f"RESULTADO DO DESAFIO '{u['perfil']}' ({u['duracao_s']} s)")
    print(texto_placar(u["placar"]))
    print("=" * 60)
    print(f"Escreva no quadro: PONTUAÇÃO {u['placar']['pontuacao']:g}")
    return SAIDA_OK


def cmd_seguranca(cli: Client, args) -> int:
    if args.acao is None:
        e = cli.get("/status")
        print(f"Segurança: {'LIGADA' if e['seguranca'] else 'DESLIGADA'}")
        return SAIDA_OK
    r = cli.post("/seguranca", {"ativa": args.acao == "ligar"})
    if r["seguranca"]:
        print("OK: segurança LIGADA. Comandos inseguros serão rejeitados.")
    else:
        print("OK: segurança DESLIGADA. Comandos inseguros serão aceitos (e contados como violação).")
    return SAIDA_OK


def cmd_raw(cli: Client, args) -> int:
    if args.enviar:
        r = cli.post("/raw", {"linha": args.enviar})
        print(f"> {r['enviado']}")
        print(f"< {r['resposta']}")
        return SAIDA_OK
    ultimo = max(0, cli.get("/raw", desde=10**12)["ultimo"] - args.ultimas)
    print("Linhas da serial (> PC para Arduino, < Arduino para PC). Ctrl+C para sair.")
    if not args.com_sensores:
        print("(sem S? e PING; use --com-sensores para ver tudo)")
    try:
        while True:
            r = cli.get("/raw", desde=ultimo)
            for linha in r["linhas"]:
                ultimo = linha["seq"]
                texto = linha["linha"]
                if not args.com_sensores and (texto in ("S?", "PING", "PONG") or texto.startswith("S ")):
                    continue
                print(f"{linha['hora']}  {linha['dir']} {texto}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    return SAIDA_OK


def cmd_sim(cli: Client, args) -> int:
    if args.auto:
        corpo = {"a": None, "b": None}
    else:
        if args.a is None and args.b is None:
            print("Informe --a e/ou --b (0-1023), ou --auto.", file=sys.stderr)
            return SAIDA_ERRO
        corpo = {"a": args.a, "b": args.b}
    cli.post("/sim", corpo)
    if args.auto:
        print("OK: potenciômetros simulados em modo automático (variam devagar).")
    else:
        print(f"OK: potenciômetros simulados A={args.a if args.a is not None else 'auto'} "
              f"B={args.b if args.b is not None else 'auto'}")
    return SAIDA_OK


def cmd_watch(cli: Client, args) -> int:
    from .watch import rodar_watch

    return rodar_watch(Client(cli.url), intervalo=args.intervalo)


def cmd_daemon(args) -> int:
    from .daemon import Daemon, rodar
    from .link import SerialLink, SimLink

    link = SimLink() if args.sim else SerialLink(args.porta)
    d = Daemon(link, seguranca=not args.sem_seguranca, verbose=args.verbose)
    return rodar(d, porta=args.http_porta)


def cmd_portas(args) -> int:
    from .link import listar_portas

    portas = listar_portas()
    if not args.todas:
        # Esconde portas sem dispositivo (ex.: /dev/ttyS* no Linux).
        portas = [p for p in portas if p["vid"] or p["descricao"] not in ("n/a", "")]
    if args.json:
        _json(portas)
        return SAIDA_OK
    if not portas:
        print("Nenhuma porta serial encontrada.")
        print("Confira o cabo USB (alguns cabos só carregam) e o driver (CH340 nos clones).")
        print("Use --todas para ver também as portas sem dispositivo.")
        return SAIDA_ERRO
    for p in portas:
        marca = "  <- " + p["nota"] if p["arduino"] else ""
        vid = f" [{p['vid']}:{p['pid']}]" if p["vid"] else ""
        print(f"{p['porta']}  {p['descricao']}{vid}{marca}")
    return SAIDA_OK


def cmd_doctor(args) -> int:
    ok_total = True
    avisos = 0

    def item(ok: Optional[bool], texto: str, dica: str = "") -> None:
        nonlocal ok_total, avisos
        marca = {True: "[ok]  ", False: "[FALHA]", None: "[aviso]"}[ok]
        print(f"{marca} {texto}")
        if dica and ok is not True:
            print(f"        -> {dica}")
        if ok is False:
            ok_total = False
        if ok is None:
            avisos += 1

    print(f"tl {__version__} | Python {platform.python_version()} | {platform.system()} {platform.release()}")
    item(sys.version_info >= (3, 9), "Python 3.9 ou mais novo", "instale um Python mais novo")
    venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    item(venv or None, "rodando dentro de um venv", "ative o venv (veja o guia do aluno)")
    for mod in ("serial", "rich"):
        try:
            __import__(mod)
            item(True, f"pacote {mod}")
        except ImportError:
            item(False, f"pacote {mod}", "rode `pip install -e .` na pasta do projeto")
    item(shutil.which("tl") is not None, "comando `tl` no PATH", "ative o venv antes de abrir o opencode")

    try:
        from .link import listar_portas

        arduinos = [p for p in listar_portas() if p["arduino"]]
        item(bool(arduinos) or None, "Arduino na USB: " + (", ".join(p["porta"] for p in arduinos) or "nenhum"),
             "sem placa? use `tl daemon --sim`. Com placa: confira cabo e driver CH340; rode `tl portas`")
    except Exception as e:
        item(None, f"não consegui listar portas: {e}")

    if platform.system() == "Linux":
        try:
            import grp

            grupos = {grp.getgrgid(g).gr_name for g in os.getgroups()}
            item("dialout" in grupos or "uucp" in grupos or None, "usuário no grupo dialout",
                 "`sudo usermod -aG dialout $USER` e faça login de novo")
        except Exception:
            pass

    try:
        e = Client(timeout=2.0).get("/status")
        c = e["conexao"]
        item(True, f"daemon rodando ({c['descricao']})")
        item(c["conectado"] or None, "daemon conectado à placa", c.get("erro") or "")
    except DaemonOffline:
        item(None, "daemon não está rodando", "rode `tl daemon` ou `tl daemon --sim` em outro terminal")
    except ApiError as e:
        item(False, f"daemon respondeu erro: {e.mensagem}")

    item(shutil.which("opencode") is not None or None, "opencode no PATH", "instale o opencode (veja o guia)")
    for var in ("CLUSTER_BASE_URL", "CLUSTER_API_KEY", "CLUSTER_MODEL"):
        item(bool(os.environ.get(var)) or None, f"variável {var} definida", "veja o guia do aluno, seção do opencode")
    if not ok_total:
        print("Há falhas: veja as dicas acima.")
    elif avisos:
        print(f"Sem falhas, mas com {avisos} aviso(s): veja as dicas acima.")
    else:
        print("Tudo certo!")
    return SAIDA_OK if ok_total else SAIDA_ERRO


# ------------------------------------------------------------------ parser

def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tl",
        description="Controla o semáforo da oficina (Arduino ou simulador) por meio do `tl daemon`.",
        epilog="Fases: " + " -> ".join(ph.FASES[:3]) + " -> B-verde -> B-amarelo -> vermelho-total -> A-verde",
    )
    p.add_argument("--version", action="version", version=f"tl {__version__}")
    sub = p.add_subparsers(dest="comando", metavar="COMANDO")
    sub.required = True

    s = sub.add_parser("daemon", help="inicia o daemon (dono da porta serial). Deixe rodando em um terminal")
    s.add_argument("--sim", action="store_true", help="usa o simulador em vez da placa")
    s.add_argument("--porta", help="porta serial (ex.: COM3, /dev/ttyACM0). Sem ela, detecta sozinho")
    s.add_argument("--http-porta", type=int, default=PORTA_HTTP_PADRAO, help="porta HTTP local (padrão 8765)")
    s.add_argument("--sem-seguranca", action="store_true", help="inicia com a segurança desligada")
    s.add_argument("--verbose", "-v", action="store_true", help="mostra todas as linhas da serial no log")

    s = sub.add_parser("portas", help="lista as portas seriais e marca o provável Arduino")
    s.add_argument("--todas", action="store_true", help="mostra também portas sem dispositivo")
    s.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="verifica a instalação (Python, venv, placa, daemon, opencode)")

    s = sub.add_parser("status", help="estado atual: fase, sensores, filas, placar")
    s.add_argument("--json", action="store_true", help="saída em JSON")

    s = sub.add_parser("historico", help="eventos e amostras dos últimos segundos")
    s.add_argument("--segundos", type=float, default=30.0, help="janela em segundos (padrão 30)")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("sensores", help="valores dos potenciômetros e fluxo de carros")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("fase", help="muda a fase (só no modo direto)")
    s.add_argument("fase", help="A-verde, A-amarelo, vermelho-total, B-verde ou B-amarelo")

    s = sub.add_parser("modo", help="escolhe o modo: direto (você troca cada fase) ou politica (o daemon roda o ciclo)")
    s.add_argument("modo", choices=["direto", "politica"])

    s = sub.add_parser("politica", help="define os tempos de verde do modo política")
    s.add_argument("--verde-a", type=float, required=True, metavar="S", help="segundos de verde para A")
    s.add_argument("--verde-b", type=float, required=True, metavar="S", help="segundos de verde para B")

    s = sub.add_parser("placar", help="mostra o placar (espera, violações, pontuação)")
    s.add_argument("--zerar", action="store_true", help="zera o placar")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("desafio", help="desafio com trânsito fixo para comparar pontuações")
    s.add_argument("--duracao", type=int, default=180, help="segundos (padrão 180)")
    s.add_argument("--perfil", choices=list(tr.PERFIS), default="pico")

    s = sub.add_parser("watch", help="painel no terminal com os dois semáforos, filas e comandos")
    s.add_argument("--intervalo", type=float, default=0.25, help=argparse.SUPPRESS)

    s = sub.add_parser("raw", help="mostra as linhas da serial ao vivo (ou envia uma com --enviar)")
    s.add_argument("--enviar", metavar="LINHA", help='envia uma linha crua, ex.: --enviar "S?"')
    s.add_argument("--com-sensores", action="store_true", help="mostra também S? e PING")
    s.add_argument("--ultimas", type=int, default=10, help="quantas linhas antigas mostrar no início")

    s = sub.add_parser("seguranca", help="liga/desliga a segurança (instrutor)")
    s.add_argument("acao", nargs="?", choices=["ligar", "desligar"])

    s = sub.add_parser("sim", help="define os potenciômetros do simulador")
    s.add_argument("--a", type=int, help="valor 0-1023 para A")
    s.add_argument("--b", type=int, help="valor 0-1023 para B")
    s.add_argument("--auto", action="store_true", help="volta ao modo automático")

    return p


COMANDOS_CLIENTE = {
    "status": cmd_status,
    "historico": cmd_historico,
    "sensores": cmd_sensores,
    "fase": cmd_fase,
    "modo": cmd_modo,
    "politica": cmd_politica,
    "placar": cmd_placar,
    "desafio": cmd_desafio,
    "seguranca": cmd_seguranca,
    "raw": cmd_raw,
    "sim": cmd_sim,
    "watch": cmd_watch,
}


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _utf8_no_terminal()
    args = criar_parser().parse_args(argv)
    if args.comando == "daemon":
        return cmd_daemon(args)
    if args.comando == "portas":
        return cmd_portas(args)
    if args.comando == "doctor":
        return cmd_doctor(args)

    comando = " ".join(argv) if args.comando not in ("watch", "raw") else ""
    cli = Client(comando=comando)
    try:
        return COMANDOS_CLIENTE[args.comando](cli, args)
    except DaemonOffline:
        print(MSG_OFFLINE, file=sys.stderr)
        return SAIDA_OFFLINE
    except ApiError as e:
        print(f"ERRO: {e.mensagem}", file=sys.stderr)
        for v in e.dados.get("violacoes", [])[1:]:
            print(f"ERRO: {v}", file=sys.stderr)
        if e.status == 409 and e.dados.get("violacoes"):
            print("(violação registrada no placar)", file=sys.stderr)
        return SAIDA_REJEITADO if e.status == 409 else SAIDA_ERRO


def _utf8_no_terminal() -> None:
    """Evita erro de acentos em terminais antigos do Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    sys.exit(main())
