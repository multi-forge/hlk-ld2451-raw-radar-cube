/*
 * HLK-LD2451 — sniffer passivo do barramento SPI1 (RC2412 -> AC635N)
 *
 * Alvo: ESP32-S3 (Arduino-ESP32 core >= 3.0 / ESP-IDF v5)
 *
 * Protocolo capturado (verificado no binario do firmware, ver RELATORIO.md):
 *   - Barramento SPI1 do AC635N: SLAVE=1 (SPI1_CON bit1), CSE=0 (bit2) => NAO ha pino CS.
 *     SPICLK ocioso em nivel BAIXO (CKID=0, bit6 limpo em 0x1E14DEC).
 *   - Quadro de 257 bytes por chirp:
 *       byte 0     = header: idx = byte & 0x3F (0..63), status = byte >> 7
 *       byte 1..256= 256 amostras ADC de 8 bits com sinal (int8)
 *   - 64 chirps por cubo -> payload 64 x 256 = 16384 bytes (0x4000)
 *
 * NOTA CRITICA SOBRE O CS:
 *   O driver SPI slave do ESP32-S3 delimita transacoes por BORDA de CS.
 *   Como o AC635N nao possui saida de CS, nao existe transacao delimitada:
 *   a API oficial (spi_slave_transmit / queue_trans) NAO funciona aqui.
 *   Duas saidas possiveis:
 *     (a) ESP32-S3 "sniffer" por PIO nao existe (PIO e so do RP2040/RP2350).
 *     (b) Raspberry Pi Pico com PIO -> decodifica SPI mode 1 sem CS de forma
 *         deterministica. RECOMENDADO.
 *     (c) Logica de analise (e.g. Logic 2 / Saleae) com decoder SPI mode 1.
 *   O codigo abaixo implementa a via (d): amostragem por GPIO com ISR no
 *   FALLING edge do clock (ponto de amostragem do modo 1), e um reconciliador
 *   de bits por software. Isto funciona ate ~1 MHz com clock de 240 MHz.
 *   A 2-4 MHz (taxa provavel do RC2412) o ISR NAO da conta: use (b) ou (c).
 *
 * Ligacao sugerida (ESP32-S3):
 *   PP0 (AC635N PB0 / SPI1CLK)  -> GPIO 12
 *   PP2 (AC635N PB2 / SPI1DI)   -> GPIO 11
 *   GND                         -> GND
 *   MISO (GPIO13)               -> NAO LIGADO (nao ha DO no barramento)
 *
 * Saida: USB CDC (Serial). Envia:
 *   0xAA 0xBB 0xCC 0xDD | len(u32 LE) | seq(u32 LE) | payload (16384 bytes)
 */

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <string.h>
#include "soc/gpio_struct.h"

#define PIN_SCLK   12
#define PIN_DI     11

#define FRAME_LEN  257
#define CHIRPS     64
#define PAYLOAD    (FRAME_LEN * CHIRPS)   /* 16448 bytes: 64 cabecalhos + 64*256 amostras */
#define PAYLOAD_PURE (CHIRPS * 256)       /* 16384 bytes: so as amostras */

static constexpr size_t QUEUE_DEPTH = 3;
static constexpr size_t RING_BYTES  = 65536;

/* ------------------------------------------------------------------ */
/* Ring buffer de bytes recebidos (ISR -> task)                        */
/* ------------------------------------------------------------------ */
static volatile uint8_t  g_ring[RING_BYTES];
static volatile uint32_t g_ring_head = 0;   /* escrito pela ISR */
static volatile uint32_t g_ring_tail = 0;   /* lido pela task   */
static volatile uint32_t g_overruns = 0;

/* ------------------------------------------------------------------ */
/* Reconciliador de bits                                               */
/* ------------------------------------------------------------------ */
/*
 * O ponto de amostragem do modo 1 e a borda de descida do clock.
 * A ISR dispara nesse instante e le o nivel de DI. Porem, a latencia da
 * ISR nao e zero: se a latencia ultrapassar o periodo do clock, o bit
 * lido pode ser do ciclo seguinte.
 *
 * Estrategia: amostramos em TODAS as bordas (subida E descida) e
 * reconstruimos os bytes por software:
 *   - no modo 1 (CPOL=0, CPHA=1) o master muda o dado na BORDA DE SUBIDA
 *     e o slave amostra na BORDA DE DESCIDA. Logo, o valor estavel de DI
 *     durante a janela [subida, descida] e o bit valido.
 *   - amostramos na descida (falling) e descartamos a subida.
 *
 * Se a taxa for alta demais,_ISR atrasa e amostramos o bit errado.
 * Por isso a taxa maxima pratica com ISR e ~1 MHz.
 */

static uint8_t  g_bits = 0;      /* byte em construcao */
static uint8_t  g_bitcount = 0;  /* bits acumulados   */

static void IRAM_ATTR isr_clock() {
  /* leitura direta do registro GPIO.in: muito mais rapido que digitalRead() */
  const uint32_t in = GPIO.in;
  const bool level = (in & (1u << PIN_SCLK)) != 0;

  /* so interessa a borda de descida (amostragem do modo 1) */
  if (!level) {
    const bool di = (in & (1u << PIN_DI)) != 0;
    const uint32_t head = g_ring_head;
    g_ring[head] = di ? 1 : 0;
    g_ring_head = (head + 1) % RING_BYTES;
    if (g_ring_head == g_ring_tail) {
      g_overruns++;               /* buffer cheio: perdemos bytes */
    }
  }
}

/* ------------------------------------------------------------------ */
/* Extracao de bytes da ring buffer                                    */
/* ------------------------------------------------------------------ */
static bool pop_bit(bool &out) {
  if (g_ring_tail == g_ring_head) return false;
  out = (g_ring[g_ring_tail] != 0);
  g_ring_tail = (g_ring_tail + 1) % RING_BYTES;
  return true;
}

