# Guia de bancada — captura passiva do SPI1

> Fase 1 do plano. **Risco zero** para o módulo: é uma escuta passiva.

---

## 1. Antes de ligar: o que é obrigatório

### 1.1 Medir o nível lógico (R2)

O AC635N é um SoC de 3,3 V, mas **o pino PP0/PP2 do módulo pode estar a 1,8 V** ou
outro nível. **Medir com multímetro antes de ligar a ESP32-S3.**

| Medição | Acção |
|---|---|
| 3,3 V | ligar directamente |
| 1,8 V | **level shifter** (BSS138 bidireccional é demasiado lento para 2–4 MHz; usar TXS0108E ou 74LVC245) ou divisor resistivo se o duty cycle tolerar |
| 5 V | **não ligar** — usar divisor + level shifter |

> ⚠️ Ligar 5 V a um GPIO da ESP32-S3 destrói o GPIO e pode estragar a placa.

### 1.2 Medir a taxa do clock SPI1 (R1) — **O BLOQUEIO PRINCIPAL**

O clock vem do **RC2412FR** (master), não do AC635N. A firmware não define a taxa em
modo slave, por isso só se descobre empiricamente.

**Opção A — multímetro com função de frequência** (a mais simples):
ligar a ponta de teste em PP0. Deve mostrar ~1–4 MHz.

**Opção B — a própria ESP32-S3 como contador de pulsos** (não precisa de nada extra):

```cpp
// sketch de medição: conta bordas de subida em PP0 durante 1 s
volatile uint32_t count = 0;
void IRAM_ATTR isr() { count++; }

void setup() {
  pinMode(12, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(12), isr, RISING);
}
void loop() {
  uint32_t c = count;
  count = 0;
  Serial.printf("%lu pulsos/s  (~%.2f MHz)\n", c, c / 1e6);
  delay(1000);
}
```

Este sketch só conta — não faz mais nada — e funciona a taxas muito superiores ao
limite do sniffer. Serve perfeitamente para decidir a arquitectura.

**Opção C — analisador lógico** (se tiver): decoder SPI mode 1, e guardar o ficheiro
`.sr`/CSV.

### 1.3 Decidir a arquitectura

| Taxa medida | Decisão |
|---|---|
| **≤ 1 MHz** | usar o sketch ESP32-S3 incluído |
| **> 1 MHz** | comprar um **Raspberry Pi Pico** (RP2040) e usar PIO — é a solução determinística, ~20 linhas de `pioasm` |

---

## 2. Fiação

```
AC635N (dentro do HLK-LD2451)        ESP32-S3
  PP0  (PB0, SPI1CLK)  ─────────────▶ GPIO 12
  PP2  (PB2, SPI1DI)   ─────────────▶ GPIO 11
  GND                  ─────────────▶ GND

  MISO (GPIO 13) — NÃO LIGAR
  3V3                 — NÃO LIGAR (o módulo já tem a sua alimentação)
```

**Como aceder a PP0/PP2?** São pinos internos do AC635N (QFN). Opções:

1. **Test points expostos** na PCB do HLK-LD2451 — procurar por pads deRede do
   gate do radar. Usar um multímetro em modo continuidade para os identificar
   relativamente ao GND.
2. **Fios finos (Kynan wire / enamel)** soldados directamente no pad.
3. **Cortar a pista** e soldar no corte (funciona, mas stressa a placa).

> ⚠️ Este é o passo mais delicado. Um curto entre PP0 e PP2, ou com GND, estraga o
> módulo. **Confirmar a continuidade ANTES de ligar a ESP32.**

---

## 3. Gravar e correr o sniffer

### 3.1 Compilar

Na VM (o toolchain Arduino não corre no Termux/Android):

```bash
cd esp32s3_spi_sniffer
arduino-cli compile --fqbn esp32:esp32:esp32s3 \
    --build-path /opt/rea-fw/work/arduino/build esp32s3_spi_sniffer.ino
```

Pré-requisitos na VM:

```bash
arduino-cli core update-index --additional-urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.12
```

### 3.2 Gravar

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 write_flash 0x0 \
  esp32s3_spi_sniffer.ino.bin
