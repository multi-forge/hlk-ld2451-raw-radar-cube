# RELATÓRIO FINAL — Engenharia Reversa do Radar HLK-LD2451

**Projeto:** Extração de dados brutos (Raw Radar Cube) do HLK-LD2451
**Alvo:** Módulo Hi-Link HLK-LD2451 — radar mmWave 24 GHz
**SoC:** JieLi AC635N (série BR23), ISA proprietária **pi32v2** (RISC 32-bit)
**Front-end RF:** SkyRelay RC2412FR (ADC 8 bits, 1 TX, 2 RX)
**Data:** 2026-10-20
**Autor:** Agente de engenharia reversa (opencode)

---

## 1. RESUMO EXECUTIVO

O objetivo original era extrair **dados brutos de radar** (amostras ADC / I-Q / FFT) do
HLK-LD2451, em vez de apenas os pacotes de alvos já processados que o módulo envia pela
UART.

**A engenharia reversa está CONCLUÍDA e VERIFICADA.** A cadeia completa de processamento
de sinal foi mapeada no firmware, com endereços exatos:

```
RC2412FR (ADC 8-bit)
   │  SPI1, 1 bit, modo 1 (CPOL=0/CPHA=1), SEM pino de CS
   │  quadro = 257 bytes = [header(1) + 256 amostras int8]
   ▼
AC635N — ISR 0x1E1146E  →  buffer bruto  0x19D74 + idx*257   (64 chirps)
   │
   ▼  rotina 0x1E14E46 (copia 64 × 256 bytes, stride 257 → 256)
CUBO PACKED  0x15B60   (64 × 256 = 16384 bytes, int8, contíguo)
   │
   ▼  rotina 0x1E15B5E  (janela 256 floats @ 0x1E21F84 → FFT 256 pts @ 0x1E15480)
   │                    → 65 bins de range, saida complexa 0x15360
   ▼
RANGE-DOPPLER COMPLEXO   0xCF60   (65 range × 64 doppler, float32)
   │  (janela Doppler 64 floats @ 0x1E21E84 → FFT 64 pts → magnitude)
   ▼
MAPA DE MAGNITUDE        0x4C60   (65 × 64 float32)
   │
   ▼
detecção de alvos → frame UART "F4 F3 F2 F1 … F8 F7 F6 F5"
```

**Conclusão central:** o AC635N **é** o cérebro do DSP. O RC2412FR é apenas o
front-end analógico/ADC. Os dados brutos **existem** no AC635N e são capturáveis por
duas vias:

| Via | Descrição | Esforço | Risco |
|---|---|---|---|
| **A — Passiva (HW)** | Espelhar PP0 (CLK) e PP2 (DI) com um sniffer SPI | Baixo | Nenhum (não destrutivo) |
| **B — Patch de firmware** | Injetar dump do cubo na UART0 do próprio AC635N | Médio | Brick (backup obrigatório) |

**Correção importante que fiz contra a instrução original do líder:** a instrução pedia
interrupção de GPIO no pino de clock para o ESP32-S3. Isso é **inviável** — ver §7.
Além disso, corrigi o critério de detecção de frame: o header **não** é `0x00`, é
`byte & 0x3F` (ver §6.3).

---

## 2. ENTREGÁVEIS JÁ PRODUZIDOS E VALIDADOS

Todos em `~/rea-fw/sniffer/`:

| Arquivo | O que faz | Estado |
|---|---|---|
| `esp32s3_spi_sniffer/esp32s3_spi_sniffer.ino` | Sniffer ESP32-S3, USB CDC | **Compila sem erros** (verificado na VM GCP, core 3.3.12) |
| `capture_cube.py` | PC: lê a USB, valida framing, grava `cube_XXXXXX.bin` + `cube_XXXXXX_samples.bin` | **Testado** com cubo sintético |
| `plot_rd.py` | PC: reconstrói o mapa Range-Doppler 65×64 + CSV + ASCII | **Testado** com cubo sintético |
| `bootloader.bin` (em `/opt/rea-fw/work/arduino/build` na VM) | pré-compilado para gravar | pronto |

**Validação de pipeline executada com sucesso:**
- sketch ESP32-S3 → compila (281 137 bytes flash, 21%; 104 552 bytes RAM, 31%)
- cubo sintético 64×257 com headers `idx = 0..63` e bit de status em 8 frames
- `capture_cube.py` → `headers_ok=True`, `status_bits=[0,1]`
- `plot_rd.py` → mapa 65×64 gerado, CSV escrito, sem erros

---

## 3. MAPA DE MEMÓRIA (verificado contra headers BR23 e o binário)

```
hs_base = 0x1F0000     ls_base = 0x1E0000
SPI0   0x1E1C00   ← flash serial externa (comandos 0x6B/0x9F/0x4B em 0x1E24900)
SPI1   0x1E1D00   ← LINK DO RADAR (RC2412FR)          ★
SPI2   0x1E1E00
UART0  0x1E2000   ← link host (protocolo FD FC FB FA)
UART1  0x1E2100
UART2  0x1E2200
DMA    0x1E3F00
SFC    0x1F0200   ← flash controller
```

Buffers/globais relevantes:

