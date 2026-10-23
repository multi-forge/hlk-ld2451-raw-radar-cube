/*
 * HLK-LD2451 — Sniffer determinístico SPI1 em Raspberry Pi Pico (RP2040)
 *
 * Captura o barramento SPI1 (RC2412 -> AC635N) sem pino CS a velocidades
 * de até 25 MHz via PIO (Programmable I/O) + DMA.
 *
 * Protocolo de saída (USB CDC / Serial):
 *   0xAA 0xBB 0xCC 0xDD | len(u32 LE = 16448) | seq(u32 LE) | payload (64 x 257 B)
 *
 * Compatível 100% com capture_cube.py e plot_rd.py.
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/pwm.h"
#include "hardware/clocks.h"
#include "spi_slave_mode1.pio.h"

#define PIN_SCLK        2   // PP0 do HLK-LD2451 (PB0 AC635N)
#define PIN_DI          3   // PP2 do HLK-LD2451 (PB2 AC635N)
#define PIN_LED         25  // LED da placa Pico (pisca a cada frame)

#define FRAME_LEN       257
#define CHIRPS          64
#define CUBE_SIZE       (FRAME_LEN * CHIRPS)  // 16448 bytes

#define MAGIC_HEADER    0xDDCCBBAA  // Little-endian para AA BB CC DD

// Buffers de captura em RAM (Ping-Pong)
static uint8_t g_buf[2][CUBE_SIZE] __attribute__((aligned(4)));
static volatile int g_buf_ready = -1;
static volatile uint32_t g_seq = 0;
static volatile uint32_t g_overruns = 0;

// Medição precisa do clock SCLK via contador de pulsos de hardware (PWM counter)
static float measure_sclk_frequency(void) {
    uint slice = pwm_gpio_to_slice_num(PIN_SCLK);
    pwm_config cfg = pwm_get_default_config();
    pwm_config_set_clkdiv_mode(&cfg, PWM_DIV_B_RISING);
    pwm_init(slice, &cfg, false);
    pwm_set_counter(slice, 0);

    pwm_set_enabled(slice, true);
    sleep_ms(100); // Janela de 100 ms
    pwm_set_enabled(slice, false);

    uint16_t count = pwm_get_counter(slice);
    return (float)count * 10.0f; // Multiplica por 10 para obter Hz
}

// Tarefa no Core 1: Envia dados pela USB CDC para não bloquear a captura
static void core1_tx_loop(void) {
    while (true) {
        int buf_idx = g_buf_ready;
        if (buf_idx >= 0) {
            uint8_t *buf = g_buf[buf_idx];
            uint32_t seq = g_seq++;
            g_buf_ready = -1;

            // Transmite cabeçalho do sniffer
            uint32_t hdr[3];
            hdr[0] = MAGIC_HEADER;
            hdr[1] = CUBE_SIZE;
            hdr[2] = seq;

            fwrite(hdr, 1, sizeof(hdr), stdout);
            fwrite(buf, 1, CUBE_SIZE, stdout);
            fflush(stdout);

            gpio_xor_mask(1u << PIN_LED);
        } else {
            sleep_us(500);
        }
    }
}

int main(void) {
    stdio_init_all();

    gpio_init(PIN_LED);
    gpio_set_dir(PIN_LED, GPIO_OUT);
    gpio_put(PIN_LED, 1);

    // Aguarda conexão USB por até 3 segundos
    for (int i = 0; i < 30 && !stdio_usb_connected(); i++) {
        sleep_ms(100);
    }
    gpio_put(PIN_LED, 0);

    printf("# HLK-LD2451 RP2040 PIO SPI1 Sniffer Inicializado\n");

    // Medição preliminar de frequência SCLK (R1)
    float sclk_hz = measure_sclk_frequency();
    printf("# Medição preliminar SCLK: %.2f kHz (%.2f MHz)\n", sclk_hz / 1000.0f, sclk_hz / 1e6f);

    // Configura PIO0
    PIO pio = pio0;
    uint sm = 0;
    uint offset = pio_add_program(pio, &spi_slave_mode1_program);
    spi_slave_mode1_program_init(pio, sm, offset, PIN_SCLK, PIN_DI);

    // Configura DMA
    int dma_chan = dma_claim_unused_channel(true);
    dma_channel_config c = dma_channel_get_default_config(dma_chan);
    channel_config_set_read_increment(&c, false);
    channel_config_set_write_increment(&c, true);
    channel_config_set_dreq(&c, pio_get_dreq(pio, sm, false)); // DREQ no RX FIFO do PIO
    channel_config_set_transfer_data_size(&c, DMA_SIZE_8);

    // Inicia Core 1 para envio USB CDC
    multicore_launch_core1(core1_tx_loop);

    int cur_buf = 0;
    printf("# Iniciando amostragem contínua via PIO + DMA...\n");

    while (true) {
        // Dispara transferência de 1 cubo (16448 bytes) via DMA
        dma_channel_configure(
            dma_chan,
            &c,
            g_buf[cur_buf],         // Destino
            &pio->rxf[sm],          // Origem (RX FIFO do PIO)
            CUBE_SIZE,              // Contagem de bytes
            true                    // Inicia imediatamente
        );

        dma_channel_wait_for_finish_blocking(dma_chan);

        // Se o Core 1 ainda não terminou de enviar o buffer anterior, conta overrun
        if (g_buf_ready >= 0) {
            g_overruns++;
        }
        g_buf_ready = cur_buf;
        cur_buf ^= 1; // Alterna para o outro buffer
    }

    return 0;
}
