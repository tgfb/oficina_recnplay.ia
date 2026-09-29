"""Conexão com o Arduino: porta serial real (pyserial) ou simulador no processo."""

from __future__ import annotations

import math
import time
from typing import Callable, List, Optional

from . import protocol

# Callback para o log bruto: (direção, linha). Direção: ">" enviado, "<" recebido.
RawLog = Callable[[str, str], None]

# VIDs USB comuns: Arduino, Arduino (novo), CH340 (clones), FTDI, CP210x.
VIDS_ARDUINO = {0x2341: "Arduino", 0x2A03: "Arduino", 0x1A86: "CH340", 0x0403: "FTDI", 0x10C4: "CP210x"}
PALAVRAS_ARDUINO = ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "wch")

WATCHDOG_S = 3.0


class LinkError(Exception):
    """Falha de comunicação com a placa."""


class Link:
    descricao = "?"
    tipo = "?"

    def __init__(self) -> None:
        self.on_raw: Optional[RawLog] = None

    def _log(self, direcao: str, linha: str) -> None:
        if self.on_raw:
            self.on_raw(direcao, linha)

    def abrir(self) -> None:
        raise NotImplementedError

    def enviar(self, linha: str, timeout: float = 0.5) -> str:
        """Envia uma linha e devolve a resposta. Lança LinkError."""
        raise NotImplementedError

    def fechar(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Simulador: um "Arduino falso" com o mesmo protocolo e o mesmo watchdog.
# ---------------------------------------------------------------------------

class SimLink(Link):
    tipo = "sim"
    descricao = "simulador"

    def __init__(self, relogio: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.relogio = relogio
        self.led = "O"
        self.piscando = False
        self.watchdog_ativo = False
        self.pot_a: Optional[int] = None  # None = automático
        self.pot_b: Optional[int] = None
        self._ultimo_cmd = relogio()
        self._t0 = relogio()

    def abrir(self) -> None:
        self._ultimo_cmd = self.relogio()
        self._log("<", f"READY semaforo {protocol.VERSAO}")

    def pots(self) -> tuple:
        """Valores dos potenciômetros. No modo automático variam devagar (período 2 min)."""
        t = self.relogio() - self._t0
        auto_a = int(512 + 380 * math.sin(2 * math.pi * t / 120.0))
        auto_b = int(512 + 380 * math.sin(2 * math.pi * t / 120.0 + math.pi))
        a = auto_a if self.pot_a is None else self.pot_a
        b = auto_b if self.pot_b is None else self.pot_b
        return min(1023, max(0, a)), min(1023, max(0, b))

    def definir_pots(self, a: Optional[int], b: Optional[int]) -> None:
        self.pot_a, self.pot_b = a, b

    def estado_led(self) -> str:
        """LED visível agora: R, Y, G, O ou 'B' (amarelo piscante)."""
        if self.relogio() - self._ultimo_cmd > WATCHDOG_S:
            self.watchdog_ativo = True
        if self.piscando or self.watchdog_ativo:
            return "B"
        return self.led

    def enviar(self, linha: str, timeout: float = 0.5) -> str:
        self._log(">", linha)
        self._ultimo_cmd = self.relogio()
        self.watchdog_ativo = False
        partes = linha.strip().split()
        if partes == ["PING"]:
            resp = "PONG"
        elif len(partes) == 2 and partes[0] == "L" and partes[1] in protocol.LEDS:
            self.led = partes[1]
            self.piscando = False
            resp = f"OK L {partes[1]}"
        elif partes == ["B"]:
            self.piscando = True
            resp = "OK B"
        elif partes == ["S?"]:
            a, b = self.pots()
            resp = f"S {a} {b}"
        else:
            resp = "ERR comando desconhecido"
        self._log("<", resp)
        return resp


# ---------------------------------------------------------------------------
# Porta serial real.
# ---------------------------------------------------------------------------

def listar_portas() -> List[dict]:
    """Portas seriais do sistema, com uma nota se parece um Arduino."""
    from serial.tools import list_ports

    portas = []
    for p in list_ports.comports():
        nota = ""
        if p.vid in VIDS_ARDUINO:
            nota = VIDS_ARDUINO[p.vid]
        else:
            texto = f"{p.description} {p.manufacturer or ''}".lower()
            if any(k in texto for k in PALAVRAS_ARDUINO):
                nota = "provável Arduino"
        portas.append({
            "porta": p.device,
            "descricao": p.description,
            "vid": f"{p.vid:04X}" if p.vid is not None else None,
            "pid": f"{p.pid:04X}" if p.pid is not None else None,
            "arduino": bool(nota),
            "nota": nota,
        })
    portas.sort(key=lambda x: (not x["arduino"], x["porta"]))
    return portas


def detectar_porta() -> Optional[str]:
    candidatas = [p for p in listar_portas() if p["arduino"]]
    return candidatas[0]["porta"] if candidatas else None


class SerialLink(Link):
    tipo = "serial"

    def __init__(self, porta: Optional[str] = None) -> None:
        super().__init__()
        self.porta_fixa = porta
        self.porta: Optional[str] = porta
        self.ser = None

    @property
    def descricao(self) -> str:
        return f"serial {self.porta or '(procurando)'}"

    def abrir(self) -> None:
        import serial

        self.fechar()
        porta = self.porta_fixa or detectar_porta()
        if not porta:
            raise LinkError("nenhum Arduino encontrado. Rode `tl portas` e use `tl daemon --porta <PORTA>`.")
        self.porta = porta
        try:
            self.ser = serial.Serial(porta, protocol.BAUD, timeout=0.1, write_timeout=1.0)
        except (serial.SerialException, OSError) as e:
            self.ser = None
            raise LinkError(_explicar_erro_serial(porta, e))
        # O Uno reinicia quando a porta abre: espere o READY (até 4 s).
        fim = time.monotonic() + 4.0
        while time.monotonic() < fim:
            linha = self._ler_linha()
            if linha and linha.startswith("READY"):
                return
        # Algumas placas não reiniciam: tente um PING.
        try:
            if self.enviar(protocol.cmd_ping(), timeout=1.0) == "PONG":
                return
        except LinkError:
            pass
        self.fechar()
        raise LinkError(f"a placa em {porta} não respondeu. O firmware semaforo.ino está gravado?")

    def _ler_linha(self) -> Optional[str]:
        import serial

        try:
            dados = self.ser.readline()
        except (serial.SerialException, OSError) as e:
            raise LinkError(f"erro de leitura na porta {self.porta}: {e}")
        if not dados:
            return None
        linha = dados.decode("ascii", errors="replace").strip()
        if linha:
            self._log("<", linha)
        return linha or None

    def enviar(self, linha: str, timeout: float = 0.5) -> str:
        import serial

        if self.ser is None:
            raise LinkError("porta serial fechada")
        self._log(">", linha)
        try:
            self.ser.write((linha + "\n").encode("ascii"))
        except (serial.SerialException, OSError) as e:
            raise LinkError(f"erro de escrita na porta {self.porta}: {e}")
        fim = time.monotonic() + timeout
        while time.monotonic() < fim:
            resp = self._ler_linha()
            if resp is None:
                continue
            if resp.startswith("READY"):
                # A placa reiniciou no meio do caminho: o comando se perdeu.
                raise LinkError("a placa reiniciou")
            return resp
        raise LinkError(f"sem resposta da placa para {linha!r}")

    def fechar(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        if not self.porta_fixa:
            self.porta = None


def _explicar_erro_serial(porta: str, erro: Exception) -> str:
    texto = str(erro)
    baixo = texto.lower()
    if "permission" in baixo or "acesso negado" in baixo or "access is denied" in baixo:
        return (
            f"sem permissão para abrir {porta}. No Linux: `sudo usermod -aG dialout $USER` e faça login de novo. "
            f"No Windows: feche o Monitor Serial do Arduino IDE (a porta pode estar ocupada). ({texto})"
        )
    if "busy" in baixo or "ocupad" in baixo or "resource" in baixo:
        return f"a porta {porta} está ocupada. Feche o Arduino IDE / Monitor Serial e outro `tl daemon`. ({texto})"
    return f"não abriu {porta}: {texto}"
