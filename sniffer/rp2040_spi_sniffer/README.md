# Sniffer SPI1 Determinístico para Raspberry Pi Pico (RP2040)

Implementação em hardware dedicado via **PIO (Programmable I/O)** e **DMA** para capturar o barramento SPI1 do radar Hi-Link HLK-LD2451 (RC2412 -> AC635N) sem pino de Chip Select (CS).

Esta implementação elimina completamente o risco **R1** (taxas de clock acima de 1 MHz), operando com folga até **25 MHz** com zero sobrecarga de interrupção na CPU.

---

## 1. Conexões de Hardware

| Sinal Radar | Pino HLK-LD2451 | Pino RP2040 / Pico | Notas |
|---|---|---|---|
| **SPICLK** | **PP0** (PB0 AC635N) | **GPIO 2** (Pino 4) | Linha de clock master |
| **SPIDI** | **PP2** (PB2 AC635N) | **GPIO 3** (Pino 5) | Dados brutos ADC (int8) |
| **GND** | **GND** | **GND** (Pino 3 ou 8) | Referência comum obrigatória |

> ⚠️ **Nível Lógico (R2):** O Pico opera nativamente em 3,3 V. Se a medição no pino PP0 indicar 1,8 V, utilize um level shifter unidirecional veloz (ex.: 74LVC245 ou TXS0108E).

---

## 2. Como Funciona

- **Máquina de Estado PIO (`spi_slave_mode1.pio`)**:
  - `wait 1 gpio 2`: sincroniza na borda de subida do SCLK.
  - `wait 0 gpio 2`: detecta a borda de descida (ponto exato de amostragem do Modo 1).
  - `in pins, 1`: amostra o bit de DI diretamente no registrador ISR.
  - Autopush configurado a cada 8 bits (1 byte) para o RX FIFO do PIO.
- **DMA (Direct Memory Access)**:
  - Transfere bytes do RX FIFO diretamente para buffers em RAM em blocos de 16.448 bytes (64 chirps × 257 B).
- **Core 1 (Dual-Core RP2040)**:
  - Envia os pacotes completos via USB CDC (Serial) sem interferir na captura contínua de alta velocidade.
- **Medidor de Frequência de Hardware**:
  - Ao inicializar, utiliza um contador de bordas PWM no GPIO 2 para medir e imprimir a taxa exata do clock em MHz.

---

## 3. Como Compilar

```bash
# Clone ou aponte o pico-sdk
export PICO_SDK_PATH=/caminho/para/pico-sdk

mkdir build && cd build
cmake ..
make -j4
```

O arquivo binário gerado será `rp2040_spi_sniffer.uf2`.

Para gravar:
1. Segure o botão **BOOTSEL** do Raspberry Pi Pico e conecte o cabo USB ao computador.
2. Arraste o arquivo `rp2040_spi_sniffer.uf2` para a unidade de disco virtual que aparecer (`RPI-RP2`).
3. O Pico reiniciará imediatamente como um dispositivo serial USB (`/dev/ttyACM0`).

---

## 4. Captura e Processamento no PC / Host

```bash
# Captura 1 ou mais cubos do sniffer USB
python3 tools/capture_cube.py /dev/ttyACM0

# Processa e gera o mapa Range-Doppler e Range Profile
python3 tools/plot_rd.py cube_000000_samples.bin --csv rd.csv --profile-csv profile.csv
```
