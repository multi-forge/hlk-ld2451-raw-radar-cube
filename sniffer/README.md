# Sniffer passivo do SPI1 — HLK-LD2451

Escuta passiva do barramento **SPI1** entre o RC2412FR (radar) e o AC635N (SoC),
para capturar o **cubo radar bruto** 64×256.

⚠️ **Risco zero para o módulo** — é apenas uma escuta em PP0/PP2.

---

## O que é capturado

| | |
|---|---|
| Barramento | SPI1, 1 bit, **modo 1** (CPOL=0, CPHA=1), **sem CS** |
| Pinos | PP0 (PB0) = CLK · PP2 (PB2) = DI |
| Frame | 257 bytes = `[header(1)] [256 amostras int8]` |
| Header | `idx = byte & 0x3F` (0..63) · `bit 7` = status |
| Cubo | 64 frames → 64×256 = **16 384 bytes int8** |

---

## Fiação

```
AC635N (dentro do HLK-LD2451)        ESP32-S3
  PP0  (PB0, SPI1CLK)  ─────────────▶ GPIO 12
  PP2  (PB2, SPI1DI)   ─────────────▶ GPIO 11
  GND                  ─────────────▶ GND
```

* **MISO (GPIO 13) — NÃO LIGAR**
* **3V3 — NÃO LIGAR** (o módulo tem a sua alimentação)
* ⚠️ **Confirmar o nível lógico (3,3 V vs 1,8 V) ANTES de ligar**
* ⚠️ PP0/PP2 são pinos internos do QFN — ver [guia de bancada](../docs/07-bancada.md)

---

## Compilar e gravar

Na VM GCP (o toolchain Arduino não corre no Termux/Android):

```bash
arduino-cli core install esp32:esp32@3.3.12
cd esp32s3_spi_sniffer
arduino-cli compile --fqbn esp32:esp32:esp32s3 \
    --build-path /opt/rea-fw/work/arduino/build esp32s3_spi_sniffer.ino
esptool.py --chip esp32s3 --port /dev/ttyACM0 write_flash 0x0 \
    esp32s3_spi_sniffer.ino.bin
```

No Arduino IDE: **ESP32S3 Dev Module**, **USB CDC On Boot: Enabled**, porta USB nativa.

---

## Protocolo

```
ESP32 → PC (USB CDC, 921600 baud)
  AA BB CC DD | len(u32 LE = 16448) | seq(u32 LE) | payload (16448 B)
  payload = 64 frames × 257 bytes = [header][256 amostras int8]

PC → ESP32
  'S'  iniciar captura
  'X'  parar e imprimir STATS
  'R'  imprimir STATS sem parar
```

---

## Implementação

* ISR em `IRAM_ATTR` que lê **`GPIO.in` directamente** (não `digitalRead()`, que passa
  por funções da Arduino e é ~10× mais lento)
* dispara na **borda de descida** do clock — instante em que o dado é estável no modo 1
* ring buffer de 64 KB em RAM, com contador de **overruns**
* reconciliação de bytes em software: procura um header com `idx == 0` e **exige a
  progressão 0→63** antes de aceitar o cubo — elimina frames espúrios

### Limitação honesta: ~1 MHz

Com clock de 2–4 MHz (o período é de 250–500 ns) a latência de uma ISR (1–2 µs) é
insuficiente. O contador de overruns avisa:

```
# STATS cubes_ok=3 cubes_fail=0 overruns=0 bits_lost=0
# overruns=0 -> captura integralmente confiavel
# ATENCAO: 142 overruns -> bits perdidos; clock SPI1 rapido demais para a ISR
# USE: Raspberry Pi Pico (PIO) ou analisador logico
```

Alternativas para clock rápido: **Raspberry Pi Pico com PIO** (determinístico) ou
**analisador lógico**.

### Diagnóstico de fase de bit

Se os headers saírem deslocados,experimente a borda de subida:

```cpp
attachInterrupt(digitalPinToInterrupt(PIN_SCLK), isr_clock, FALLING);
//                                              ^^^^^^  →  RISING
```

---

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `esp32s3_spi_sniffer/esp32s3_spi_sniffer.ino` | o sketch |
| `../tools/capture_cube.py` | PC: framing + gravação |
| `../tools/plot_rd.py` | PC: FFT + Range Profile |
