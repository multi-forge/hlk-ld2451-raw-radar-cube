# HLK-LD2451 — Extração do Cubo Radar Bruto

**Engenharia reversa do radar mmWave Hi-Link HLK-LD2451 (24 GHz)** para extrair os
**dados brutos** (cubo radar 64×256, int8) em vez de apenas os pacotes de alvos já
processados que o módulo envia pela UART.

| | |
|---|---|
| **Alvo** | Módulo Hi-Link HLK-LD2451 |
| **SoC** | JieLi **AC635N** (série BR23), ISA proprietária **pi32v2** (RISC 32-bit) |
| **Front-end RF** | SkyRelay **RC2412FR** (ADC 8 bits, 1 TX, 2 RX) |
| **Firmware analisado** | `HLK-LD2451_V1.13.ufw` → `app.bin` v1.13 (165 632 bytes, base `0x1E00120`) |
| **SHA-256 app.bin** | `77d399e7e673c416b98ab3ba0d0f6b14ff0fa6b2d2da09c45ea6444869dab800` |
| **Status** | RE **concluída e verificada** · sniffer **compilado e testado** · patch **gerado e validado** |
| **Última atualização** | 2026-10-20 |

---

## TL;DR — o que foi descoberto

O AC635N **é o cérebro do DSP**; o RC2412FR é apenas o front-end analógico/ADC. A cadeia
completa de processamento de sinal foi mapeada com endereços exatos:

```
RC2412FR (ADC 8-bit)
   │  SPI1 · 1 bit · modo 1 (CPOL=0, CPHA=1) · SEM pino de CS
   │  quadro = 257 bytes = [header(1) + 256 amostras int8]
   ▼
AC635N ── ISR 0x1E1146E ──▶ buffer bruto  0x19D74 + idx*257   (64 chirps)
   │
   ▼  rotina 0x1E14E46 (copia 64×256 bytes, stride 257 → 256)
CUBO PACKED  0x15B60   (64 × 256 = 16384 bytes, int8, contíguo)   ★ alvo
   │
   ▼  rotina 0x1E15B5E (janela 256 floats @ 0x1E21F84 → FFT 256 pts @ 0x1E15480)
   │                    → 65 bins de range, saída complexa 0x15360
   ▼
RANGE-DOPPLER COMPLEXO  0xCF60   (65 range × 64 doppler, float32)
   │  (janela Doppler 64 floats @ 0x1E21E84 → FFT 64 pts → magnitude)
   ▼
MAPA DE MAGNITUDE  0x4C60   (65 × 64 float32)
   │
   ▼
detecção de alvos → frame UART "F4 F3 F2 F1 … F8 F7 F6 F5"
```

**Duas vias de captura**, ambas implementadas neste repositório:

| Via | Descrição | Risco | Artefatos |
|---|---|---|---|
| **A — Passiva (HW)** | Espelhar PP0 (CLK) e PP2 (DI) com um sniffer SPI | **Nenhum** | [`sniffer/`](sniffer/), [`tools/`](tools/) |
| **B — Patch de firmware** | Injetar dump do cubo na UART0 do próprio AC635N | Brick (exige módulo de descarte) | [`firmware/`](firmware/) |

---

## Sumário do repositório

