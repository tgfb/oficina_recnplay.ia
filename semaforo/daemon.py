"""Daemon do semáforo: dono da porta serial, fases, segurança, trânsito e API HTTP.

Só este processo fala com o Arduino. A CLI `tl` e o `tl watch` falam com ele
por HTTP em localhost (JSON).
"""

from __future__ import annotations

import json
import queue
import random
import signal
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import PORTA_HTTP_PADRAO, __version__
from . import phases as ph
from . import protocol
from . import traffic as tr
from .link import Link, LinkError, SimLink

TICK_S = 0.1
SENSOR_S = 0.2
PING_S = 1.0
RECONEXAO_S = 2.0
AMOSTRA_S = 1.0

POLITICA_MAX_S = 120.0
DESAFIO_MIN_S = 10
DESAFIO_MAX_S = 900

MODOS = ("direto", "politica")


class ApiErro(Exception):
    def __init__(self, status: int, mensagem: str, **extra) -> None:
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem
        self.extra = extra


def _hora() -> str:
    return time.strftime("%H:%M:%S")


class Daemon:
    def __init__(
        self,
        link: Link,
        relogio: Callable[[], float] = time.monotonic,
        seguranca: bool = True,
        verbose: bool = False,
        saida=None,
    ) -> None:
        self.lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self.relogio = relogio
        self.verbose = verbose
        self.saida = saida if saida is not None else sys.stdout

        self.link = link
        self.link.on_raw = self._registrar_raw
        self.conectado = False
        self.erro_conexao: Optional[str] = None
        self._proxima_tentativa = 0.0

        agora = relogio()
        self.inicio = agora
        self.cruz = ph.Cruzamento(agora)
        self.modo = "direto"
        self.seguranca = seguranca
        self.politica = {"verde_a": 15.0, "verde_b": 15.0}
        self.sensores = {"A": 0, "B": 0}

        self.transito = tr.Transito()
        self.rng = random.Random()
        self.desafio: Optional[dict] = None
        self.ultimo_desafio: Optional[dict] = None

        self.raw: deque = deque(maxlen=1000)
        self._raw_seq = 0
        self.chamadas: deque = deque(maxlen=300)
        self._chamada_seq = 0
        self.eventos: deque = deque(maxlen=1000)
        self.amostras: deque = deque(maxlen=900)

        self._fila_raw: "queue.Queue" = queue.Queue()
        self._led_aplicado: Optional[str] = None
        self._ultimo_tick = agora
        self._ultimo_sensor = -1e9
        self._ultimo_ping = -1e9
        self._ultima_amostra = -1e9

    # ------------------------------------------------------------------ logs

    def _imprimir(self, texto: str) -> None:
        try:
            print(f"{_hora()}  {texto}", file=self.saida, flush=True)
        except Exception:
            pass

    def _registrar_raw(self, direcao: str, linha: str) -> None:
        with self.lock:
            self._raw_seq += 1
            self.raw.append({"seq": self._raw_seq, "hora": _hora(), "dir": direcao, "linha": linha})
        if self.verbose:
            self._imprimir(f"serial {direcao} {linha}")

    def _evento(self, texto: str, agora: Optional[float] = None) -> None:
        agora = self.relogio() if agora is None else agora
        self.eventos.append({"t": agora, "hora": _hora(), "texto": texto})
        self._imprimir(texto)

    def registrar_chamada(self, comando: str, resultado: str, mensagem: str = "") -> None:
        with self.lock:
            self._chamada_seq += 1
            self.chamadas.append({
                "seq": self._chamada_seq,
                "hora": _hora(),
                "t": self.relogio(),
                "comando": comando,
                "resultado": resultado,
                "mensagem": mensagem,
            })
        extra = f"  ({mensagem})" if mensagem else ""
        self._imprimir(f"tl {comando}  -> {resultado.upper()}{extra}")

    # --------------------------------------------------------------- tick

    def tick(self) -> None:
        """Um passo do laço principal (10 vezes por segundo)."""
        with self._tick_lock:
            agora = self.relogio()
            self._cuidar_conexao(agora)
            self._processar_raw()
            if self.conectado:
                try:
                    self._falar_com_placa(agora)
                except LinkError as e:
                    self._desconectar(str(e), agora)
            with self.lock:
                self._avancar(agora)

    def _cuidar_conexao(self, agora: float) -> None:
        if self.conectado or agora < self._proxima_tentativa:
            return
        self._proxima_tentativa = agora + RECONEXAO_S
        try:
            self.link.abrir()
        except LinkError as e:
            if str(e) != self.erro_conexao:
                self._evento(f"Arduino desconectado: {e}")
            self.erro_conexao = str(e)
            return
        self.conectado = True
        self.erro_conexao = None
        self._led_aplicado = None
        self._evento(f"conectado: {self.link.descricao}")

    def _desconectar(self, motivo: str, agora: float) -> None:
        self.conectado = False
        self.erro_conexao = motivo
        self._proxima_tentativa = agora + RECONEXAO_S
        try:
            self.link.fechar()
        except Exception:
            pass
        self._evento(f"conexão perdida: {motivo}")

    def _falar_com_placa(self, agora: float) -> None:
        if agora - self._ultimo_sensor >= SENSOR_S:
            self._ultimo_sensor = agora
            resp = protocol.parse(self.link.enviar(protocol.cmd_sensores()))
            a, b = protocol.parse_sensores(resp)
            with self.lock:
                self.sensores = {"A": a, "B": b}
        with self.lock:
            led = ph.led_fisico(self.cruz.fase)
        if led != self._led_aplicado:
            resp = self.link.enviar(protocol.cmd_led(led))
            if resp != f"OK L {led}":
                raise LinkError(f"resposta inesperada para L {led}: {resp!r}")
            self._led_aplicado = led
        if agora - self._ultimo_ping >= PING_S:
            self._ultimo_ping = agora
            if self.link.enviar(protocol.cmd_ping()) != "PONG":
                raise LinkError("PING sem PONG")

    def _processar_raw(self) -> None:
        while True:
            try:
                linha, pronto, caixa = self._fila_raw.get_nowait()
            except queue.Empty:
                return
            try:
                if not self.conectado:
                    raise LinkError("Arduino desconectado")
                caixa["resposta"] = self.link.enviar(linha)
                if linha.startswith(("L ", "B")):
                    # O LED mudou por fora: fica assim até a próxima troca de fase.
                    with self.lock:
                        self._led_aplicado = ph.led_fisico(self.cruz.fase)
            except LinkError as e:
                caixa["erro"] = str(e)
            finally:
                pronto.set()

    def _avancar(self, agora: float) -> None:
        dt = max(0.0, agora - self._ultimo_tick)
        self._ultimo_tick = agora

        if self.modo == "politica":
            destino = ph.passo_politica(self.cruz, agora, self.politica["verde_a"], self.politica["verde_b"])
            if destino:
                self._mudar_fase(destino, agora, origem="política")

        chegadas = self._chegadas(agora, dt)
        self.transito.passo(agora, dt, chegadas, ph.direcao_verde(self.cruz.fase))

        if self.desafio and agora - self.desafio["inicio"] >= self.desafio["duracao"]:
            self._terminar_desafio(agora)

        if agora - self._ultima_amostra >= AMOSTRA_S:
            self._ultima_amostra = agora
            self.amostras.append({
                "t": agora,
                "hora": _hora(),
                "fase": self.cruz.fase,
                "filas": {d.lower(): n for d, n in self.transito.tamanho_filas().items()},
                "sensores": {"a": self.sensores["A"], "b": self.sensores["B"]},
            })

    def _chegadas(self, agora: float, dt: float) -> Dict[str, int]:
        if self.desafio:
            t = agora - self.desafio["inicio"]
            lista = self.desafio["chegadas"]
            chegadas = {"A": 0, "B": 0}
            while self.desafio["idx"] < len(lista) and lista[self.desafio["idx"]][0] <= t:
                chegadas[lista[self.desafio["idx"]][1]] += 1
                self.desafio["idx"] += 1
            return chegadas
        return {d: tr.poisson(self.rng, tr.taxa_do_sensor(self.sensores[d]) * dt) for d in tr.DIRECOES}

    def _taxas(self, agora: float) -> Dict[str, float]:
        if self.desafio:
            a, b = tr.taxas_perfil(self.desafio["perfil"], agora - self.desafio["inicio"])
            return {"A": a, "B": b}
        return {d: tr.taxa_do_sensor(self.sensores[d]) for d in tr.DIRECOES}

    def _mudar_fase(self, destino: str, agora: float, origem: str) -> list:
        """Aplica a troca. Com segurança ligada, rejeita se houver violação."""
        violacoes = self.cruz.verificar(destino, agora)
        if violacoes:
            self.transito.registrar_violacao()
            if self.seguranca:
                self._evento(f"VIOLAÇÃO rejeitada ({origem}): {' '.join(violacoes)}", agora)
                raise ApiErro(409, violacoes[0], violacoes=violacoes)
            self._evento(f"VIOLAÇÃO aceita, segurança desligada ({origem}): {' '.join(violacoes)}", agora)
        anterior = self.cruz.fase
        self.cruz.aplicar(destino, agora)
        self._evento(f"fase {anterior} -> {destino} ({origem})", agora)
        return violacoes

    # ------------------------------------------------------------- desafio

    def _terminar_desafio(self, agora: float) -> None:
        d = self.desafio
        self.ultimo_desafio = {
            "perfil": d["perfil"],
            "duracao_s": d["duracao"],
            "hora_fim": _hora(),
            "placar": self.transito.placar(),
        }
        self.desafio = None
        p = self.ultimo_desafio["placar"]
        self._evento(
            f"desafio '{d['perfil']}' terminou: pontuação {p['pontuacao']} "
            f"(espera {p['espera_total_s']} carro·s, {p['violacoes']} violações)",
            agora,
        )

    # ----------------------------------------------------------------- API

    def estado(self) -> dict:
        with self.lock:
            agora = self.relogio()
            fase = self.cruz.fase
            taxas = self._taxas(agora)
            info = {
                "versao": __version__,
                "modo": self.modo,
                "seguranca": self.seguranca,
                "fase": fase,
                "fase_decorrido_s": round(self.cruz.decorrido(agora), 1),
                "proxima_fase_legal": self.cruz.proxima_legal(),
                "pode_mudar_em_s": round(self.cruz.falta_para_mudar(agora), 1),
                "semaforo_a": ph.cor(fase, "A"),
                "semaforo_b": ph.cor(fase, "B"),
                "sensores": {"a": self.sensores["A"], "b": self.sensores["B"]},
                "fluxo_carros_por_s": {"a": round(taxas["A"], 3), "b": round(taxas["B"], 3)},
                "filas": {d.lower(): n for d, n in self.transito.tamanho_filas().items()},
                "politica": dict(self.politica),
                "placar": self.transito.placar(),
                "desafio": self._info_desafio(agora),
                "ultimo_desafio": self.ultimo_desafio,
                "conexao": {
                    "tipo": self.link.tipo,
                    "descricao": self.link.descricao,
                    "conectado": self.conectado,
                    "erro": self.erro_conexao,
                },
                "tempo_ligado_s": round(agora - self.inicio, 1),
            }
            if self.modo == "politica":
                dur = ph.duracao_politica(fase, self.politica["verde_a"], self.politica["verde_b"])
                info["proxima_troca_em_s"] = round(max(0.0, dur - self.cruz.decorrido(agora)), 1)
            if isinstance(self.link, SimLink):
                info["led_simulado"] = self.link.estado_led()
            return info

    def _info_desafio(self, agora: float) -> Optional[dict]:
        if not self.desafio:
            return None
        decorrido = agora - self.desafio["inicio"]
        return {
            "perfil": self.desafio["perfil"],
            "duracao_s": self.desafio["duracao"],
            "decorrido_s": round(decorrido, 1),
            "restante_s": round(max(0.0, self.desafio["duracao"] - decorrido), 1),
        }

    def historico(self, segundos: float) -> dict:
        with self.lock:
            agora = self.relogio()
            limite = agora - segundos

            def rel(item):
                item = dict(item)
                item["ha_s"] = round(agora - item.pop("t"), 1)
                return item

            return {
                "segundos": segundos,
                "eventos": [rel(e) for e in self.eventos if e["t"] >= limite],
                "amostras": [rel(a) for a in self.amostras if a["t"] >= limite],
            }

    def api_fase(self, corpo: dict) -> dict:
        nome = str(corpo.get("fase", ""))
        destino = ph.normalizar_fase(nome)
        if not destino:
            raise ApiErro(400, f"fase desconhecida: {nome!r}. Fases válidas: {', '.join(ph.FASES)}.")
        with self.lock:
            if self.modo == "politica":
                raise ApiErro(
                    409,
                    "Modo política ativo: o daemon controla as fases sozinho. "
                    "Use `tl politica --verde-a N --verde-b N` para mudar os tempos, "
                    "ou `tl modo direto` para controlar cada fase.",
                )
            if not self.conectado:
                raise ApiErro(503, f"Arduino desconectado: {self.erro_conexao}")
            agora = self.relogio()
            if destino == self.cruz.fase:
                return {"ok": True, "fase": destino, "mensagem": f"já está em {destino}", "avisos": []}
            avisos = self._mudar_fase(destino, agora, origem="tl fase")
            return {"ok": True, "fase": destino, "avisos": avisos}

    def api_modo(self, corpo: dict) -> dict:
        modo = str(corpo.get("modo", "")).lower().replace("í", "i")
        if modo not in MODOS:
            raise ApiErro(400, f"modo desconhecido: {corpo.get('modo')!r}. Use 'direto' ou 'politica'.")
        with self.lock:
            if modo != self.modo:
                self.modo = modo
                self._evento(f"modo -> {modo}")
            return {"ok": True, "modo": modo, "politica": dict(self.politica)}

    def api_politica(self, corpo: dict) -> dict:
        try:
            verde_a = float(corpo["verde_a"])
            verde_b = float(corpo["verde_b"])
        except (KeyError, TypeError, ValueError):
            raise ApiErro(400, "informe verde_a e verde_b em segundos (números).")
        for nome, v in (("verde-a", verde_a), ("verde-b", verde_b)):
            if not (1.0 <= v <= POLITICA_MAX_S):
                raise ApiErro(400, f"--{nome} precisa ficar entre 1 e {POLITICA_MAX_S:g} s (recebi {v:g}).")
        with self.lock:
            curtos = [v for v in (verde_a, verde_b) if v < ph.VERDE_MIN_S]
            avisos = []
            if curtos:
                msg = f"O verde precisa durar pelo menos {ph.VERDE_MIN_S:g} s (recebi {min(curtos):g} s)."
                if self.seguranca:
                    self.transito.registrar_violacao()
                    self._evento(f"VIOLAÇÃO rejeitada (tl politica): {msg}")
                    raise ApiErro(409, msg, violacoes=[msg])
                avisos.append(msg + " Cada troca com verde curto conta uma violação.")
            self.politica = {"verde_a": verde_a, "verde_b": verde_b}
            self._evento(f"política: verde A {verde_a:g} s, verde B {verde_b:g} s")
            resp = {"ok": True, "politica": dict(self.politica), "modo": self.modo, "avisos": avisos}
            if self.modo != "politica":
                resp["mensagem"] = "Valores guardados. O modo atual é direto: use `tl modo politica` para ativar."
            return resp

    def api_placar(self) -> dict:
        with self.lock:
            return {
                "placar": self.transito.placar(),
                "desafio": self._info_desafio(self.relogio()),
                "ultimo_desafio": self.ultimo_desafio,
            }

    def api_zerar_placar(self) -> dict:
        with self.lock:
            if self.desafio:
                raise ApiErro(409, "Há um desafio em andamento. Espere terminar ou cancele com Ctrl+C no `tl desafio`.")
            self.transito.zerar()
            self._evento("placar zerado")
            return {"ok": True, "placar": self.transito.placar()}

    def api_desafio(self, corpo: dict) -> dict:
        perfil = str(corpo.get("perfil", "pico"))
        if perfil not in tr.PERFIS:
            raise ApiErro(400, f"perfil desconhecido: {perfil!r}. Perfis: {', '.join(tr.PERFIS)}.")
        try:
            duracao = int(corpo.get("duracao", 180))
        except (TypeError, ValueError):
            raise ApiErro(400, "duração inválida")
        if not (DESAFIO_MIN_S <= duracao <= DESAFIO_MAX_S):
            raise ApiErro(400, f"a duração precisa ficar entre {DESAFIO_MIN_S} e {DESAFIO_MAX_S} s.")
        with self.lock:
            if self.desafio:
                raise ApiErro(409, "Já há um desafio em andamento.")
            agora = self.relogio()
            self.transito.zerar()
            self.desafio = {
                "perfil": perfil,
                "duracao": duracao,
                "inicio": agora,
                "chegadas": tr.gerar_chegadas(perfil, duracao),
                "idx": 0,
            }
            self._evento(f"desafio '{perfil}' começou ({duracao} s): placar zerado, sensores ignorados", agora)
            return {"ok": True, "desafio": self._info_desafio(agora)}

    def api_cancelar_desafio(self) -> dict:
        with self.lock:
            if not self.desafio:
                return {"ok": True, "mensagem": "nenhum desafio em andamento"}
            self.desafio = None
            self._evento("desafio cancelado")
            return {"ok": True}

    def api_seguranca(self, corpo: dict) -> dict:
        ativa = corpo.get("ativa")
        if not isinstance(ativa, bool):
            raise ApiErro(400, "informe ativa: true ou false")
        with self.lock:
            self.seguranca = ativa
            self._evento(f"segurança {'LIGADA' if ativa else 'DESLIGADA'}")
            return {"ok": True, "seguranca": ativa}

    def api_raw_listar(self, desde: int) -> dict:
        with self.lock:
            return {"linhas": [r for r in self.raw if r["seq"] > desde], "ultimo": self._raw_seq}

    def api_raw_enviar(self, corpo: dict) -> dict:
        linha = str(corpo.get("linha", "")).strip()
        if not linha or len(linha) > 64 or not linha.isascii():
            raise ApiErro(400, "linha inválida (texto ASCII, até 64 caracteres)")
        pronto = threading.Event()
        caixa: dict = {}
        self._fila_raw.put((linha, pronto, caixa))
        if not pronto.wait(3.0):
            raise ApiErro(504, "o daemon não enviou a linha a tempo")
        if "erro" in caixa:
            raise ApiErro(503, caixa["erro"])
        return {"ok": True, "enviado": linha, "resposta": caixa["resposta"]}

    def api_chamadas(self, desde: int) -> dict:
        with self.lock:
            return {"chamadas": [dict(c, t=None) for c in self.chamadas if c["seq"] > desde],
                    "ultimo": self._chamada_seq}

    def api_sim(self, corpo: dict) -> dict:
        if not isinstance(self.link, SimLink):
            raise ApiErro(400, "`tl sim` só funciona com `tl daemon --sim`. Com a placa, gire os potenciômetros.")

        def valor(chave):
            v = corpo.get(chave)
            if v is None:
                return None
            v = int(v)
            if not 0 <= v <= 1023:
                raise ApiErro(400, "os valores precisam ficar entre 0 e 1023")
            return v

        a, b = valor("a"), valor("b")
        self.link.definir_pots(a, b)
        desc = "automático" if a is None and b is None else f"A={a if a is not None else 'auto'} B={b if b is not None else 'auto'}"
        self._evento(f"simulador: potenciômetros {desc}")
        return {"ok": True, "a": a, "b": b}

    def parar(self) -> None:
        """Deixa o semáforo em amarelo piscante e fecha a porta."""
        with self._tick_lock:
            if self.conectado:
                try:
                    self.link.enviar(protocol.cmd_piscar())
                except LinkError:
                    pass
            self.link.fechar()
            self.conectado = False