```

No Arduino IDE: seleccionar **ESP32S3 Dev Module**, **USB CDC On Boot: Enabled**, e usar
a **porta USB nativa** (não a UART).

### 3.3 Capturar no PC

```bash
python3 tools/capture_cube.py /dev/ttyACM0
```

O script envia `S` a cada segundo, valida o framing e grava:

* `cube_000000.bin` — 16 448 B, com headers
* `cube_000000_samples.bin` — 16 384 B, 64×256 int8 puro

### 3.4 Verificar o resultado

O script imprime:

```
cube_000000.bin seq=0 headers_ok=True status_bits={0, 1}
```

* `headers_ok=True` ⇒ a progressão 0..63 foi correcta ⇒ **captura íntegra**
* `headers_ok=False` ⇒ ver a secção de diagnóstico abaixo

E o sketch imprime (a cada cubo e no fim):

```
# STATS cubes_ok=3 cubes_fail=0 overruns=0 bits_lost=0
# overruns=0 -> captura integralmente confiavel
```

### 3.5 Processar

```bash
python3 tools/plot_rd.py cube_000000_samples.bin --csv rd.csv --profile-csv prof.csv
```

Saída esperada:

```
Range Profile (potencia media por bin de distancia), pico no bin N:
  bin  0 |   ...
  ...
  bin  N |  ...  <== PICO
  ...
possivel alvo: bin de range N (..., ...% do pico)
```

---

## 4. Diagnóstico

| Sintoma | Causa provável | Acção |
|---|---|---|
| `overruns` alto | clock > ~1 MHz para a ISR | migrar para Pico PIO ou analisador |
| `headers_ok=False` | bits perdidos / fase errada | verificar bit order (MSB first), nível lógico, aterramento |
| nenhum cubo chega | CS? não é issue; clock não chega ao GPIO12 | medir PP0, confirmar continuidade |
| cubos com `idx` deslocado | amostragem na borda errada | mudar de FALLING para RISING e reavaliar |
| `# sem memoria` | `malloc` falhou | reduzir `RING_BYTES` ou reiniciar |
|(range profile sem pico) | alvo fora do alcance, ou ganho/AGC | aproximar o alvo, verificar o mapa RD |

### Diagnóstico de fase de bit

O sketch amostra na **borda de descida** (instante estável do dado no modo 1). Se os
headers saírem deslocados,experimente a **borda de subida** e compare. Em
`esp32s3_spi_sniffer.ino` basta trocar:

```cpp
attachInterrupt(digitalPinToInterrupt(PIN_SCLK), isr_clock, FALLING);
//                                              ^^^^^^  →  RISING
```

e recompilar.

---

## 5. Checklist

**Antes de tocar no módulo**

- [ ] Dump da flash original do HLK-LD2451 (para poder reverter)
- [ ] Nível lógico de PP0/PP2 medido e documentado
- [ ] Taxa do clock SPI1 medida
- [ ] PP0 e PP2 identificados com teste de continuidade (sem ESP32 ligada)
- [ ] grounds comuns ligados

**Captura**

- [ ] Sketch gravado na ESP32-S3
- [ ] `capture_cube.py` a correr
- [ ] `# STATS overruns=0`
- [ ] `headers_ok=True`
- [ ] `cube_000000_samples.bin` com 16 384 bytes

**Validação**

- [ ] `plot_rd.py` produz mapa Range-Doppler
- [ ] Range Profile com pico na distância esperada
- [ ] Mover um alvo e confirmar que o pico se move

**Opcional (cross-check)**

- [ ] Se houver segundo módulo: testar `patched_firmware.bin` (ver
      [`06-patch-de-firmware.md`](06-patch-de-firmware.md))
- [ ] Comparar o mapa capturado **fora** do módulo com o que o próprio módulo calcula
      internamente (`0x4C60`) — se baterem, a RE está 100 % correcta

---

## 6. O que fazer se a ESP32-S3 não servir

Sem analisador lógico e sem Pico, há ainda a Via B (patch) — mas ela exige um **módulo
de descarte**. Com um único módulo HLK-LD2451, o patch **não** deve ser tentado.

Opções de hardware barato (~US$ 5–15):
* Raspberry Pi Pico ou Pico W (RP2040) — PIO, a melhor opção
* Analisador lógico 8 canais 24 MHz (BT) com decoder SPI
* Módulo de 8 canais genérico (Saleae clone)