```
.
├── README.md                          este ficheiro
├── RELATORIO.md                       relatório técnico completo (equivalente ao PDF enviado)
├── docs/
│   ├── 01-mapa-de-memoria.md          endereços verificados e semântica de cada buffer
│   ├── 02-cadeia-dsp.md               desmontagem anotada da cadeia FFT
│   ├── 03-protocolo-spi1.md           formato do frame SPI, ISR, modo, pinos
│   ├── 04-protocolo-uart-host.md      protocolo FD FC FB FA do host
│   ├── 05-container-ufw.md            formato, cifra e CRC do container .ufw
│   ├── 06-patch-de-firmware.md        desenho completo do patch (stub, hooks, code caves)
│   ├── 07-bancada.md                  guia de bancada, fiação, riscos, checklist
│   └── 08-correcoes-ao-briefing.md    as 10 correções à instrução original
├── sniffer/
│   ├── esp32s3_spi_sniffer/           sketch Arduino (ESP32-S3) — compila verificado
│   └── README.md                      fiação, limites, alternativas
├── tools/
│   ├── capture_cube.py                PC: framing, validação, gravação do cubo
│   ├── plot_rd.py                     PC: FFT range-Doppler + Range Profile + CSV
│   └── smoke_test.py                  Teste de fumo ponta a ponta (captura + DSP + patch)
├── firmware/
│   ├── stub3.c                        stub pi32v2 do dump (C, para o toolchain JieLi)
│   ├── hooks.s                        hooks asm que redirecionam as chamadas
│   ├── link_stub.ld                   linker script (posiciona hook e stub)
│   ├── apply_patch2.py                aplicador do patch (verifica e aplica)
│   ├── patch.elf                      stub + hooks linkados (pronto)
│   └── patched_firmware.bin           firmware patcheado (flag=2, contínuo)
├── research/
│   ├── ac635n_manual.txt              manual AC635N extraído (2753 linhas)
│   ├── ld2451_protocol.txt            protocolo oficial LD2451 v1.03
│   ├── sdk-headers/                   headers BR23 (br23.h, spi.h, uart.h, gpio.h)
│   └── ghidra-scripts/                scripts Ghidra headless usados na análise
└── artifacts/                         saídas e logs
```

---

## Via A — Captura passiva (recomendada, sem risco)

### Por que a instrução original não funcionaria

O briefing pedia *"interrupção de GPIO no pino de Clock"*. **Dois problemas
verificados:**

**(a) O driver SPI slave do ESP32-S3 exige bordas de CS.**
A documentação oficial (ESP-IDF, `spi_slave`) diz: *"A full-duplex SPI transaction begins
when the Host asserts the CS line… At the end of the transaction, the Host de-asserts the
CS line."* O driver **não tem** modo "sem CS". Confirmado no fórum do Espressif (mesmo
sintoma: `spi_slave_transmit` nunca retorna).

Isto não é uma hipótese: o registo `SPI1_CON` do firmware tem o **bit CSE (bit2) a zero**,
o que significa literalmente *"não usar o sinal SPICS"*. **O hardware não tem pino de CS.**

**(b) ISR no clock é lento demais.** Com clock de 2–4 MHz o período é de 250–500 ns; a
latência de uma ISR no ESP32-S3 (240 MHz) é de ~1–2 µs, ou seja **4–8× o período**.

### A solução entregue

Sampling por ISR **otimizada** (IRAM, leitura direta de `GPIO.in`, sem `digitalRead()`),
com **reconciliação de bits em software** e validação estrita da progressão de headers.

* ✅ Compilado e validado na VM (core `esp32:esp32@3.3.12`, 281 713 bytes flash / 21%)
* ✅ Pipeline PC testado ponta a ponta com cubo sintético

**Limite honesto: ~1 MHz.** Acima disso use as alternativas da tabela abaixo.

### Fiação

```
AC635N                          ESP32-S3
  PP0 (PB0, SPI1CLK)  ─────────▶ GPIO 12
  PP2 (PB2, SPI1DI)   ─────────▶ GPIO 11
  GND                 ─────────▶ GND
                                   MISO (GPIO13) — NÃO LIGAR
```

⚠️ **Nível lógico:** confirmar 3,3 V vs 1,8 V **antes** de ligar. Se 1,8 V, usar level
shifter (ou divisor resistivo). O barramento é single-wire bidirecional e o AC635N não
transmite nele — observe apenas PP0 e PP2.

### Protocolo sketch ↔ PC

