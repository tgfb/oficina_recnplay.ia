# Guia do aluno — Um agente de IA controla um semáforo

Nesta oficina você liga um **agente de IA** (opencode + CENTOPEIA, modelo local no CESAR) a um
**semáforo de verdade** (Arduino Uno). O agente usa uma ferramenta simples: o comando `tl`.

```
opencode (CENTOPEIA)
   │  ferramenta bash: "tl fase A-amarelo"
   ▼
tl (CLI)  ──HTTP localhost:8765──▶  tl daemon  ──serial 115200──▶  Arduino (semaforo.ino)
                                     ├─ regras de segurança
                                     ├─ fases e modo política
                                     └─ trânsito simulado e placar
```

Cada camada pode ser vista: `tl raw` mostra a serial, o terminal do `tl daemon` mostra cada
comando que chega, e `tl watch` mostra o cruzamento.

---

## 1. Montagem

Monte o circuito de [fiacao.md](fiacao.md): 3 LEDs (D11 vermelho, D10 amarelo, D9 verde) e
2 potenciômetros (A0 = sensor da direção A, A1 = sensor da direção B).

## 2. Gravar o firmware

O firmware está em `firmware/semaforo/semaforo.ino`.

**Arduino IDE**
1. Abra `firmware/semaforo/semaforo.ino`.
2. *Ferramentas → Placa → Arduino Uno*. *Ferramentas → Porta →* a porta da placa.
3. Clique em *Carregar* (seta →).
4. **Feche o Monitor Serial** depois (ele ocupa a porta e o daemon não consegue abrir).

**arduino-cli** (alternativa)
```bash
arduino-cli core install arduino:avr
arduino-cli compile --fqbn arduino:avr:uno firmware/semaforo
arduino-cli upload  --fqbn arduino:avr:uno -p <PORTA> firmware/semaforo
```

No boot os LEDs acendem em sequência. Depois de 3 s sem daemon, o amarelo pisca (watchdog).

## 3. Instalar o software

Precisa de Python 3.9 ou mais novo. Na pasta do projeto:

**Windows (PowerShell)**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```
Se o PowerShell bloquear o script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.
No `cmd.exe`, use `.venv\Scripts\activate.bat`.

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Confira: `tl doctor`.

**Drivers e permissões**
- Clone com chip **CH340** (Windows e macOS): instale o driver CH340 se a porta não aparecer.
- **Linux**: `sudo usermod -aG dialout $USER`, depois saia da sessão e entre de novo.
- Cabo USB: alguns cabos só carregam. Se nenhuma porta aparece, troque o cabo.

> **Importante:** ative o venv em **todo** terminal novo (`tl` só existe dentro do venv).

## 4. Primeiros comandos (sem IA)

Abra 3 terminais, com o venv ativo em cada um.

| Terminal | Comando | Para quê |
|---|---|---|
| 1 | `tl daemon` | dono da porta serial. Deixe aberto. Sem placa: `tl daemon --sim` |
| 2 | `tl watch` | painel com os dois semáforos, filas, placar e comandos |
| 3 | os comandos abaixo | |

```bash
tl portas            # lista as portas e marca o Arduino
tl status            # estado atual
tl sensores          # gire os potenciômetros e rode de novo
tl fase A-verde
tl fase A-amarelo    # rápido demais? veja o ERRO
tl raw               # veja as linhas da serial (Ctrl+C sai)
tl raw --enviar "S?" # fale direto com a placa
```

Se a porta não for encontrada: `tl daemon --porta COM3` (Windows) ou `--porta /dev/ttyACM0` (Linux)
ou `--porta /dev/cu.usbmodem...` (macOS).

### O cruzamento

```
A-verde → A-amarelo → vermelho-total → B-verde → B-amarelo → vermelho-total → A-verde ...
```

- O LED físico mostra a direção **A**. A direção **B** é virtual (aparece no `tl watch`).
- Tempos mínimos: verde **5 s**, amarelo **3 s**, vermelho-total **1 s**.
- Com a segurança ligada, o daemon **rejeita** trocas fora da ordem ou antes do tempo
  (`ERRO: ...`, código de saída 2). Cada rejeição conta como **violação** no placar.

### O placar

- Os potenciômetros definem quantos carros chegam (máximo 0,5 carro/s). No verde, passa 1 carro/s.
- **Pontuação = espera total (carro·s) + 60 por violação.** Menor é melhor.
- `tl placar` mostra o placar. `tl placar --zerar` zera.

## 5. opencode e o CENTOPEIA

1. Instale o opencode (uma das opções):
   - macOS / Linux: `curl -fsSL https://opencode.ai/install | bash`
   - qualquer sistema com Node.js: `npm install -g opencode-ai`
   - macOS com Homebrew: `brew install opencode`
2. Defina as variáveis com os valores que o instrutor passar:

   **macOS / Linux**
   ```bash
   export CLUSTER_BASE_URL="https://.../v1"
   export CLUSTER_API_KEY="..."
   export CLUSTER_MODEL="..."
   ```
   **Windows (PowerShell)**
   ```powershell
   $env:CLUSTER_BASE_URL = "https://.../v1"
   $env:CLUSTER_API_KEY = "..."
   $env:CLUSTER_MODEL = "..."
   ```
3. Teste se o modelo usa ferramentas (o daemon precisa estar rodando):
   ```bash
   python scripts/testar_modelo.py
   ```
   Ele pede ao agente para rodar `tl status` e confere no daemon se a chamada chegou.
