# Protocolo SPI1 — ligação com o radar (RC2412FR → AC635N)

★ A interface física do radar. Tudo aqui foi **verificado no registo `SPI1_CON`** e no
ISR, não inferido.

---

## 1. Configuração de SPI1 — rotina `0x1E14D64`

`SPI1` fica em `0x1E1D00` (`JL_SPI1_BASE = ls_base + map_adr(0x1d, 0)`).

```asm
1e14d64: 79 04              [--sp] = {rets, r9-r4}
1e14d66: c8 ff 70 ef e1 01  r8 = 31584112     ; 0x1E1EF70
1e14d6c: 40 e0 e1 29        r0 = 10721        ; offset da tabela spi_io
1e14d70: b4 e0 80 40        r4 = r8 + r0      ; 0x1E21951
1e14d74: 09 e1 02 40        r9 = r4 + 2
1e14d78: 40 21              r0 = 1
1e14d7a: 51 80              call 0x1E14CBC    ; setup de pinos
   …
1e14d98: c6 ff 00 1d 1e 00  r6 = 1973504      ; ★ 0x1E1D00 = SPI1
1e14d9e: 00 ef 00 fe        [r6+0] &= 0xFFFFFFFE  ; bit0  SPIE=0
   …  (configuração de pinos GPIO a partir de spi_io)
1e14dae: 00 ef 08 60        [r6+0] |= 0x8         ; bit3  BIDIR=1
1e14db2: c0 ef 40 6e        [r6+0] &= 0xFFFFF3FF  ; bits10-11 DATW=00 (1 bit)
1e14dd8: c0 ef 04 60        [r6+0] &= 0xFFFFFFFB  ; ★ bit2 CSE=0
1e14ddc: 00 ef 02 60        [r6+0] |= 0x2         ; ★ bit1 SLAVE=1
1e14de0: 00 ef 10 60        [r6+0] |= 0x10        ; bit4  SE=1
1e14de4: 00 ef 20 60        [r6+0] |= 0x20        ; bit5  UE=1
1e14de8: 00 ef 80 60        [r6+0] |= 0x80        ; bit7  CSID=1
1e14dec: c0 ef 40 60        [r6+0] &= 0xFFFFFFBF  ; ★ bit6  CKID=0
1e14df0: 00 ef 00 6c        [r6+0] |= 0x4000      ; bit14 PCLR
1e14df4: c0 ff 48 42 00 00  r0 = 16968         ; 0x4248
1e14dfa: 12 f1 7d 8b        r2 = r8 + 7037      ; 0x1E20AED
1e14dfe: 04 60              r4 = [r0+0]
1e14e00: 40 21              r0 = 1
1e14e02: 43 16              r3 = r4
1e14e04: bf ea 4c bb        call -35176 <0x1E0C4A0>   ; config de clock
1e14e08: e0 e0 cf 6c        r0 = r6 + 0x6780
1e14e0c: 00 e9 07 40        if (r4 >= r0) goto 0x1e14e1e
1e14e14: e5 61              [r6+4] = r5         ; SPI1_BAUD = 0
1e14e18: bf ea 42 bb        call -35196 <0x1E0C4A0>
1e14e1e: f4 e1 40 00        r0 = r4 / r0 (u)    ; ÷4
1e14e22: f8 3f              r0 += -1
1e14e24: e0 61              [r6+4] = r0        ; SPI1_BAUD
1e14e26: 40 20              r0 = 0
1e14e28: e0 62              [r6+8] = r0        ; SPI1_ADR = 0
1e14e2a: 00 ef 01 60        [r6+0] |= 0x1       ; bit0  SPIE=1
1e14e2e: 00 ef 00 6d        [r6+0] |= 0x2000    ; bit13 IE=1
1e14e32: c2 ff 6e 14 e1 01  r2 = 31528046     ; ★ 0x1E1146E  handler do IRQ
1e14e38: 40 2f              r0 = 15             ; IRQ 15
1e14e3a: 41 20              r1 = 0
1e14e3c: bf ea e5 c2        call -31286 <0x1E0D40A>   ; regista IRQ 15
```

### Interpretação dos bits (`SPI1_CON`)