```
ESP32 → PC (USB CDC):
  AA BB CC DD | len(u32 LE = 16448) | seq(u32 LE) | payload (16448 B)
  payload = 64 frames × 257 bytes = [header][256 amostras int8]

PC → ESP32:  'S' captura   'X' para (imprime STATS)   'R' relatório de overruns
```

O sketch imprime `# STATS cubes_ok=N cubes_fail=M overruns=K bits_lost=K`.
**`overruns` é o indicador crítico**: cada overrun significa que a ISR perdeu um bit, logo
o cubo pode estar corrompido. Se crescer muito → clock rápido demais → migre para PIO.

### Alternativas conforme a taxa medida

| Taxa do clock SPI1 | Solução |
|---|---|
| ≤ 1 MHz | **ESP32-S3** (sketch incluído) |
| 1–10 MHz | **Raspberry Pi Pico com PIO** ★ recomendado — determinístico, sem CS |
| qualquer | **Analisador lógico** (Logic 2 / Saleae / 8ch barato) — decoder SPI mode 1 pronto |
| qualquer | **Patch de firmware** (Via B) — zero hardware extra |

---

## Via B — Patch de firmware (gerado, NÃO gravado)

> ⚠️ **NÃO GRAVADO EM NENHUM MÓDULO.** Só existe um módulo HLK-LD2451 e não há como
> testar. O binário está preparado para quando houver um segundo módulo.

### Conceito

O cubo já está pronto e empacotado em `0x15B60` (16 384 bytes) quando a cadeia FFT
chama. O patch intercepta **os dois call sites** da cadeia FFT:

| Endereço | Original | Patcheado |
|---|---|---|
| `0x1E1601E` | `bf ea 9e fd` → `call 0x1E15B5E` | `80 ea 0b 8d` → `call 0x1E27A38` |
| `0x1E162CC` | `bf ea 47 fc` → `call 0x1E15B5E` | `80 ea b4 8b` → `call 0x1E27A38` |

O stub em `0x1E27A38` (code cave de 1032 bytes, **verificado sem ponteiros 32-bit
apontando para ele**) faz:

1. lê o flag de controlo em `0x1E27A34`
2. se ≠ 0, envia o cabeçalho `AA BB CC DD | len | seq` e o cubo (16 384 B) em blocos de
   512 B pela UART0 (`0x1E115FA`, assinatura `r0=buffer, r1=len`)
3. **depois executa a função FFT original** (`call r0` → `0x1E15B5E`), preservando
   integralmente o comportamento do radar

Flag: `0` = desligado (idêntico ao original) · `1` = one-shot · `2` = contínuo.

### Por que os call sites e não a entrada da função

A primeira tentativa foi fazer hook em `0x1E15B5E` (entrada da cadeia FFT). A
validação por disassembly mostrou que isso **destruía o prólogo** da função:

```
1e15b5e:    c0 ea 6b 8f       	goto 0x1E27A38      ← hook
1e15b62:    f8 1d             	r0 = r7 + r7      ← LIXO (era `sp += -520`)
```

Um hook de 4 bytes não cabe no prólogo de 6 bytes. Hooking os **call sites** preserva a
ABI de forma inequívoca: o stub é chamado exactamente onde a original era chamada, com
os mesmos argumentos, e devolve chamando a original.

### Validação do patch

```
total de bytes alterados: 391
  região VA 0x01E1601E len 4 : 3 bytes alterados
  região VA 0x01E162CC len 4 : 3 bytes alterados
  região VA 0x01E27A34 len 4 : 1 byte alterado   (flag)
  região VA 0x01E27A38 len 490 : 384 bytes alterados  (stub)
  bytes alterados FORA das regiões esperadas: 0
```

Verificado por reconstrução do ELF e desassembly independente com o `objdump` oficial
JieLi (`-mcpu=r3`).

### Reprodutibilidade