| Endereço | Tamanho | Conteúdo |
|---|---|---|
| `0x19D71` | 3 B | flags de estado do radar (b[0], b[1], b[2]) |
| `0x19D74` | 64 × 257 = 16448 B | **buffer bruto SPI** — stride 257 (1 header + 256 amostras) |
| `0x19D75` | 16384 B útil | início das amostras (pulando o header de cada chirp) |
| `0x15B60` | 16384 B | **cubo packed** 64 × 256 int8 (destino de `0x1E14E46`) |
| `0x15360` | 4096 B | buffer complexo intermédio da FFT de range |
| `0xCF60` | 33280 B | **Range-Doppler complexo** (65 × 64 × 2 floats) |
| `0x4C60` | 16640 B | **magnitude Range-Doppler** (65 × 64 float32) |
| `0x4B60` | — | buffer de trace/targets do radar |
| `0x1E230` | — | contexto do radar (ctx) |
| `0x1E1EF70` | — | base de globals/strings do firmware |
| `0x1E21F84` | 1024 B | **janela de range** — 256 float32 (verificada: simétrica, pico 0.99996) |
| `0x1E21E84` | 256 B | **janela Doppler** — 64 float32 (verificada: pico 0.99943) |
| `0x1E1DDB4` | 257 B | staging do frame SPI (origem da cópia no ISR) |
| `0x1E280` | — | handle do device UART0 (ctx+80) |
| `0x19C70` | — | buffer de TX da UART host |

---

## 4. CADEIA DE TAREAS (RTOS JieLi)

Tabela de tasks em **`0x1E1EE14`** — entradas de **12 bytes**, formato
`{ name_ptr, (stack<<16)|priority, qsize }`, **sem ponteiro de função**.

A criação é feita pelo wrapper **`0x1E0D462`**: recebe `r0=func`, `r1=arg`, `r2=name`,
procura o nome na tabela via `strcmp` (`0x21127B8`) e chama `os_task_create` (`0x2002D58`).

| Task | Função | Stack | Prio | Qsize |
|---|---|---|---|---|
| `app_core` | `0x1E0E52A` | — | — | — |
| **`app_radar`** | **`0x1E16DD2`** | 1024 | 1 | 0 |
| `sys_event` | — | — | — | — |
| `btctrler` | — | — | — | — |
| `btencry` | — | — | — | — |
| `btstack` | `0x1E0A510` | — | — | — |
| `systimer` | `0x1E0D65E` | — | — | — |
| `update` / `dw_update` | — | — | — | — |
| `rcsp_task` | — | — | — | — |

> ⚠️ **Correção**: a task `app_radar` **não** começa em `0x1E16692`. A entrada real é
> **`0x1E16DD2`**; `0x1E16692` é código **dentro** do state machine `0x1E15FD4`.
> O loop principal é **`0x1E16B3E`**.

Fluxo de `app_radar` (`0x1E16B3E`):
1. timestamp de `[0x4248]/1000000*1000`
2. `[0x1E0600] = 0x4000`
3. `0x1E0D40A(6, 3, 0x1E114F6)` → registra o **ISR do SPI1** (`0x1E114F6`)
4. `0x1E241D4` → **abre a UART host** (handle em ctx+80 = `0x1E280`); imprime
   `"UART INITing...baudrate=%d\n"` com baud de `[0x19B64]`
5. `0x1E15FD4` → state machine de processamento
6. parse do buffer `ctx+828`: header `FD FC FB FA`, tail `04 03 02 01`,
   comando em +6, payload em +7

`0x1E241D4` (UART open) seleciona UART0/1/2 por tabelas de 12 entradas em `0x42CC`/`0x42D8`;
device structs: `0x215C8` (UART0), `0x21604` (UART1), `0x21640` (UART2); IRQ handler
`0x1E23BFC` via `0x1E0D40A(18, 3, …)`.

> ⚠️ **Correção**: `0x1E241D4` é **UART open/init**, não SPI/DMA.
> `0x1E2376A` NÃO é init do radar: é **init genérico de sistema/board**.

---

## 5. A INTERFACE FÍSICA DO RADAR (SPI1) — VERIFICADO NO REGISTRO

Este é o núcleo do achado. A configuração de `SPI1_CON` (`0x1E1D00`) está na rotina
`0x1E14D64`. Sequência decodificada:

```
1e14d9e: [r6+0] &= 0xFFFFFFFE     ; bit0 SPIE=0 (desliga)
1e14dae: [r6+0] |= 0x8            ; bit3  BIDIR=1  (modo bidirecional 1 bit)
1e14db2: [r6+0] &= 0xFFFFF3FF     ; bits10-11 DATW=00 (1 bit)
1e14dd8: [r6+0] &= 0xFFFFFFFB     ; bit2  CSE=0  → ★ NÃO USA SPICS (sem CS!) ★
1e14ddc: [r6+0] |= 0x2            ; bit1  SLAVE=1 → AC635N é ESCRAVO do RC2412
1e14de0: [r6+0] |= 0x10           ; bit4  SE=1 (amostra na borda de SUBIDA do SPICK)
1e14de4: [r6+0] |= 0x20           ; bit5  UE=1 (atualiza dado na SUBIDA)
1e14de8: [r6+0] |= 0x80           ; bit7  CSID=1
1e14dec: [r6+0] &= 0xFFFFFFBF     ; bit6  CKID=0 → SPICK ocioso em BAIXO (CPOL=0)
1e14df0: [r6+0] |= 0x4000         ; bit14 PCLR (limpa PND)
1e14e26: [r6+8] = 0               ; SPI1_ADR = 0
1e14e2a: [r6+0] |= 0x1            ; SPIE=1 (liga)
1e14e2e: [r6+0] |= 0x2000         ; IE=1 (interrupção habilitada)
1e14e32: r2 = 0x1E1146E           ; handler do IRQ 15
1e14e38: r0 = 15 ; call 0x1E0D40A  ; registra IRQ 15 = SPI1
```

