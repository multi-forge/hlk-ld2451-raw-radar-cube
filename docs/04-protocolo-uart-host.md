# Protocolo UART host — LD2451 v1.03

Documentação oficial extraída de `ld2451_protocol.pdf` (v1.03), cruzada com a RE do
firmware.

## Configuração da porta

| Parâmetro | Valor | Origem |
|---|---|---|
| Baud rate | **1 000 000** (por omissão do `isd_config.ini`); 115200 no protocolo v1.03 | `isd_config.ini` vs PDF |
| Bits de dados | 8 | PDF |
| Paridade | nenhuma | PDF |
| Bits de paragem | 1 | PDF |
| Fluxo | nenhum | PDF |

Tabela de baudrates lida do firmware em `0x1E204BC` (8 × u32 LE):

```
1 → 115200    2 → 9600     3 → 19200    4 → 38400
5 → 57600     6 → 115200   7 → 230400   8 → 256000
```

## Formato dos comandos (host → módulo)

```
FD FC FB FA | LEN(u16 LE) | CMD(u16 LE) | PAYLOAD | 04 03 02 01
```

* `FD FC FB FA` — cabeçalho (4 bytes)
* `LEN` — `2 + len(PAYLOAD)`, little-endian
* `CMD` — identificador do comando, little-endian
* `PAYLOAD` — dados do comando
* `04 03 02 01` — cauda (4 bytes)

## Resposta (ACK)

```
CMD | 0x100
```

O ACK repete o `CMD` com o bit `0x100` setado.

## Relatório de alvos (módulo → host)

```
F4 F3 F2 F1 | LEN | ALARM | COUNT | [alvo × 5 bytes] | F8 F7 F6 F5
```

* `LEN` — `2 + 5*COUNT`
* `ALARM` — 0 = normal, 1 = presença de alvo
* `COUNT` — número de alvos (0..5)
* cada alvo: `X (u16 LE)` | `Y (i8)` | `Velocidade (i16 LE)` | `Resolução (u8)`
  — a velocidade em cm/s, dividida por 10 para km/h

Construtor do frame no firmware: `0x1E108E0` / `0x1E108A0`
(`F4F3F2F1`, comprimento `n*5+2`, contagem em +6).

## Tabela de despacho de comandos (14 entradas, `0x1E21A34`)

Formato: `{ cmd(u32), handler(u32) }`, 8 bytes por entrada.

| idx | cmd | handler | função |
|---|---|---|---|
| 0 | `0x00FF` | `0x1E10BA6` | `UartProtocolCmdStartCfg` — entrar em modo de configuração |
| 1 | `0x00FE` | `0x1E10BD6` | `UartProtocolCmdEndCfg` — sair do modo de configuração |
| 2 | `0x00A0` | `0x1E10C06` | `UartProtocolCmdGetRadarBaseParam` |
| 3 | `0x00A1` | `0x1E10C58` | `UartProtocolCmdSetRadarBaseParam` |
| 4 | `0x00A2` | `0x1E10F4E` | `UartProtocolCmdGetRadarTrigParam` |
| 5 | `0x00A3` | `0x1E10FDA` | `UartProtocolCmdSetRadarTrigParam` |
| 6 | `0x00A4` | `0x1E11012` | `UartProtocolCmdOutIoPolarityGet` |
| 7 | `0x00A5` | `0x1E1107C` | `UartProtocolCmdOutIoPolaritySet` |
| 8 | `0x0012` | `0x1E110FC` | `UartProtocolCmdRestore` (AlgoParamInit) |
| 9 | `0x0002` | `0x1E111EC` | `UartProtocolCmdGetVersion` |
| 10 | `0x0013` | `0x1E11270` | `UartProtocolCmdGetMac` |
| 11 | `0x0003` | `0x1E112B2` | `UartProtocolCmdBoot` (reiniciar) |
| 12 | `0x00A6` | `0x1E11300` | `UartProtocolCmdBleSW` |
| 13 | `0x00A7` | `0x1E1136A` | `UartProtocolCmdBaudrate` / leitura de registador |

⚠️ **A tabela está cheia (14/14)** — não há slot livre para injetar um comando novo.
Ver [`06-patch-de-firmware.md`](06-patch-de-firmware.md) para a estratégia de hook.

## ★ Não existe engineering mode

O protocolo v1.03 **não** tem comandos de engineering mode (`0x62`/`0x63`). O snippet
`serral_ld24xx.be` que circula na comunidade refere-se ao LD2450/LD2410, não ao LD2451.

→ A via de dados brutos **tem** de ser a captura de hardware (Via A) ou o patch (Via B).

## Cliente pronto

`research/` e a sessão anterior produziram um cliente pyserial independente do app da
Hi-Link: `hlk2451_client.py`. Utilização:

```bash
python3 hlk2451_client.py --port /dev/ttyUSB0 --baud 115200 get-version
```

Comandos suportados: `start-cfg`, `end-cfg`, `get-version`, `set-baudrate`, `restore`,
`boot`, `blesw`, `get-mac`, `get-base`, `set-base`, `get-trig`, `set-trig`, `pol-set`,
`pol-get`.

## Parsing do buffer de recepção host

No loop de `app_radar` (`0x1E16B3E`):

* header `FD FC FB FA` e tail `04 03 02 01` são detectados no buffer `ctx+828`
* comando em `r4+6`, payload em `r4+7`
* strings de debug: `"cmd %02x"`, `"cmd handle err"`, `" link err"`, `"clk:%d cnt:%d\r\n"`