```bash
# 1. compilar o stub e os hooks
clang -target pi32v2 -O2 -c stub3.c -o stub3.o
clang -target pi32v2 -c hooks.s -o hooks.o

# 2. linkar nas posições corretas (o linker JieLi resolve os displacements)
ld -m elf32pi32v2 -T link_stub.ld hooks.o stub3.o -o patch.elf

# 3. aplicar
python3 apply_patch2.py firmware_app.bin patch.elf patched_firmware.bin 2
```

O `objcopy` do toolchain **não** suporta `--only-section`; use `-j <secao>`.

### Riscos

| Risco | Mitigação |
|---|---|
| Brick | **Fazer dump da flash original antes** (`esptool read_flash`). Só testar em módulo de descarte. |
| OTA rejeita o `.ufw` | Recalcular `hdrcrc`, `listcrc`, `edcrc` (ver [`docs/05-container-ufw.md`](docs/05-container-ufw.md)) |
| Corromper BSS/stack | Usar o code cave `0x1E27A34`; **nunca** `0x1E24514` (é a tabela de vetores) |
| RST do RC2412 durante gravação | O RC2412 é o master do SPI1; considerar segurar o RST |
| Sem packer `.ufw` | Existe só o *unpacker*; reimplementar a escrita do container ou gravar direto por USB/SPI |

---

## Correções ao briefing original

A RE estática revelou **10 erros** na instrução inicial. As mais críticas:

| # | Afirmação original | Realidade verificada |
|---|---|---|
| 1 | `app_radar` começa em `0x1E16692` | **`0x1E16DD2`**; `0x1E16692` é código dentro do state machine `0x1E15FD4` |
| 2 | Tabela de tasks em `0x1E1EE10` | **`0x1E1EE14`** (em `0x1E1EE10` está o qsize da entrada anterior) |
| 3 | "byte 0 do frame é 0x00" | **Não**: `idx = byte & 0x3F`; bit 7 = status. Comparar com `0x00` **perde frames** |
| 4 | "detectar header 0x00 e progressão até 0x3F" | A progressão é `(byte & 0x3F) == 0..63` — o bit de status suja o byte |
| 5 | "ESP32-S3 com ISR no clock" | **Inviável a 2–4 MHz**; e o driver SPI slave do S3 **exige CS**, que não existe |
| 6 | "SPI0 é o link com o radar" | **SPI0 é a flash serial externa** (comandos `0x6B/0x9F/0x4B` em `0x1E24900`). O radar é **SPI1** |
| 7 | `0x1E241D4` é dispatch de comandos/DMA | É o **open/init da UART host** |
| 8 | `0x1E2376A` é init do radar | É **init genérico de sistema/board** |
| 9 | "256 pontos vêm de 0x19D75 com 0x4000 bytes" | `0x19D75` tem **stride 257** (headers). O payload **empacotado** de 0x4000 B está em **`0x15B60`** (stride 256) |
| 10 | "amostras são I/Q" | São **reais** (int8). O I/Q complexo é **resultado** da FFT de range em `0xCF60` |

Detalhe completo em [`docs/08-correcoes-ao-briefing.md`](docs/08-correcoes-ao-briefing.md).

---

## Resultados técnicos notáveis

**O registo `SPI1_CON` decodificado** (rotina `0x1E14D64`):

```asm
1e14dd8: [r6+0] &= 0xFFFFFFFB   ; bit2  CSE=0  → NÃO USA SPICS (sem CS)
1e14ddc: [r6+0] |= 0x2          ; bit1  SLAVE=1 → AC635N é escravo do RC2412
1e14de0: [r6+0] |= 0x10         ; bit4  SE=1 (amostra na borda de subida)
1e14dec: [r6+0] &= 0xFFFFFFBF   ; bit6  CKID=0 → SPICK ocioso em baixo (CPOL=0)
```

**O ISR do SPI1** (`0x1E1146E`) — formato do frame provado a nível de instrução:

```asm
1e11490: r1 = b[r5 + 0x4043]     ; header do frame em 0x1DDB4
1e1149a: r3 = r1 >> 7            ; ★ bit7 = STATUS
1e1149c: r6 = r1 & 0x3F          ; ★ bits0-5 = ÍNDICE DO CHIRP (0..63)
1e114b2: r0 += 3                 ; ★ dest = 0x19D74 + idx*257
1e114b8: call memcpy             ; copia 257 bytes
1e114cc: b[r5+0] = r0            ; ★ 0x19D71 = 1 → flag "cubo completo"
```

**Janela de range verificada empiricamente** (`0x1E21F84`, 256 float32): valores
`0.000149 … 0.99996 … 0.000149`, simétricos — tipo **Hann**. A janela Doppler
(`0x1E21E84`, 64 float32) tem pico 0.99943.

---

## Ambiente

### VM de análise (GCP)

| Item | Valor |
|---|---|
| Instância | `rea-fw-spot` (spot), zona `us-central1-a`, projeto `stt-465818` |
| Ghidra | 12.1.4 + plugin `quarkslab/ghidra-jieli` |
| Projeto Ghidra | `/opt/rea-fw/projects/hlk` (558 funções) |
| Toolchain JieLi | `/opt/rea-fw/tools/jieli-toolchain/pi32v2/bin/` (clang 4.0.1, target `pi32v2`) |
| Arduino CLI | `/opt/rea-fw/work/arduino/arduino-cli` + core `esp32:esp32@3.3.12` |
| Backup Ghidra | `/opt/rea-fw/backup/ghidra-hlk-20261020T063241Z.tar.gz` |
| Patch | `/opt/rea-fw/out/patch/` (`patched_firmware.bin`, `patch.elf`, fontes) |

⚠️ O toolchain x86 do Arduino **não** executa no Termux/Android — compilar na VM.

### Ferramentas de referência

* Plugin Ghidra pi32v2 — <https://github.com/quarkslab/ghidra-jieli>
* SDK oficial — <https://github.com/Jieli-Tech/fw-AC63_GP_MCU>
* Toolchain Linux — <https://pkgman.jieliapp.com/s/linux-toolchain>
* Dumper — <https://github.com/kagaimiq/jl-uboot-tool>
* Info BR23 — <https://kagaimiq.github.io/jielie/chips/br23/>

---

## Como reproduzir a análise

```bash
# 1. desassembly completa com o objdump oficial JieLi
objdump -mcpu=r3 -d firmware_app_ld.elf > app_objdump.txt

# 2. reconstruir o ELF a partir do app.bin bruto
ld -m elf32pi32v2 -T fw_link.ld -b binary firmware_app.bin -o firmware_app_ld.elf
#    (depois marcar a secção .text como AX: e_shoff+40+8 |= 4)

# 3. capturar e processar
python3 tools/capture_cube.py /dev/ttyACM0      # grava cube_000000_samples.bin
python3 tools/plot_rd.py cube_000000_samples.bin --csv rd.csv --profile-csv prof.csv

# 4. teste de fumo ponta a ponta (validação automática de captura, DSP e patch)
python3 tools/smoke_test.py
```

⚠️ Na sessão anterior, VAs antigos precisavam de **+0x120** (o blob foi re-extraído com
base `0x1E00120`).

---

## Aviso legal

Este repositório documenta engenharia reversa de firmware de terceiro para fins de
pesquisa, interoperabilidade e estudo de sinais de radar. O ficheiro `firmware_app.bin`
original **não** é distribuído aqui — é obtido do OTA oficial da Hi-Link. O
`patched_firmware.bin` incluído é uma modificação de pesquisa, para uso exclusivo em
módulos de teste próprios.

## Licença

Código e documentação deste repositório: MIT. Firmware da Hi-Link / JieLi: © seus
respectivos donos, não incluídos para redistribuição.