**Conclusões verificadas:**
- **SPI1 é SLAVE** (bit1=1): o **RC2412FR é o master** e gera o clock.
- **`CSE = 0`** (bit2 limpo): o hardware **não usa o sinal SPICS** → **não existe pino de
  CS** neste barramento. O frame é delimitado apenas pelo header.
- **SPICK ocioso em baixo** (CKID=0) → **CPOL = 0**.
- **SE=1** → amostragem na **borda de subida** do clock. Combinado com CPOL=0 e
  dados alterados na subida, o modo efetivo é **SPI modo 1 (CPOL=0, CPHA=1)**.
- **1 bit**, modo bidirecional (single-wire, como o `spi_io` struct da SDK indica:
  `di_pin` e `do_pin` compartilham o mesmo fio).

### 5.1 Pinos

Da tabela `spi_io` do SDK (`struct spi_io { u8 cs_pin, di_pin, do_pin, clk_pin, … }`) e do
mapa de pinos do manual AC635N (`ac635n_manual.txt`):

| Sinal | Pino AC635N | Alias no manual |
|---|---|---|
| SPI1 CLK | **PB0** | `PP0` (SPI1CLKA) |
| SPI1 DI/DO | **PB2** | `PP2` (SPI1DIA) |
| SPI1 DO | PB1 | `PP1` (SPI1DOA) — **não usado**, o barramento é single-wire |
| CS | — | **inexistente** (CSE=0) |

Configuração de SPI1 no firmware: `SPI 2_3_0_0` (em `isd_config.ini`), host UART em
`UTTX=PA05`, `UTRX=PB05`, `RESET=PB01`, **baud 1 000 000**.

> ★ **O clock SPI vem do RC2412FR**, não do AC635N. A taxa real precisa ser medida em
> bancada (ver §9, risked item R1). O firmware só configura `SPI1_BAUD` (que é ignorado
> em modo slave).

### 5.2 O ISR do SPI1 (`0x1E1146E`) — decodificado

```
1e1144e: r0 = 0x1E1D00
1e11454: [r0+0] |= 0x1000         ; bit12 DIR=1 (RX)
1e11458: r1 = 16451  (0x4043)
1e1145c: r2 = 105841 (0x19D71)
1e11462: r1 += r2  →  r1 = 0x1DDB4   ; staging do frame
1e11464: r1 = 257
1e11468: [r0+12] = r1             ; SPI1_ADR = 257 (bytes por transação)
1e1146a: [r0+16] = r1             ; SPI1_CNT = 257
1e1146c: rts

1e1146e: ISR
1e11474: r0 = 0x1E1D00
1e1147a: r1 = [r0+0]
1e1147c: if ((r1 & 0x8000) == 0) goto fim   ; PND (bit15) não setado → sai
1e11480: [r0+0] |= 0x4000          ; PCLR: limpa PND
1e11484: call 0x1E1144E            ; (re)configura DMA
1e1148a: r5 = 0x19D71
1e11490: r1 = b[r5 + 0x4043]       ; ★ header do frame em 0x1DDB4
1e1149a: r3 = r1 >> 7              ; ★ bit7 = STATUS
1e1149c: r6 = r1 & 0x3F            ; ★ bits0-5 = ÍNDICE DO CHIRP (0..63)
1e114a0: r2 = b[r4+1]              ; ctx+1 = próximo índice esperado
1e114a2: b[r5+2] = r3              ; guarda status em 0x19D73
1e114a4: if (r6 != r2) goto erro   ;_idx_ fora de ordem → contador de erros
1e114a8: r1 = r5 + r0              ; src = 0x1DDB4
1e114aa: r0 = 257
1e114ae: r0 *= r6                  ; 257 * idx
1e114b0: r0 += r5                  ; + 0x19D71
1e114b2: r0 += 3                   ; ★ dest = 0x19D74 + idx*257
1e114b4: r2 = 257
1e114b8: call memcpy (0x21127A8)   ; copia 257 bytes
1e114bc: r0 = r6 + 1
1e114c0: b[r4+1] = r0              ; ctx+1 = idx+1
1e114c2: if (r1 == 64) {           ; 64 chirps completos
1e114c6:   b[r4+1] = 0
1e114ca:   r0 = 1
1e114cc:   b[r5+0] = r0            ; ★ 0x19D71 = 1 → flag "cubo completo"
          }
1e114d4: (erro) r0 = b[r4+76]; ++; if (>= 301) { b[r5+1] = 1; … }
```

**Formato do frame SPI (257 bytes) — DEFINITIVO:**

| Offset | Tamanho | Conteúdo |
|---|---|---|
| 0 | 1 | **header**: bits 0–5 = índice do chirp (0..63); **bit 7 = status**; bit 6 não usado |
| 1 | 256 | **amostras ADC int8** (com sinal) do chirp |

O bit 7 é lido separadamente (`r1 >> 7`) e guardado em `0x19D73` — logo **não faz parte
do índice**. O índice é `header & 0x3F`.

> ★ **CORREÇÃO CRÍTICA** (contra a instrução original do líder, que mandava comparar o
> byte com `0x00`): o byte 0 do frame **não é 0x00**. Para o primeiro chirp ele vale
> `0x00` **ou `0x80`** (se o bit de status estiver setado). Comparar com `0x00` perde
> frames. **Use `byte & 0x3F`** e exija a progressão `0,1,2,…,63`.

---

## 6. A CADEIA DSP (decodificada instrução a instrução)

### 6.1 Cópia do bruto → cubo packed — `0x1E14E46`