# ---------------------------------------------------------------------- HTTP

def _criar_handler(daemon: Daemon):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"tl-daemon/{__version__}"

        def log_message(self, format, *args):  # silencia o log padrão
            pass

        def _responder(self, status: int, dados: dict) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _corpo(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                dados = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiErro(400, "JSON inválido")
            if not isinstance(dados, dict):
                raise ApiErro(400, "JSON precisa ser um objeto")
            return dados

        def _tratar(self, metodo: str) -> None:
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            comando = unquote(self.headers.get("X-TL-Comando", "") or "")
            try:
                status, dados = 200, self._rota(metodo, url.path, q)
                if comando:
                    daemon.registrar_chamada(comando, "ok", "; ".join(dados.get("avisos") or []))
            except ApiErro as e:
                status = e.status
                dados = {"ok": False, "erro": e.mensagem, **e.extra}
                if comando:
                    resultado = "rejeitado" if e.status == 409 else "erro"
                    daemon.registrar_chamada(comando, resultado, e.mensagem)
            except Exception as e:  # erro interno: não derruba o daemon
                status, dados = 500, {"ok": False, "erro": f"erro interno no daemon: {e!r}"}
                daemon._imprimir(f"ERRO interno: {e!r}")
            self._responder(status, dados)

        def _rota(self, metodo: str, caminho: str, q: dict) -> dict:
            d = daemon
            if metodo == "GET":
                if caminho == "/status":
                    return d.estado()
                if caminho == "/historico":
                    return d.historico(float(q.get("segundos", 30)))
                if caminho == "/sensores":
                    e = d.estado()
                    return {k: e[k] for k in ("sensores", "fluxo_carros_por_s", "filas", "desafio")}
                if caminho == "/placar":
                    return d.api_placar()
                if caminho == "/raw":
                    return d.api_raw_listar(int(q.get("desde", 0)))
                if caminho == "/chamadas":
                    return d.api_chamadas(int(q.get("desde", 0)))
            elif metodo == "POST":
                corpo = self._corpo()
                rotas = {
                    "/fase": lambda: d.api_fase(corpo),
                    "/modo": lambda: d.api_modo(corpo),
                    "/politica": lambda: d.api_politica(corpo),
                    "/placar/zerar": d.api_zerar_placar,
                    "/desafio": lambda: d.api_desafio(corpo),
                    "/desafio/cancelar": d.api_cancelar_desafio,
                    "/seguranca": lambda: d.api_seguranca(corpo),
                    "/raw": lambda: d.api_raw_enviar(corpo),
                    "/sim": lambda: d.api_sim(corpo),
                }
                if caminho in rotas:
                    return rotas[caminho]()
            raise ApiErro(404, f"rota desconhecida: {metodo} {caminho}")

        def do_GET(self):
            self._tratar("GET")

        def do_POST(self):
            self._tratar("POST")

    return Handler


def criar_servidor(daemon: Daemon, host: str = "127.0.0.1", porta: int = PORTA_HTTP_PADRAO) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer((host, porta), _criar_handler(daemon))
    servidor.daemon_threads = True
    return servidor


def laco_tick(daemon: Daemon, parar: threading.Event) -> None:
    while not parar.is_set():
        inicio = time.monotonic()
        try:
            daemon.tick()
        except Exception as e:  # nunca deixa o laço morrer
            daemon._imprimir(f"ERRO no laço principal: {e!r}")
        parar.wait(max(0.0, TICK_S - (time.monotonic() - inicio)))


def iniciar_em_threads(daemon: Daemon, host: str = "127.0.0.1", porta: int = PORTA_HTTP_PADRAO) -> Tuple[ThreadingHTTPServer, threading.Event]:
    """Sobe o servidor HTTP e o laço de tick em threads. Usado pelos testes e por `rodar`."""
    servidor = criar_servidor(daemon, host, porta)
    parar = threading.Event()
    threading.Thread(target=laco_tick, args=(daemon, parar), daemon=True).start()
    threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    return servidor, parar


def rodar(daemon: Daemon, porta: int = PORTA_HTTP_PADRAO) -> int:
    try:
        servidor, parar = iniciar_em_threads(daemon, "127.0.0.1", porta)
    except OSError as e:
        print(
            f"ERRO: não consegui usar a porta HTTP {porta} ({e}). "
            "Outro `tl daemon` já está rodando? Feche-o ou use --http-porta.",
            file=sys.stderr,
        )
        return 1
    seg = "LIGADA" if daemon.seguranca else "DESLIGADA"
    daemon._imprimir(
        f"tl daemon {__version__} em http://127.0.0.1:{porta}  |  {daemon.link.descricao}  |  segurança {seg}"
    )
    daemon._imprimir("Deixe este terminal aberto. Ctrl+C para parar.")

    def _sinal(*_):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _sinal)
    except (ValueError, AttributeError):
        pass
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        daemon._imprimir("parando: semáforo em amarelo piscante")
    finally:
        parar.set()
        servidor.shutdown()
        daemon.parar()
    return 0
