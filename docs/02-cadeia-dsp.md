# Cadeia DSP — desmontagem anotada

Toda a cadeia foi decodificada instrução a instrução a partir de `app_objdump.txt`
(61 478 linhas, objdump oficial JieLi com `-mcpu=r3`).

## Visão geral

```
amostras int8  0x15B60  (64 chirps × 256)
   │
   │  janela  0x1E21F84 (256 float32)
   │  × amostra (itof)
   ▼
buffer complexo  0x15360  (256 complex)
   │
   │  FFT 256 pontos  →  0x1E15480
   ▼
65 bins de range por chirp, complexos
   │
   │  FFT 64 pontos sobre os 64 chirps (Doppler)
   │  janela Doppler  0x1E21E84 (64 float32)
   ▼
Range-Doppler complexo  0xCF60  (65 × 64 × 2 float32)
   │
   │  magnitude = sqrt(re² + im²)
   ▼
magnitude  0x4C60  (65 × 64 float32)
```

---

## 1. Cópia do buffer bruto → cubo packed — `0x1E14E46`

```asm
1e14e46: 76 04              [--sp] = {rets, r6-r4}
1e14e48: c0 ff 75 9d 01 00  r0 = 105845      ; 0x19D75  (amostras, pula o header)
1e14e4e: 41 20              r1 = 0            ; contador de chirp
1e14e50: c2 ff 60 5b 01 00  r2 = 88928       ; 0x15B60  (destino)
1e14e58: 43 e0 00 01        r3 = 256          ; bytes por linha
1e14e5c: 04 16              r4 = r0           ; src corrente
1e14e5e: 25 16              r5 = r2           ; dst corrente
1e14e60: 04 8e              goto 0x1e14e68
1e14e62: 46 07              r6 = b[r4++=1] (u)  ; lê 1 byte do src
1e14e64: d6 07              b[r5++=1] = r6      ; escreve no dst
1e14e68: 3f 3c              if (r3 != 0) goto 0x1e14e62
1e14e6a: 00 e1 01 01        r0 = r0 + 257     ; ★ src stride 257 (pula o header)
1e14e6e: 02 e1 00 21        r2 = r2 + 256     ; ★ dst stride 256 (empacotado)
1e14e72: c1 21              r1 += 1
1e14e74: 81 f8 f0 81        if (r1 != 64) goto 0x1e14e58
1e14e78: 56 04              {pc, r6-r4} = [sp++]
```

**Resultado:** `0x15B60` contém os **16 384 bytes** do cubo 64×256 int8, **contíguos e
sem headers** — exactamente o que a Via B (patch) envia pela UART.

---

## 2. Janela + FFT de range — `0x1E15B5E`

### Prólogo

```asm
1e15b5e: 7f 04              [--sp] = {rets, r15-r4}
1e15b60: f0 e8 f8 1d        sp += -520
1e15b64: f8 e8 00 01        r0 = sp + 256
```

> ⚠️ Este prólogo tem 6 bytes — por isso um hook de 4 bytes na entrada da função o
> destruiria. Ver [`06-patch-de-firmware.md`](06-patch-de-firmware.md).

### Constantes

```asm
1e15b74: c0 ff 60 cf 00 00  r0 = 53088        ; 0xCF60
1e15b7a: 09 e1 04 02        r9 = r0 + 516     ; destino do range FFT
1e15b7e: ca ff 60 5b 01 00  r10 = 88928       ; 0x15B60  amostras int8 do cubo
1e15b84: c8 ff 70 ef e1 01  r8  = 31584112    ; 0x1E1EF70 (base de globals)
1e15b8a: c4 ff 60 53 01 00  r4  = 86880       ; 0x15360  buffer complexo
1e15b90: 46 e0 05 0c        r6  = 3077        ; offset da tabela de janela
1e15b94: c3 14              r11 = 0           ; contador de chirp
```

A tabela de janela é `0x1E1EF70 + 3077*4 = 0x1E21F84`.

### Loop por chirp (0..63)