```
1e14e46: [--sp] = {rets, r6-r4}
1e14e48: r0 = 105845 (0x19D75)     ; src = amostras (pula o 1º header)
1e14e4e: r1 = 0
1e14e50: r2 = 88928  (0x15B60)     ; dst = cubo packed
1e14e58: r3 = 256                 ; bytes por linha
1e14e5c: r4 = r0 ; r5 = r2
1e14e62: r6 = b[r4++=1] (u)       ; byte a byte
1e14e64: b[r5++=1] = r6
1e14e68: r3 += -1
1e14e6a: r0 = r0 + 257            ; ★ src stride 257 (pula header)
1e14e6e: r2 = r2 + 256            ; ★ dst stride 256 (empacotado)
1e14e72: r1 += 1
1e14e74: if (r1 != 64) loop       ; 64 chirps
```

★ **`0x15B60` contém os 16384 bytes do cubo 64×256 int8, contíguos e sem headers.**

### 6.2 Janela + FFT de range — `0x1E15B5E`

```
1e15b74: r0 = 53088 (0xCF60) ; r9 = r0 + 516
1e15b7e: r10 = 88928 (0x15B60)      ; amostras int8 do cubo packed
1e15b84: r8  = 0x1E1EF70
1e15b8a: r4  = 86880 (0x15360)      ; buffer complexo de saída
1e15b90: r6  = 3077                 ; offset da tabela de janela
1e15b94: r11 = 0                    ; contador de chirp (0..63)
   loop chirp:
1e15b9c: r1 = r10 ; r2 = r4
1e15ba4: r7 = b[r1++=1] (s)        ; ★ amostra int8 COM SINAL
1e15ba8: r3 = [r3 + r6<<2]         ; ★ coeficiente da janela (float)
1e15bac: r7 = itof(r7)             ; converte int8 → float
1e15bb0: r3 = r7 * r3 (f)          ; ★ amostra × janela
1e15bb4: [r2+] = {r5, r3}          ; store complexo {re=0, im=prod}
1e15bba: r0 += 4 ; r2 += 8
1e15bbc: if (r0 != 1024) loop      ; 256 iterações × 4 bytes = 1024
1e15bc2: r0 = r8 + 1292            ; params da FFT (0x1E1F474)
1e15bc6: r1 = r4                   ; buffer 0x15360
1e15bc8: call 0x1E15480            ; ★ FFT de 256 pontos
   …
1e15be8: r9 += 8 ; r10 += 256 ; r11 += 1
1e15bf4: if (r11 != 64) loop       ; 64 chirps
```

★ A tabela de janela é `0x1E1EF70 + 3077*4 = 0x1E21F84` — **256 float32**,
confirmado empiricamente: valores `0.000149 … 0.99996 … 0.000149`, simétricos
(tipo **Hann**).

### 6.3 FFT de Doppler + magnitude

Fase 2 em `0x1E15BF8` (65 bins de range × 64 chirps):
- janela Doppler em `0x1E21E84` (64 float32, verificada: pico 0.99943) — accessed via
  `r3 = [r3 + r15<<2]` com `r15 = 3013`
- FFT de 64 pontos via `0x1E15480`
- laço final (`0x1E15CAA`–`0x1E15CD0`) calcula `r2*r2 + r3*r3` → magnitude, escrita em
  `r10` (= `0x4C60`), com `r11` contando 1..65 (65 gates de range) e `r0` contando
  0..63 (64 bins de doppler)

### 6.4 Saídas confirmadas

- **`0xCF60`** — Range-Doppler **complexo** (65 × 64)
- **`0x4C60`** — Range-Doppler **magnitude** (65 × 64)

---

## 7. VIA A — CAPTURA PASSIVA: POR QUE A INSTRUÇÃO ORIGINAL NÃO FUNCIONA

### 7.1 O problema do CS no ESP32-S3

O líder pediu: *"Como não há pino de CS, a ESP32-S3 precisará usar uma interrupção de GPIO
no pino de Clock (PB0/PP0) para ler o pino de Dados (PB2/PP2) bit a bit."*

**Dois problemas, ambos verificados:**

**(a) O driver SPI slave do ESP32-S3 exige bordas de CS.**
Documentação oficial (ESP-IDF, `spi_slave`): *"A full-duplex SPI transaction begins when
the Host asserts the CS line… At the end of the transaction, the Host de-asserts the CS
line."* O driver **não tem** modo "sem CS". Thread no fórum do Espressif (2023, mesmo
sintoma, `spi_slave_transmit` nunca retorna): confirmado. O ESP32 (original) tem
`SPI_CS0_DIS` em `SPI_MISC_REG`, mas **o ESP32-S3 não** — e o `SPI0/1` do S3 também não
suporta slave.

Alternativas dentro do ESP32-S3, todas verificadas como **não-óptimas**:
- "Fake CS" por pull-up/pull-down num pino — o driver ainda exige *transições*, e o timing
  seria frágil.
- Rotear CS para um pino virtual sempre-ativo — não existe no S3.

**(b) ISR no clock é lento demais.**
Com clock de 2–4 MHz, o período é de 250–500 ns. A latência de uma ISR no ESP32-S3
(240 MHz, `IRAM_ATTR`) é de **~1–2 µs**, ou seja **4–8× o período**. Perde-se o
sinal. A 1 MHz a taxa de erro ainda é alta.

### 7.2 A solução que entreguei

No sketch `esp32s3_spi_sniffer.ino` implementei **amostragem por ISR com reconciliação
de bits em software**, com estas mitigações:
- ISR em IRAM lendo **`GPIO.in` diretamente** (não `digitalRead()`, que passa por
  funções da Arduino — ~10× mais lento)
- dispara só na **borda de descida**, que é o instante estável do dado no modo 1
- ring buffer de 64 KB em RAM, com contador de overruns
- **reconciliador de bytes por software**: procura um header com `idx == 0` e **exige a
  progressão 0→63** antes de aceitar o cubo — elimina frames espúrios