4. Abra o opencode **na pasta do projeto, com o venv ativo**: `opencode`.
   Pergunte: *"como está o trânsito agora?"*. Olhe o terminal do daemon: a chamada `tl status` aparece.

O `opencode.json` do projeto só deixa o agente rodar `tl status`, `tl historico`, `tl sensores`,
`tl fase`, `tl modo`, `tl politica` e `tl placar`. Ele não pode editar arquivos, desligar a
segurança, nem rodar outros comandos.

---

## 6. Etapa 1 — Modo direto: o agente troca cada fase

O agente lê o `AGENTS.md` da pasta do projeto como instruções. Ele está quase vazio.
**Sua tarefa: escrever as instruções do controlador.**

Responda no texto do `AGENTS.md`:
- Qual é a ordem das fases? Quanto tempo cada uma precisa durar, no mínimo?
- Como o agente decide **quando** trocar? (filas? fluxo dos sensores? tempo no verde?)
- O que o agente faz quando um comando dá `ERRO`?
- Como usar `tl status --json` (campos `proxima_fase_legal`, `pode_mudar_em_s`, `filas`)?
- E `tl historico --segundos 30`?
- Como a resposta deve ser? (curta, com o motivo da decisão?)

Teste no opencode: *"controle o cruzamento pelos próximos 2 minutos"*. Gire os potenciômetros.

Observe:
- Quanto tempo o agente leva entre dois comandos? (veja as horas no `tl watch`)
- Quantas violações? O agente aprende com a mensagem de erro?
- O instrutor vai **desligar a segurança** por um momento. O que acontece?

## 7. Etapa 2 — Modo política: o daemon roda o ciclo

O LLM demora segundos para responder. Um semáforo precisa de decisões rápidas e sem erro.
Então: **tire o LLM do laço rápido.** O daemon roda o ciclo sozinho, e o agente só escolhe
os tempos de verde.

```bash
tl modo politica
tl politica --verde-a 20 --verde-b 10    # amarelo 3 s e vermelho-total 1 s são fixos
tl modo direto                           # volta ao modo da etapa 1
```

No modo política, `tl fase` é rejeitado.

**Sua tarefa:** reescreva o `AGENTS.md` para o modo política.
- Como o agente escolhe `--verde-a` e `--verde-b`? (proporção dos fluxos? das filas?)
- Qual é o limite mínimo e máximo razoável?
- Quando **não** mudar nada?

Teste: *"ajuste a política para o trânsito atual"*. Mude os potenciômetros e peça de novo.

## 8. Etapa 3 — Laço autônomo e desafio

Agora ninguém conversa com o agente: um programa o acorda de tempos em tempos.

1. Abra `agente_loop.py` e complete os TODOs (intervalo, pedido, estado no pedido, falhas).
2. Rode: `python agente_loop.py`.
3. Em outro terminal, rode o desafio: `tl desafio --duracao 180 --perfil pico`.
   - O desafio zera o placar e usa um trânsito **fixo** (ignora os potenciômetros),
     igual para todos os alunos. Assim as pontuações são comparáveis.
   - No fim, ele mostra a pontuação. **Escreva no quadro.**
4. Melhore o `AGENTS.md` e o laço, e rode o desafio de novo.

Perfis: `pico` (A cheio, depois equilibrado, depois B cheio), `equilibrado`, `leve`.

---

## Referência dos comandos

| Comando | O que faz |
|---|---|
| `tl daemon [--sim] [--porta P] [-v]` | inicia o daemon (um por computador) |
| `tl portas` | lista as portas seriais |
| `tl doctor` | confere a instalação |
| `tl status [--json]` | fase, sensores, filas, placar |
| `tl historico [--segundos 30] [--json]` | eventos e amostras recentes |
| `tl sensores [--json]` | potenciômetros e fluxo |
| `tl fase <FASE>` | troca a fase (modo direto) |
| `tl modo direto\|politica` | escolhe o modo |
| `tl politica --verde-a S --verde-b S` | tempos de verde do modo política |
| `tl placar [--zerar] [--json]` | placar |
| `tl desafio [--duracao 180] [--perfil pico]` | desafio com trânsito fixo |
| `tl watch` | painel ao vivo |
| `tl raw [--enviar LINHA] [--com-sensores]` | serial ao vivo |
| `tl seguranca [ligar\|desligar]` | segurança (instrutor) |
| `tl sim --a N --b N` / `tl sim --auto` | potenciômetros do simulador |

Códigos de saída do `tl`: `0` ok, `1` erro, `2` rejeitado (segurança ou modo), `3` daemon não está rodando.

## Problemas comuns

| Sintoma | Solução |
|---|---|
| `tl: command not found` / `'tl' não é reconhecido` | ative o venv |
| `ERRO: o daemon não está rodando` | rode `tl daemon` (ou `--sim`) em outro terminal |
| `nenhum Arduino encontrado` | `tl portas`; troque o cabo; instale o driver CH340; use `--porta` |
| `sem permissão para abrir /dev/ttyACM0` | Linux: grupo `dialout` (veja a seção 3) |
| `a porta está ocupada` | feche o Monitor Serial do Arduino IDE e outro `tl daemon` |
| `porta HTTP 8765 já em uso` | já existe um `tl daemon` rodando |
| amarelo piscando | o daemon parou ou o cabo soltou (watchdog) |
| o agente diz que não pode rodar `tl` | abra o `opencode` na pasta do projeto, com o venv ativo |
| `testar_modelo.py` FALHOU | mostre a saída ao instrutor |
