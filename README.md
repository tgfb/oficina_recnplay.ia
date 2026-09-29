# Oficina Rec'n'Play: um agente de IA controla um semáforo

Nesta oficina você liga um **agente de IA** (opencode + CENTOPEIA, modelo local no CESAR) a um
**semáforo Arduino**. O agente controla o semáforo por meio de uma CLI Python, o `tl`.

```
opencode ──bash "tl ..."──▶ tl (CLI) ──HTTP localhost:8765──▶ tl daemon ──serial──▶ Arduino Uno
```

- O **daemon** é o único dono da porta serial. Ele tem as regras de segurança, as fases,
  o modo política, o trânsito simulado e o placar.
- A **CLI `tl`** fala com o daemon. O agente chama o `tl` pela ferramenta bash.
- **`tl watch`** mostra o cruzamento no terminal. **`tl raw`** mostra a serial.
- **`tl daemon --sim`** simula a placa (sem hardware).

**Comece pelo [guia do aluno](docs/guia-aluno.md).**

## Início rápido

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -e .

tl daemon --sim                    # terminal 1 (com a placa: tl daemon)
tl watch                           # terminal 2
tl status                          # terminal 3
```

Com o agente (defina `CLUSTER_BASE_URL`, `CLUSTER_API_KEY` e `CLUSTER_MODEL` antes):

```bash
python scripts/testar_modelo.py    # o modelo chama ferramentas?
opencode                           # na pasta do projeto, com o venv ativo
```

## Conteúdo

| Caminho | O quê |
|---|---|
| `docs/guia-aluno.md` | guia do aluno: instalação, primeiros comandos, exercícios |
| `docs/fiacao.md` | ligações e diagrama do circuito |
| `firmware/semaforo/semaforo.ino` | firmware do Arduino Uno (você grava na placa) |
| `semaforo/` | pacote Python: daemon, CLI `tl`, simulador, painel |
| `opencode.json` | provedor CENTOPEIA (variáveis de ambiente) + permissões do agente |
| `AGENTS.md` | instruções do agente (você completa nas etapas 1 e 2) |
| `agente_loop.py` | laço autônomo com TODOs (etapa 3) |
| `scripts/testar_modelo.py` | teste rápido: o modelo usa ferramentas? |

## Licença

MIT. Veja [LICENSE](LICENSE).