```asm
1e15b98: 40 20              r0 = 0            ; offset do byte (0..1020)
1e15b9a: a1 16              r1 = r10          ; cursor nas amostras
1e15b9c: 42 16              r2 = r4           ; cursor no buffer complexo
1e15b9e: 04 8e              goto 0x1e15bbc
1e15ba0: b4 e0 00 38        r3 = r0 + r8      ; 0x1E1EF70 + offset
1e15ba4: d4 ee 11 70        r7 = b[r1++=1] (s)   ; ★ amostra int8 COM SINAL
1e15ba8: d8 ec 3a 36        r3 = [r3 + r6<<2]    ; ★ coeficiente da janela (float)
1e15bac: 3f e5 8f 77        r7 = itof(r7)        ; int8 → float
1e15bb0: 3f e5 72 33        r3 = r7 * r3 (f)     ; ★ amostra × janela
1e15bb4: 22 eb 28 00        [r2++] = {r5, r3}   ; store complexo
1e15bb8: c0 24              r0 += 4
1e15bba: c2 28              r2 += 8
1e15bbc: 01 ff 00 04 ef ff  if (r0 != 1024) goto 0x1e15ba0   ; 256 iterações
```

### Chamada da FFT

```asm
1e15bc2: 00 e1 0c 85        r0 = r8 + 1292    ; 0x1E1F474  params da FFT
1e15bc6: 41 16              r1 = r4           ; 0x15360    buffer
1e15bc8: bf ea 5a fc        call -1868 <0x1E15480>   ; ★ FFT de 256 pontos
```

### Cópia da saída (65 bins por chirp)

```asm
1e15bcc: 40 e0 f8 fd        r0 = -520
1e15bd0: 91 16              r1 = r9
1e15bd2: 04 89              goto 0x1e15be6
1e15bd4: 02 1d              r2 = r0 + r4
1e15bd6: d2 ec 20 31        r3 = [r2+528]
1e15bda: d2 ec 24 21        r2 = [r2+532]
1e15bde: 93 7f              [r1+-4] = r3
1e15be0: da ec 11 20        [r1++=512] = r2
1e15be4: c0 28              r0 += 8
1e15be6: f0 56              if (r0 != 0) goto 0x1e15bd4
1e15be8: 09 e1 08 90        r9 = r9 + 8       ; avança 8 bytes por chirp
1e15bec: 0a e1 00 a1        r10 = r10 + 256   ; avança 256 amostras por chirp
1e15bf0: 0b e1 01 b0        r11 = r11 + 1
1e15bf4: 8b f8 d0 81        if (r11 != 64) goto 0x1e15b98
```

---

## 3. FFT de Doppler + magnitude — a partir de `0x1E15BF8`

```asm
1e15bf8: c0 ff 60 cf 00 00  r0 = 53088        ; 0xCF60
1e15bfe: 09 e1 04 02        r9 = r0 + 516
1e15c02: ca ff 60 4c 00 00  r10 = 19552       ; 0x4C60  ← magnitude
1e15c08: 4b e0 01 00        r11 = 1           ; contador de range gate (1..65)
1e15c0c: 46 20              r6 = 0
1e15c0e: ed e0 72 55        r13 = r5 + 0x3C800000   ; 1.0f
1e15c12: 4f e0 c5 0b        r15 = 3013        ; offset da janela Doppler
```

Janela Doppler: `0x1E1EF70 + 3013*4 = 0x1E21E84` (64 float32, pico 0.99943).

**Soma sobre os 64 chirps** (por bin de range):

```asm
1e15c18: 50 20              r0 = 64
1e15c1a: 91 16              r1 = r9
1e15c1c: 42 20              r2 = 0
1e15c1e: 04 88              goto 0x1e15c30
1e15c20: 13 60              r3 = [r1+0]       ; parte real
1e15c22: 3f f5 20 23        r2 = r2 + r3 (f)
1e15c26: 14 7f              r4 = [r1+-4]      ; parte imaginária
1e15c28: 3f e5 50 54        r5 = r5 + r4 (f)
1e15c2c: f8 3f              r0 += -1
1e15c2e: c1 28              r1 += 8
1e15c30: f0 57              if (r0 != 0) goto 0x1e15c20
```

**Multiplicação complexa pela janela Doppler** (64 iterações):