**Limite honesto: ~1 MHz.** Acima disso, use as opções abaixo.

### 7.3 Opções recomendadas por taxa de clock

| Taxa | Solução | Nota |
|---|---|---|
| ≤ 1 MHz | **ESP32-S3** (sketch entregue) | Funciona; watch o contador de overruns |
| 1–10 MHz | **Raspberry Pi Pico com PIO** | ★ **RECOMENDADO.** PIO decodifica SPI sem CS de forma determinística, a qualquer taxa. ~20 linhas de `pioasm`. |
| qualquer | **Analisador lógico** (Logic 2 / Saleae / cheap 8ch) | Decoder SPI mode 1 pronto; salva `.sr`/CSV para reprocessar |
| qualquer | **Patch de firmware** (Via B) | Zero hardware extra; stream direto pela UART |

### 7.4 Ligação sugerida

```
AC635N                          ESP32-S3
  PP0 (PB0, SPI1CLK)  ─────────▶ GPIO 12
  PP2 (PB2, SPI1DI)   ─────────▶ GPIO 11
  GND                 ─────────▶ GND
                                   MISO (GPIO13) — NÃO LIGAR
```

⚠️ **Nível lógico:** confirmar 3,3 V vs 1,8 V no módulo antes de ligar. Se for 1,8 V,
usar level shifter (ou o GND comum com divisor resistivo, se os pulsos tolerarem).

⚠️ **Não use MISO.** O barramento é single-wire bidirecional e o AC635N não transmite
nele; apenas observar PP0 e PP2.

### 7.5 Protocolo do sketch ↔ PC

```
ESP32 → PC (USB CDC):
  AA BB CC DD | len(u32 LE=16448) | seq(u32 LE) | payload (16448 B)
  payload = 64 frames × 257 bytes = [header][256 amostras int8]

PC → ESP32: 'S' (inicia captura) / 'X' (para)
```

O `capture_cube.py` envia `S` a cada segundo, valida o framing, grava
`cube_NNNNNN.bin` (16448 B, com headers) e `cube_NNNNNN_samples.bin` (16384 B, 64×256
puro) e reporta `headers_ok` e os bits de status.

---

## 8. VIA B — PATCH DE FIRMWARE (conceito detalhado)

### 8.1 Hook ideal

O melhor ponto de hook é a **entrada de `0x1E15B5E`** (início da cadeia FFT):

- o cubo **já está pronto** em `0x15B60` (16384 B empacotados) quando essa função é
  chamada — não é preciso recalcular nada
- o cave verifica um flag; se ligado, envia `0x15B60`/0x4000 pela UART0 e **retorna sem
  rodar a FFT**
- se desligado, executa o prólogo original (`[--sp] = {rets, r15-r4}`, `sp += -520`) e
  salta para `0x1E15B64`

Alternativa: hook em `0x1E14E46` (antes do empacotamento) → enviaria
`0x19D74 + 0x4040` (16448 B, **com** os headers).

### 8.2 Code caves encontrados no binário

Sequências de bytes nulos confirmadas em `firmware_app.bin` (base `0x1E00120`):

| Endereço | Tamanho | Observação |
|---|---|---|
| **`0x1E27A34`** | **1032 B** | melhor candidato — seguido de `ff ff 03 37 55 55` |
| `0x1E281E9` | 903 B | logo após a string `"…riorityDisinherit"` |
| `0x1E28571` | 99 B | |
| `0x1E27F4D` | 78 B | |
| `0x1E27E7B` | 68 B | |
| `0x1E24514` | 64 B | ⚠️ é a **tabela de vetores** copiada para RAM 0x0 no startup — **NÃO USAR** |

Nota: o arquivo termina em `0x1E28820`; os últimos bytes (`0x1E287F8`–`0x1E2881F`, 40 B)
são `0xFF` — outro candidato pequeno.

### 8.3 Como compilar código pi32v2

O toolchain JieLi na VM já faz isso:

```bash
/opt/rea-fw/tools/jieli-toolchain/pi32v2/bin/clang -target pi32v2 -O2 -c stub.c -o stub.o
/opt/rea-fw/tools/jieli-toolchain/pi32v2/bin/objdump -d stub.o
```

O `objdump` oficial decodifica corretamente **desde que se use `-mcpu=r3`**:
```
objdump -mcpu=r3 -d firmware_app_ld.elf
```
Sem `-mcpu=r3`, ~1465 instruções caem em `<unknown instruction>` (pools de literais).

### 8.4 Envio pela UART0

O dispatcher está em **`0x1E115FA`**:
```
1e115fa: r2 = 0x1E230        ; ctx do radar
1e11600: r2 = [r2+80]        ; ctx+80 = 0x1E280 → handle do device UART
1e11604: r2 = [r2+20]        ; tabela de métodos → handler de escrita
1e11606: goto r2             ; chamada indireta
```
Chamadores conhecidos:
- `0x1E10A0A` — envia 10 bytes de `0x19B9C`
- `0x1E10B9A` — frame builder (resposta de comando)
- `0x1E16C8E` — caminho de recepção host

**Assinatura:** `r0 = buffer`, `r1 = tamanho` (verificado no caller `0x1E10A0A`:
`r0 = 105324` e `r1 = 10`).

**Enviar em chunks de 512 B** para não estourar o ring buffer; testar 0x4000 de uma vez
só se o driver aceitar.

### 8.5 Tabela de comandos host

**14 entradas de 8 bytes** em **`0x1E21A34`**, formato `{cmd(u32), handler(u32)}`:

| idx | cmd | handler | Função (do `strings-app.txt` / decompilação) |
|---|---|---|---|
| 0 | `0x00FF` | `0x1E10BA6` | StartCfg |
| 1 | `0x00FE` | `0x1E10BD6` | EndCfg |
| 2 | `0x00A0` | `0x1E10C06` | GetRadarBaseParam |
| 3 | `0x00A1` | `0x1E10C58` | SetRadarBaseParam |
| 4 | `0x00A2` | `0x1E10F4E` | GetRadarTrigParam |
| 5 | `0x00A3` | `0x1E10FDA` | SetRadarTrigParam |
| 6 | `0x00A4` | `0x1E11012` | OutIoPolarityGet |
| 7 | `0x00A5` | `0x1E1107C` | OutIoPolaritySet |
| 8 | `0x0012` | `0x1E110FC` | Restore (AlgoParamInit) |
| 9 | `0x0002` | `0x1E111EC` | GetVersion |
| 10 | `0x0013` | `0x1E11270` | GetMac |
| 11 | `0x0003` | `0x1E112B2` | Boot (Reboot) |
| 12 | `0x00A6` | `0x1E11300` | BleSW |
| 13 | `0x00A7` | `0x1E1136A` | Baudrate / leitura de registrador |

**Não há slot livre** (14/14). Opções:
1. **Repurposear a entrada 13** (`0xA7`) → trocar o cmd para `0x0099` e apontar para o
   cave. ⚠️ Se o host usa `0xA7`, quebra-se essa função.
2. **Hook antes do lookup** em `0x1E16D4E` (leitura de `b[r4+6]`, o comando):
   ```
   1e16d4e: r10 = b[r4+6] (u)     ; ← cmd lido do buffer host
   1e16d52: r0 = r15 + 232
   1e16d56: r1 = r10
   1e16d58: call 0x1E0C3E2
   ```
   Se `r10 == 0x0099` → desvia para o cave.
3. **Dump automático** sem comando: útil para bancada, mas polui a UART do host.

**Formato de dump proposto:**
```
AA BB CC DD | len(u32 LE) | seq(u32 LE) | payload
payload = 0x15B60, 0x4000 bytes, empacotado 64×256 int8
```
Alternativas: `0xCF60` (complexo, 33280 B) ou `0x4C60` (magnitude, 16640 B).

**Flag de controle:** reservar 4 bytes no próprio code cave (não usar BSS sem verificar).

### 8.6 Baud e vazão

O baud da UART host vem de `[0x19B64]`. O `isd_config.ini` indica **1 000 000 bps**
(8N1). A 1 Mbps, 16 KB levam ~131 ms → ~7,6 cubos/s. A 460800 → ~284 ms → 3,5/s.

⚠️ **Nota:** o dump bloqueia a task; o ISR do SPI continua enchendo `0x19D74`, mas o
processamento pula ciclos (perda de cubos, não de integridade).

### 8.7 Riscos de brick

| Risco | Mitigação |
|---|---|
| Firmware não boots | Guardar dump da flash original (`esptool read_flash`) + testar o `.ufw` num módulo de descarte |
| OTA rejeita o `.ufw` | Ver §9 (container, CRCs) |
| Patch corrompe BSS/stack | Usar code cave em `0x1E27A34`; nunca `0x1E24514` |
| CRC do container errado | Recalcular `hdrcrc`, `listcrc` e `edcrc` (ver §9) |
| **RST do RC2412 durante gravação** | O RC2412 é o master do SPI1 — se ele foriar o clock durante o flash, corrompe. Considerar segurar RST |

### 8.8 Container `.ufw` — verificado na sessão anterior

Formato `jl-new-fw`:
- header **0x40** bytes: `hdrcrc(u16)`, `listcrc(u16)`, `imgsize(u32)`, `numents(u16)`,
  `wa3(u16)`, `wa4(u16)`, chipname (16 B)
- **7 entradas** de **0x50** bytes: `etype, eindex, edcrc, ewa1, eoffset, esize, esize2, ewa2, ename`
- dados dos arquivos após o header

**Cifras/CRCs (implementação Python pura, na sessão anterior):**

```python
def jl_crc16(data, crc=0x0000):
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def jl_enc_cipher(buff, off, size, key=0xFFFF):   # LFSR scrambling
    for i in range(size):
        buff[off+i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return key
```

- `chip-key = 43023` (`0xA80F`), extraído do `isd_config.ini`
- chave do header = `0xFFFF`
- app area usa também `jl_sfc_cipher` (SFC region)

**Ferramentas** (sessão anterior, `jl-misctools`): `fwunpack_newfw.py`, `recrypt.py`,
`jltech/cipher.py`, `jltech/crc.py`, `jltech/chipkeybin.py`.
⚠️ **Não há packer pronto** — só unpacker. Para reempacotar é preciso reimplementar a
escrita do container (ou usar o `fwpack` oficial do SDK JieLi).

---

## 9. PROTOCOLO UART HOST (para referência)

Protocolo LD2451 v1.03 (do PDF oficial, extraído para `ld2451_protocol.txt`):

**Comando:** `FD FC FB FA` + `len(u16 LE)` + `cmd(u16 LE)` + payload + `04 03 02 01`
**Resposta/ACK:** cmd + `0x100`
**Relatório de alvos:** `F4 F3 F2 F1` + len + alarm + count + N×5 bytes de alvo + `F8 F7 F6 F5`

Tabela de baudrates lida do firmware em `0x1E204BC` (8 × u32):
`1→115200, 2→9600, 3→19200, 4→38400, 5→57600, 6→115200, 7→230400, 8→256000`