| Bit | Mask | Valor | Significado (manual AC635N §9.4.1) |
|---|---|---|---|
| 0 | `0x1` | **1** | SPIE — SPI habilitado |
| 1 | `0x2` | **1** | **SLAVE — o AC635N é escravo**; o RC2412FR é o master |
| 2 | `0x4` | **0** | **CSE — SPICS NÃO é usado ⇒ não há pino de CS** |
| 3 | `0x8` | **1** | BIDIR — modo bidirecional 1 bit (fio único) |
| 4 | `0x10` | **1** | SE — amostragem na borda de **subida** do SPICK |
| 5 | `0x20` | **1** | UE — actualização do dado na **subida** |
| 6 | `0x40` | **0** | CKID — SPICK ocioso em **BAIXO** ⇒ CPOL = 0 |
| 7 | `0x80` | 1 | CSID — SPICS ocioso em alto (irrelevante, CSE=0) |
| 10-11 | `0xC00` | 00 | DATW — largura de **1 bit** |
| 13 | `0x2000` | 1 | IE — interrupção habilitada |
| 15 | `0x8000` | — | PND — flag de pedido de interrupção |

**Resultado:** **SPI modo 1 (CPOL=0, CPHA=1)**, 1 bit, single-wire, **sem CS**.

> `SPI1_BAUD` ([r6+4]) é irrelevante em modo slave — o clock vem do RC2412FR.
> A taxa real precisa ser medida na bancada.

---

## 2. Pinos

Da tabela `spi_io` do SDK (`struct spi_io { u8 cs_pin, di_pin, do_pin, clk_pin, d2_pin,
d3_pin; }`) e do **mapa de pinos do manual AC635N**:

| Sinal | Pino | Alias no manual | Nota |
|---|---|---|---|
| SPI1 CLK | **PB0** | `PP0` (SPI1CLKA) | saída do RC2412FR |
| SPI1 DI/DO | **PB2** | `PP2` (SPI1DIA) | barramento single-wire (BIDIR) |
| SPI1 DO | PB1 | `PP1` (SPI1DOA) | não usado neste barramento |
| CS | — | — | **inexistente** (CSE=0) |

Configuração declarada em `top/isd_config.ini`: `SPI 2_3_0_0`, host UART em
`UTTX=PA05`, `UTRX=PB05`, `RESET=PB01`, **baud 1 000 000**.

---

## 3. ISR do SPI1 — `0x1E1146E`

### Setup do DMA — `0x1E1144E`

```asm
1e1144e: c0 ff 00 1d 1e 00  r0 = 0x1E1D00
1e11454: 00 ef 80 0d        [r0+0] |= 0x1000   ; bit12 DIR=1 (RX)
1e11458: 41 e0 43 40        r1 = 16451         ; 0x4043
1e1145c: c2 ff 71 9d 01 00  r2 = 105841        ; 0x19D71
1e11462: 21 18              r1 += r2           ; ★ 0x1DDB4 (staging)
1e11464: 41 f0 01 01        r1 = 257
1e11468: 81 63              [r0+12] = r1       ; SPI1_ADR = 257
1e1146a: 81 64              [r0+16] = r1       ; SPI1_CNT = 257
1e1146c: 80 00              rts
```

### Handler

