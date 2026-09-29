# Fiação do semáforo (Arduino Uno)

## Material

| Qtde | Item |
|---|---|
| 1 | Arduino Uno (original ou clone com CH340) + cabo USB **de dados** |
| 1 | Protoboard |
| 3 | LEDs: vermelho, amarelo, verde |
| 3 | Resistores de 220 Ω (vermelho-vermelho-marrom) |
| 2 | Potenciômetros de 10 kΩ (sensores de trânsito das direções A e B) |
| ~10 | Jumpers macho-macho |

## Tabela de ligações

| Arduino | Vai para | Observação |
|---|---|---|
| D11 | resistor 220 Ω → perna **longa** (+) do LED **vermelho** | |
| D10 | resistor 220 Ω → perna longa do LED **amarelo** | |
| D9 | resistor 220 Ω → perna longa do LED **verde** | |
| GND | perna **curta** (−) dos 3 LEDs | use a linha azul (−) da protoboard |
| 5V | uma ponta de cada potenciômetro | linha vermelha (+) da protoboard |
| GND | a outra ponta de cada potenciômetro | |
| A0 | pino do **meio** do potenciômetro **A** | sensor da direção A |
| A1 | pino do **meio** do potenciômetro **B** | sensor da direção B |

## Diagrama

LEDs (cada um com seu resistor):

```
  Arduino                                   protoboard
  D11 ────[220Ω]────(+) LED vermelho (−)────┐
  D10 ────[220Ω]────(+) LED amarelo  (−)────┤
  D9  ────[220Ω]────(+) LED verde    (−)────┤
  GND ──────────────────────────────────────┘   (linha − da protoboard)
```

Potenciômetros (3 pinos: ponta, meio, ponta):

```
                 pot A                          pot B
          ┌───────────────┐              ┌───────────────┐
          │  1    2    3  │              │  1    2    3  │
          └──┬────┬────┬──┘              └──┬────┬────┬──┘
             │    │    │                    │    │    │
            5V   A0   GND                  5V   A1   GND
```

Pino do meio do pot A → A0. Pino do meio do pot B → A1. As pontas vão em 5V e GND
(a ordem das pontas só inverte o sentido do giro).

## O que é o quê

- Os 3 LEDs são o semáforo **físico** da direção **A**.
- A direção **B** é **virtual**: ela aparece no `tl watch`. Ela é sempre o "contrário" seguro de A.
- Cada potenciômetro simula um sensor de trânsito: girar para o máximo = 0,5 carro por segundo
  chegando naquela direção.

## Teste rápido

1. Grave o firmware (veja o guia do aluno). No boot, os LEDs acendem em sequência: vermelho, amarelo, verde.
2. Depois de 3 s sem o daemon, o amarelo pisca. Isso é normal: é o watchdog ("sem controle").
3. Rode `tl daemon` e `tl sensores`. Gire cada potenciômetro: o valor precisa ir de ~0 a ~1023.

Se um LED não acende: confira a perna longa (+) do lado do resistor, e o GND.