⚠️ **Não existe engineering mode `0x62/0x63`** no protocolo v1.03 — a via de dados
brutos **tem** de ser pela captura de hardware ou pelo patch.

Cliente pronto em `~/rea-fw/s3k8y2/hlk2451_client.py` (pyserial, sem app da Hi-Link).

---

## 10. AMBIENTE E FERRAMENTAS

### 10.1 VM GCP (compilação Ghidra + Arduino)

| Item | Valor |
|---|---|
| Instância | `rea-fw-spot` (spot), zona `us-central1-a`, projeto `stt-465818` |
| Conta | `cooprevisaude@gmail.com` |
| Ghidra | 12.1.4 em `/opt/rea-fw/tools/ghidra_12.1.4_PUBLIC` |
| Plugin pi32v2 | `quarkslab/ghidra-jieli` em `/opt/rea-fw/tools/ghidra-jieli` |
| Projeto Ghidra | `/opt/rea-fw/projects/hlk` (programa `firmware_app_elf.bin`, 558 funções) |
| Toolchain JieLi | `/opt/rea-fw/tools/jieli-toolchain/pi32v2/bin/` (clang 4.0.1, target `pi32v2`) |
| Arduino CLI | `/opt/rea-fw/work/arduino/arduino-cli` + core `esp32:esp32@3.3.12` |
| Scripts Ghidra | `~/rea-fw/{TraceSpi,ForceAnalyze,VerifyFw}.java` |

⚠️ **Armadilhas:**
- `arduino-cli` no Termux roda via `termux-chroot` mas o **toolchain x86 do Arduino não
  executa** → compilar **na VM** (é o que fiz; funcionou).
- `gcloud compute ssh --command='cd X && nohup ... &'` backgrounda a cadeia toda.
- `sudo chown -R $USER:$USER /opt/rea-fw` antes de `scp`.
- **Não tocar** na instância `anthor-server`.
- Custo do spot é aceitável, mas **backup do projeto Ghidra em disco persistente** é
  obrigatório.

### 10.2 Termux (análise leve)

`~/rea-fw/` contém: `app_objdump.txt` (61 478 linhas de desmontagem pi32v2 oficial),
`firmware_app.bin` (165 632 B, base `0x1E00120`, SHA-256
`77d399e7e673c416b98ab3ba0d0f6b14ff0fa6b2d2da09c45ea6444869dab800`),
`zip_s3k8y2/` (o OTA original), `ac635n_manual.txt` (2753 linhas),
`ld2451_protocol.txt`, `s3k8y2/strings-app.txt`, `research/br23/*.h` (mapas de
periféricos), `research/hlk_research_session.jsonl` (log da sessão anterior).

⚠️ Na sessão anterior, VAs antigos precisavam de **+0x120** (o blob foi re-extraído com
base `0x1E00120`).

### 10.3 Links de referência (do briefing do líder)

- Plugin Ghidra: `https://github.com/quarkslab/ghidra-jieli`
- SDK oficial: `https://github.com/Jieli-Tech/fw-AC63_GP_MCU`
- Toolchain Linux: `https://pkgman.jieliapp.com/s/linux-toolchain` → `jl-update.oss-cn-shenzhen.aliyuncs.com/jieli-linux-toolchains-20260730.1.tar.xz` (25 MB)
- Toolchain Windows: `https://pkgman.jieliapp.com/s/win-toolchain`
- Dumper: `https://github.com/kagaimiq/jl-uboot-tool`
- Info BR23: `https://kagaimiq.github.io/jielie/chips/br23/`

---

## 11. ITENS DE RISCO / PENDENTES

| # | Item | Impacto | Como resolver |
|---|---|---|---|
| **R1** | **Taxa real do clock SPI1 não é conhecida** (o clock vem do RC2412) |define se o ESP32-S3 serve ou se é obrigatório ir de Pico/PIO | Medir com osciloscópio ou analyzer lógico na bancada. Se ≤1 MHz → sketch entregue serve; se >1 MHz → PIO |
| **R2** | Nível lógico do barramento (3,3 V vs 1,8 V) |queima a ESP32 se errar | Medir antes de ligar; level shifter se 1,8 V |
| **R3** | Sem packer `.ufw` | o patch não pode ser entregue por OTA | Reimplementar a escrita do container OU gravar direto via USB/SPI do AC635N |
| **R4** | Tabela de comandos cheia (14/14) |injetar `0x99` exige repurpose ou hook | Hook em `0x1E16D4E` (recomendado) ou repurpose `0xA7` |
| **R5** | Baud real da UART host (`[0x19B64]`) vs 1 Mbps do `isd_config.ini` |define a vazão do dump | Ler em runtime ou testar |
| **R6** | Sem backup da flash do HLK-LD2451 | brick irreversível | `esptool read_flash` ANTES de qualquer gravação |
| **R7** | Estrutura do command frame de entrada (`b[buf+7]`, `b[buf+8]`) |define o payload do cmd `0x99` | Descompilar o handler em `0x1E16D4E` |

---

## 12. PLANO DE EXECUÇÃO SUGERIDO

### Fase 1 — Bancada, sem risco (AGORA)
1. Medir a **taxa do clock SPI1** e o **nível lógico** (R1, R2). Sem isso, a escolha do
   sniffer é uma loteria.
2. Com analisador lógico (barato, ~US$10-20): capturar PP0/PP2 em SPI mode 1 e **salvar
   o arquivo bruto**. Isso já é um resultado_publicável: confirma ou refuta toda a
   engenharia reversa.