```asm
1e1146e: e9 04              [--sp] = {psr, rets, reti}
1e11470: d8 e8 7f 00        [--sp] = {r6-r0}
1e11474: c0 ff 00 1d 1e 00  r0 = 0x1E1D00
1e1147a: 01 60              r1 = [r0+0]
1e1147c: 51 e8 37 78        if ((r1 & 32768) == 0) goto 0x1e114ee  ; PND?
1e11480: 00 ef 80 0c        [r0+0] |= 0x4000   ; limpa PND
1e11484: 71 84              call -56 <0x1E1144E>  ; (re)configura o DMA
1e11486: 40 e0 43 40        r0 = 16451         ; 0x4043
1e1148a: c5 ff 71 9d 01 00  r5 = 105841        ; 0x19D71
1e11490: d8 ee 50 10        r1 = b[r5+r0] (u)  ; ★ header do frame (0x1DDB4)
1e11494: c4 ff 30 e2 01 00  r4 = 123440        ; 0x1E230  ctx do radar
1e1149a: 93 a7              r3 = r1 >> 7       ; ★ bit7 = STATUS
1e1149c: 76 f1 c0 10        r6 = r1 & 0x3F     ; ★ bits0-5 = ÍNDICE DO CHIRP
1e114a0: 4a 41              r2 = b[r4+1] (u)   ; ctx+1 = índice esperado
1e114a2: db 42              b[r5+2] = r3       ; guarda status em 0x19D73
1e114a4: 51 1c              if (r6 != r2) goto 0x1e114d4   ; índice fora de ordem
1e114a8: 51 8c  (r1 = r5 + r0 → 0x1DDB4)
1e114aa: 40 e0 01 01        r0 = 257
1e114ae: 60 1b              r0 *= r6           ; 257 * idx
1e114b0: 50 18              r0 += r5           ; + 0x19D71
1e114b2: c0 23              r0 += 3            ; ★ dest = 0x19D74 + idx*257
1e114b4: 42 e0 01 01        r2 = 257
1e114b8: 98 ea 76 09        call 3150572 <0x21127A8>   ; memcpy 257 bytes
1e114bc: 68 81              r0 = r6 + 1
1e114be: 01 d7              r1 = r0.b0 (u)
1e114c0: c8 41              b[r4+1] = r0       ; ctx+1 = idx+1
1e114c2: 31 e8 40 c0        if (r1 == 64) {
1e114c6: 40 20                r0 = 0
1e114c8: c8 41                b[r4+1] = r0     ; ctx+1 = 0
1e114ca: 40 21                r0 = 1
1e114cc: d8 40                b[r5+0] = r0     ; ★ 0x19D71 = 1 → cubo completo
                              }
1e114ce: 53 ea 00 40        [r4+76] = 0x0
1e114d2: 04 8d              goto 0x1e114ce
1e114d4: d0 ec 4c 04        r0 = [r4+76]
1e114d8: c0 21              r0 += 1
1e114da: d0 ec 4d 04        [r4+76] = r0
1e114de: a0 f9 06 5a        if (r0 < 301) goto 0x1e114ce
1e114e2: 40 21              r0 = 1
1e114e4: d8 41              b[r5+1] = r0       ; ★ 0x19D72 = 1 → flag de erro
1e114e6: 40 20              r0 = 0
1e114e8: c8 41              b[r4+1] = r0
1e114ea: d0 ec 4d 04        [r4+76] = r0
1e114ee: d4 e8 7f 00        {r6-r0} = [sp++]
1e114f2: a9 04              {psr, rets, reti} = [sp++]
1e114f4: 81 00              rti
```

---

## 4. Formato do frame SPI — 257 bytes

| Offset | Tamanho | Conteúdo |
|---|---|---|
| 0 | 1 | **header**: bits 0–5 = índice do chirp (0..63) · **bit 7 = status** · bit 6 não usado |
| 1 | 256 | **amostras ADC int8** (com sinal) do chirp |

Derivação: `idx = header & 0x3F` (instrução `1e1149c`) e `status = header >> 7`
(instrução `1e1149a`, guardado em `0x19D73`).

> ★ **O byte 0 NÃO é 0x00.** Para o chirp 0 vale `0x00` **ou `0x80`** (se o bit de status
> estiver setado). Comparar o byte com `0x00` **perde frames**.
> **Use `header & 0x3F`** e exija a progressão `0,1,2,…,63`.

### Layout em RAM

```
0x19D71  [0] = 1 quando os 64 chirps chegaram   (flag "cubo completo")
0x19D72  [1] = 1 em caso de erro de sequência
0x19D73  [2] = bit de status do último header
0x19D74  +0*257   frame 0 : [header][256 amostras int8]
          +1*257   frame 1
          …
          +63*257  frame 63
0x1DDB4  staging do frame recebido pelo SPI (257 bytes)
```

---

## 5. Implicações para o sniffer

1. **Sem CS** → o driver `spi_slave` do ESP32-S3 não funciona (exige bordas de CS).
2. **Modo 1** → amostrar o dado na **borda de descida** do clock (o dado é estável entre
   a subida e a descida).
3. **Byte 0 é header** → descartar; o payload são os 256 bytes seguintes.
4. **Amostras são reais (int8)**, não I/Q. O I/Q complexo é o **resultado** da FFT.

---

## 6. Referência rápida

```c
/* Reconstrução do cubo a partir do fluxo SPI bruto */
#define FRAME_LEN 257
#define CHIRPS    64
for (c = 0; c < CHIRPS; c++) {
    uint8_t hdr = stream[c * FRAME_LEN];
    if ((hdr & 0x3F) != c) { /* frame fora de ordem */ }
    memcpy(cube + c * 256, stream + c * FRAME_LEN + 1, 256);
}
```
