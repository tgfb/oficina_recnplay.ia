// semaforo.ino - firmware da oficina "agente de IA controla um semáforo"
//
// Protocolo v1 (115200 baud, linhas terminadas em '\n'):
//   (no boot)          -> READY semaforo v1
//   PING               -> PONG
//   L R | L Y | L G | L O -> OK L <x>   (acende um LED; O = todos apagados)
//   B                  -> OK B          (amarelo piscante)
//   S?                 -> S <a> <b>     (potenciômetros A0 e A1, 0-1023)
//   outro              -> ERR <mensagem>
//
// Watchdog: sem nenhum comando por 3 s, o amarelo pisca (daemon parou ou cabo solto).
// O próximo comando válido restaura o LED anterior.
//
// Este firmware NÃO tem regras de segurança: elas ficam no daemon (tl daemon).
//
// Ligações (Arduino Uno):
//   D11 -> resistor 220 ohm -> LED vermelho -> GND
//   D10 -> resistor 220 ohm -> LED amarelo  -> GND
//   D9  -> resistor 220 ohm -> LED verde    -> GND
//   Potenciômetro A: pontas em 5V e GND, pino do meio em A0
//   Potenciômetro B: pontas em 5V e GND, pino do meio em A1

const int PIN_VERMELHO = 11;
const int PIN_AMARELO = 10;
const int PIN_VERDE = 9;
const int PIN_POT_A = A0;
const int PIN_POT_B = A1;

const unsigned long WATCHDOG_MS = 3000;
const unsigned long PISCA_MS = 500;
const int TAM_LINHA = 32;

char linha[TAM_LINHA];
int tamLinha = 0;
bool linhaLonga = false;

char ledAtual = 'O';        // R, Y, G, O ou B (piscante pedido pelo PC)
bool watchdogAtivo = false;
unsigned long ultimoComando = 0;

void aplicarLeds(bool vermelho, bool amarelo, bool verde) {
  digitalWrite(PIN_VERMELHO, vermelho ? HIGH : LOW);
  digitalWrite(PIN_AMARELO, amarelo ? HIGH : LOW);
  digitalWrite(PIN_VERDE, verde ? HIGH : LOW);
}

void atualizarLeds() {
  if (watchdogAtivo || ledAtual == 'B') {
    bool aceso = (millis() / PISCA_MS) % 2 == 0;
    aplicarLeds(false, aceso, false);
    return;
  }
  aplicarLeds(ledAtual == 'R', ledAtual == 'Y', ledAtual == 'G');
}

void tratarComando(char *cmd) {
  ultimoComando = millis();
  watchdogAtivo = false;

  if (strcmp(cmd, "PING") == 0) {
    Serial.println(F("PONG"));
  } else if (strcmp(cmd, "S?") == 0) {
    int a = analogRead(PIN_POT_A);
    int b = analogRead(PIN_POT_B);
    Serial.print(F("S "));
    Serial.print(a);
    Serial.print(' ');
    Serial.println(b);
  } else if (strcmp(cmd, "B") == 0) {
    ledAtual = 'B';
    Serial.println(F("OK B"));
  } else if (cmd[0] == 'L' && cmd[1] == ' ' && cmd[3] == '\0' &&
             (cmd[2] == 'R' || cmd[2] == 'Y' || cmd[2] == 'G' || cmd[2] == 'O')) {
    ledAtual = cmd[2];
    Serial.print(F("OK L "));
    Serial.println(cmd[2]);
  } else {
    Serial.println(F("ERR comando desconhecido"));
  }
}

void lerSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (linhaLonga) {
        Serial.println(F("ERR linha longa"));
      } else if (tamLinha > 0) {
        linha[tamLinha] = '\0';
        tratarComando(linha);
      }
      tamLinha = 0;
      linhaLonga = false;
      continue;
    }
    if (tamLinha < TAM_LINHA - 1) {
      linha[tamLinha++] = c;
    } else {
      linhaLonga = true;
    }
  }
}

void setup() {
  pinMode(PIN_VERMELHO, OUTPUT);
  pinMode(PIN_AMARELO, OUTPUT);
  pinMode(PIN_VERDE, OUTPUT);
  Serial.begin(115200);

  // Teste rápido dos LEDs no boot: vermelho, amarelo, verde.
  aplicarLeds(true, false, false);
  delay(200);
  aplicarLeds(false, true, false);
  delay(200);
  aplicarLeds(false, false, true);
  delay(200);
  aplicarLeds(false, false, false);

  ultimoComando = millis();
  Serial.println(F("READY semaforo v1"));
}

void loop() {
  lerSerial();
  if (!watchdogAtivo && millis() - ultimoComando > WATCHDOG_MS) {
    watchdogAtivo = true;
  }
  atualizarLeds();
}
