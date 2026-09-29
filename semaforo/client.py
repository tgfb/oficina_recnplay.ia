"""Cliente HTTP pequeno (só biblioteca padrão) para falar com o `tl daemon`."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import quote, urlencode

from . import PORTA_HTTP_PADRAO


class DaemonOffline(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, dados: dict) -> None:
        super().__init__(dados.get("erro", f"HTTP {status}"))
        self.status = status
        self.dados = dados

    @property
    def mensagem(self) -> str:
        return self.dados.get("erro", f"HTTP {self.status}")


def url_padrao() -> str:
    return os.environ.get("TL_URL", f"http://127.0.0.1:{PORTA_HTTP_PADRAO}").rstrip("/")


class Client:
    def __init__(self, url: Optional[str] = None, comando: str = "", timeout: float = 5.0) -> None:
        self.url = (url or url_padrao()).rstrip("/")
        # Enviado no cabeçalho: o daemon registra a chamada no log (`tl watch` não envia).
        self.comando = comando
        self.timeout = timeout

    def _pedir(self, metodo: str, caminho: str, corpo: Optional[dict] = None) -> dict:
        dados = None
        cabecalhos = {"Accept": "application/json"}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cabecalhos["Content-Type"] = "application/json"
        if self.comando:
            cabecalhos["X-TL-Comando"] = quote(self.comando)
        req = urllib.request.Request(self.url + caminho, data=dados, headers=cabecalhos, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                info = json.loads(e.read().decode("utf-8"))
            except ValueError:
                info = {"erro": f"HTTP {e.code}"}
            raise ApiError(e.code, info)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise DaemonOffline(str(e))

    def get(self, caminho: str, **params) -> dict:
        if params:
            caminho += "?" + urlencode(params)
        return self._pedir("GET", caminho)

    def post(self, caminho: str, corpo: Optional[dict] = None) -> dict:
        return self._pedir("POST", caminho, corpo or {})