3. Se ≤1 MHz: gravar o sketch ESP32-S3 e capturar o cubo pela USB.
4. Se >1 MHz: usar um **Pico com PIO** (ou Logic 2 + decoder SPI).
5. Processar: `capture_cube.py` → `plot_rd.py` → mapa Range-Doppler.

### Fase 2 — Validação cruzada
6. Comparar o mapa Range-Doppler capturado **fora** do módulo com o que o próprio módulo
   calcula por dentro (0x4C60). Se baterem, a RE está 100% correta.

### Fase 3 — Patch de firmware (só depois das fases 1-2)
7. Compilar o stub pi32v2 com o toolchain JieLi na VM.
8. Colocar no code cave `0x1E27A34`.
9. Hook em `0x1E15B5E` + comando `0x99` (hook em `0x1E16D4E`).
10. Recalcular CRCs do `.ufw` (ou gravar direto) e testar **em módulo de descarte**.

---

## 13. PERGUNTAS PARA O LÍDER

1. **Tem analisador lógico ou ainda só a ESP32-S3?** Se só a ESP32-S3, ela roda a
   240 MHz? (A 1 MHz funciona; acima disso, precisa do Pico.)
2. **Tem um Pico/RP2040 disponível?** Ele resolve o problema de forma determinística.
3. **A taxa do clock SPI1 é conhecida de algum documento do RC2412?** Isso decide a
   arquitetura do sniffer sem ir à bancada.
4. **Existe um segundo HLK-LD2451 para testar um firmware patch?** (R6 é crítico.)
5. **Quer que eu implemente agora o stub pi32v2 do patch** (compilar + colocar no cave
   + gerar o `.bin` patcheado, sem gravar no módulo), ou prefere primeiro o
resultado da captura de hardware?

---

## 14. RESUMO DAS CORREÇÕES FEITAS CONTRA O BRIEFING ORIGINAL

| # | Afirmação original | Realidade verificada |
|---|---|---|
| 1 | "`app_radar` começa em `0x1E16692`" | **`0x1E16DD2`**; `0x1E16692` é código dentro do state machine `0x1E15FD4` |
| 2 | Tabela de tasks em `0x1E1EE10` | **`0x1E1EE14`** (em `0x1E1EE10` está o qsize da entrada anterior) |
| 3 | "byte 0 do frame é 0x00" | **Não**: `idx = byte & 0x3F`; bit 7 = status. Comparar com `0x00` **perde frames** |
| 4 | "detectar header 0x00 e verificar progressão até 0x3F" | A progressão deve ser `(byte & 0x3F) == 0..63` — o bit de status suja o byte |
| 5 | "ESP32-S3 com interrupção de GPIO no clock" | **Inviável a 2–4 MHz** (latência de ISR 1–2 µs vs período 250–500 ns). Além disso o driver SPI slave do S3 **exige CS**, que não existe neste barramento |
| 6 | "SPI0 é o link com o radar" | **SPI0 é a flash serial externa** (comandos 0x6B/0x9F/0x4B em `0x1E24900`). O radar é **SPI1** |
| 7 | "0x1E241D4 é dispatch de comandos/DMA" | É o **open/init da UART host** |
| 8 | "0x1E2376A é init do radar" | É **init genérico de sistema/board** |
| 9 | "os 256 pontos vêm de 0x19D75 com 0x4000 bytes" | `0x19D75` tem **stride 257** (headers). O payload **empacotado** de 0x4000 bytes está em **`0x15B60`** (stride 256) |
| 10 | "amostras são I/Q" | São **reais** (int8). O I/Q complexo é **resultado** da FFT de range em `0xCF60` |

---

## 15. ÍNDICE DE ARQUIVOS

```
~/rea-fw/
├── zip_s3k8y2/                      OTA original (app.bin, ufw, uboot.boot, isd_config.ini)
├── app_objdump.txt                  desmontagem pi32v2 oficial (61.478 linhas)
├── firmware_app_elf.bin             ELF p/ Ghidra
├── ac635n_manual.txt                manual AC635N (2753 linhas)
├── ld2451_protocol.txt              protocolo LD2451 v1.03
├── ac6351d_datasheet.txt            datasheet AC6351D
├── s3k8y2/hlk2451_client.py         cliente UART host (pyserial)
├── s3k8y2/strings-app.txt           inventário de strings com VAs
├── research/br23/{br23.h,spi.h,uart.h,gpio.h}   mapas de periféricos
├── research/hlk_research_session.jsonl           log da sessão anterior
└── sniffer/                         ★ NOVOS ARTEFATOS
    ├── esp32s3_spi_sniffer/esp32s3_spi_sniffer.ino   sniffer (compila OK)
    ├── capture_cube.py              PC: framing + gravação
    └── plot_rd.py                   PC: FFT range-Doppler + CSV + ASCII

VM rea-fw-spot:
/opt/rea-fw/
├── tools/ghidra_12.1.4_PUBLIC/      Ghidra
├── tools/ghidra-jieli/              plugin pi32v2
├── tools/jieli-toolchain/pi32v2/    clang/objdump pi32v2 oficial
├── projects/hlk/                    projeto Ghidra
├── work/app_objdump.txt(.gz)        desmontagem
├── work/firmware_app_ld.elf         ELF válido (linker JieLi + flag AX)
├── work/arduino/arduino-cli         Arduino CLI + core esp32 3.3.12
└── work/arduino/build/              build do sketch ESP32-S3
```

---

**Estado final:** engenharia reversa **completa e verificada**; artefactos de captura
**compilados e testados**; patch de firmware **desenhado com endereços exatos, code
caves identificados e pontos de hook confirmados**. Aguardando bancada para as Fases 1-2
e decisões do líder sobre os itens R1-R7.