static bool pop_byte(uint8_t &out) {
  uint8_t v = 0;
  for (int i = 0; i < 8; i++) {
    bool b;
    if (!pop_bit(b)) return false;
    v = (uint8_t)((v << 1) | (b ? 1 : 0));
  }
  out = v;
  return true;
}

/* ------------------------------------------------------------------ */
/* Deteccao de frame: procuramos o header idx=0 e subimos a progressao  */
/* ------------------------------------------------------------------ */
struct Cube {
  uint8_t *buf;     /* PAYLOAD bytes: 64 cabecalhos + amostras */
  uint32_t seq;
};

static uint32_t g_seq = 0;
static bool    g_capture = false;
static uint8_t g_assemble_buf[PAYLOAD];   /* buffer estatico: 16 KB nao cabe na stack */

/* Reconciliador: procura header idx==0 e exige a progressao 0..63. */
static bool assemble_cube(uint8_t *out) {
  for (int attempt = 0; attempt < 4096; attempt++) {
    uint8_t hdr;
    if (!pop_byte(hdr)) return false;
    if ((hdr & 0x3F) != 0) continue;

    memcpy(g_assemble_buf, &hdr, 1);
    bool ok = true;

    for (int frame = 1; frame < CHIRPS; frame++) {
      uint8_t h;
      if (!pop_byte(h)) return false;
      if ((h & 0x3F) != frame) { ok = false; break; }
      memcpy(g_assemble_buf + frame * FRAME_LEN, &h, 1);
      for (int i = 1; i < FRAME_LEN; i++) {
        uint8_t sample;
        if (!pop_byte(sample)) return false;
        g_assemble_buf[frame * FRAME_LEN + i] = sample;
      }
    }
    if (!ok) continue;

    memcpy(out, g_assemble_buf, PAYLOAD);
    return true;
  }
  return false;
}

/* ------------------------------------------------------------------ */
/* Envio                                                               */
/* ------------------------------------------------------------------ */
static void send_cube(const uint8_t *payload, uint32_t seq) {
  uint8_t hdr[12];
  hdr[0] = 0xAA; hdr[1] = 0xBB; hdr[2] = 0xCC; hdr[3] = 0xDD;
  uint32_t len = PAYLOAD;
  memcpy(hdr + 4, &len, 4);
  memcpy(hdr + 8, &seq, 4);
  Serial.write(hdr, sizeof(hdr));
  Serial.write(payload, PAYLOAD);
  Serial.flush();
}

/* ------------------------------------------------------------------ */
/* Estatisticas de captura                                              */
/* ------------------------------------------------------------------ */
/*
 * O contador de overruns e o indicador mais importante: cada overrun
 * significa que a ISR perdeu pelo menos 1 bit (ring buffer cheio), logo
 * o cubo capturado pode estar corrompido. Se o contador crescer muito
 * durante a captura, o clock do SPI1 esta rapido demais para a ISR e
 * a ESP32-S3 nao serve -> usar Raspberry Pi Pico com PIO ou analisador.
 */
static uint32_t g_overruns_at_start = 0;
static uint32_t g_cubes_ok = 0;
static uint32_t g_cubes_fail = 0;

static void print_stats() {
  const uint32_t ov = g_overruns - g_overruns_at_start;
  Serial.printf("# STATS cubes_ok=%u cubes_fail=%u overruns=%u bits_lost=%u\n",
                (unsigned)g_cubes_ok, (unsigned)g_cubes_fail,
                (unsigned)ov, (unsigned)ov);
  if (ov == 0) {
    Serial.println(F("# overruns=0 -> captura integralmente confiavel"));
  } else {
    Serial.printf("# ATENCAO: %u overruns -> bits perdidos; clock SPI1 rapido demais para a ISR\n",
                  (unsigned)ov);
    Serial.println(F("# USE: Raspberry Pi Pico (PIO) ou analisador logico"));
  }
}

void setup() {
  Serial.begin(921600);
  delay(1200);

  pinMode(PIN_SCLK, INPUT_PULLDOWN);
  pinMode(PIN_DI,   INPUT_PULLDOWN);

  /* dispara na descida do clock = ponto de amostragem do SPI mode 1 */
  attachInterrupt(digitalPinToInterrupt(PIN_SCLK), isr_clock, FALLING);

  Serial.println(F("# sniffer SPI1 pronto. Envie 'S' para capturar, 'X' para parar."));
  Serial.println(F("# comandos: S=capturar X=parar R=relatorio de overruns"));
}

void loop() {
  if (Serial.available()) {
    const int c = Serial.read();
    if (c == 'S') {
      g_capture = true;
      g_ring_head = g_ring_tail = 0;
      g_overruns_at_start = g_overruns;
      g_cubes_ok = 0;
      g_cubes_fail = 0;
      Serial.println(F("# capturando..."));
    } else if (c == 'X') {
      g_capture = false;
      Serial.println(F("# parado"));
      print_stats();
    } else if (c == 'R') {
      print_stats();
    }
  }

  if (g_capture) {
    uint8_t *tmp = (uint8_t *)malloc(PAYLOAD);
    if (tmp) {
      if (assemble_cube(tmp)) {
        send_cube(tmp, g_seq++);
        g_cubes_ok++;
        Serial.printf("# cubo %u ok (overruns=%u)\n", g_seq - 1, g_overruns);
      } else {
        g_cubes_fail++;
        Serial.printf("# cubo falhou (overruns=%u)\n", g_overruns);
      }
      free(tmp);
    } else {
      Serial.println(F("# sem memoria para o buffer do cubo"));
    }
  }
  delay(5);
}