```asm
1e15c40: b4 f0 10 38        r3 = r1 + r8
1e15c44: 24 7f              r4 = [r2+-4]
1e15c46: d8 ec 3a 3f        r3 = [r3 + r15<<2]   ; janela Doppler
1e15c4a: 3f e5 41 45        r4 = r4 - r5 (f)
1e15c4e: 3f e5 42 43        r4 = r4 * r3 (f)
1e15c52: a4 7f              [r2+-4] = r4
1e15c54: 24 60              r4 = [r2+0]
1e15c56: 3f e5 41 40        r4 = r4 - r0 (f)
1e15c5a: 3f e5 32 34        r3 = r3 * r4 (f)
1e15c5e: d8 ec 29 30        [r2++=8] = r3
1e15c62: c1 24              r1 += 4
1e15c64: a1 f8 ec 01        if (r1 != 256) goto 0x1e15c40
```

**FFT de 64 pontos** (por bin de range):

```asm
1e15c68: c0 e1 b9 00        r0 = r11 << 9     ; gate * 512 bytes
1e15c6c: c1 ff 60 cf 00 00  r1 = 53088        ; 0xCF60
1e15c72: 0c 1c              r4 = r0 + r1
1e15c74: 00 e1 fc 84        r0 = r8 + 1276    ; 0x1E1F46C  params
1e15c78: 41 16              r1 = r4
1e15c7a: bf ea 01 fc        call -2046 <0x1E15480>   ; ★ FFT de 64 pontos
```

**Cópias e magnitude** (`0x1E15C7E`–`0x1E15CD2`): três `memcpy` de 256 floats
(`0x21127A8`) e depois

```asm
1e15cb0: 42 61              r2 = [r4+4]
1e15cb2: d8 ec 48 30        r3 = [r4++=8]
1e15cb6: 3f e5 22 22        r2 = r2 * r2 (f)
1e15cba: 3f e5 32 33        r3 = r3 * r3 (f)
1e15cbe: 3f e5 30 22        r2 = r3 + r2 (f)   ; re² + im²
1e15cc2: 92 ed 80 06        if (r2 u< r6) { r2 = 0 }
1e15cc8: 92 60              [r1+0] = r2        ; magnitude
1e15cca: c0 24              r0 += 4
1e15cd0: a0 f8 ed 01        if (r0 != 256) goto 0x1e15bae
```

**Escrita na magnitude final** (`0x4C60`):

```asm
1e15cd4: 40 20              r0 = 0
1e15cd6: a1 16              r1 = r10          ; 0x4C60 + 256*gate
1e15cd8: 04 86              goto 0x1e15ce6
1e15cda: f8 e8 00 21        r2 = sp + 256
1e15cde: d8 ec 2a 20        r2 = [r2+r0<<2]
1e15ce2: 92 05              [r1++=4] = r2
1e15ce4: c0 21              r0 += 1
1e15ce6: 80 f8 f8 81        if (r0 != 64) goto 0x1e15cda
1e15cea: 0a e1 00 a1        r10 = r10 + 256   ; próximo gate
1e15cee: 09 e1 00 92        r9 = r9 + 512
1e15cf2: 0b e1 01 b0        r11 = r11 + 1
1e15cf6: 8b f8 8f 85        if (r11 != 66) goto 0x1e15c18   ; 65 gates
```

**Resultado:** `0x4C60` ← 65 linhas × 64 float32 = **magnitude Range-Doppler**.

---

## 4. Tabela de janelas — verificação empírica

Extraindo os float32 do binário:

```
janela de range  @0x1E21F84 (256 floats):
  [0.000149, 0.000598, 0.001344, 0.002389, 0.003731, 0.00537, 0.007304, 0.009533, ...]
  [0.999664, 0.999963, 0.999963, 0.999664, ...]   (meio)
  [..., 0.00537, 0.003731, 0.002389, 0.001344, 0.000598, 0.000149]   (final)
  → simétrica, pico 0.99996 no índice 127/128  ⇒ tipo HANN

janela Doppler  @0x1E21E84 (64 floats):
  [0.08, 0.08229, 0.08912, 0.10044, 0.11612, 0.13602, 0.15993, 0.18762, ...]
  [0.99943, 0.99943, 0.99486, ...]
  → pico 0.99943
```

---

## 5. Reimplementação em Python (`tools/plot_rd.py`)

`tools/plot_rd.py` reproduz exactamente esta cadeia (FFT radix-2 em Python puro, sem
dependências) e produz:

* mapa Range-Doppler 65×64 (ASCII + CSV)
* **Range Profile** — potência média por bin de distância, com detecção do pico
* estatísticas das amostras brutas (min/max/média)

Validado com cubos sintéticos: o pico do Range Profile aparece exactamente no bin de
range onde o alvo foi colocado.
