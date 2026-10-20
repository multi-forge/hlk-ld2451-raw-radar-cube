# Correções ao briefing original

A engenharia reversa estática do firmware revelou **10 erros** na instrução inicial. Todas
as correções abaixo são verificáveis nos ficheiros citados.

---

## 1. Endereço de entrada da task `app_radar`

**Briefing:** *"`app_radar` começa em `0x1E16692`"*
**Realidade:** a entrada é **`0x1E16DD2`**. `0x1E16692` é código **dentro** do state
machine `0x1E15FD4`.

```asm
1e16dd2: 1e1ef96 ...
```

O loop principal é `0x1E16B3E`.

---

## 2. Endereço da tabela de tasks

**Briefing:** *tabela em `0x1E1EE10`*
**Realidade:** as entradas de 12 bytes começam em **`0x1E1EE14`**. Em `0x1E1EE10` está
o `qsize` da **entrada anterior**.

Formato confirmado: `{ name_ptr, (stack<<16)|priority, qsize }` — **sem ponteiro de
função**. A criação é feita pelo wrapper `0x1E0D462` (procura o nome via `strcmp` em
`0x21127B8` e chama `os_task_create` em `0x2002D58`).

---

## 3. ★ Critério de detecção do header do frame

**Briefing:** *"detectar que o primeiro byte do frame é 0x00 (e depois verificar a progressão
até 0x3F)"*

**Realidade:** o byte 0 **não** é `0x00`. A instrução `1e1149c` prova:

```asm
1e1149c: 76 f1 c0 10        r6 = r1 & 0x3F     ; ★ índice do chirp = byte & 0x3F
1e1149a: 93 a7              r3 = r1 >> 7       ; ★ bit 7 = status (separado)
```

* bits 0–5 = índice do chirp (0..63)
* bit 7 = status, lido **separadamente** e guardado em `0x19D73`
* bit 6 = não usado

Comparar o byte com `0x00` **perde frames** sempre que o bit de status estiver setado
(o chirp 0 pode valer `0x80`).

**Correcção:** usar `header & 0x3F` e exigir a progressão `(header & 0x3F) == 0..63`.

---

## 4. ★ Interrupção de GPIO no clock no ESP32-S3

**Briefing:** *"a ESP32-S3 precisará usar uma interrupção de GPIO no pino de Clock (PB0/PP0)
para ler o pino de Dados (PB2/PP2) bit a bit"*

**Realidade — dois problemas:**

**(a) O driver SPI slave do ESP32-S3 exige bordas de CS.**
Documentação oficial (ESP-IDF `spi_slave`): *"A full-duplex SPI transaction begins when
the Host asserts the CS line… At the end of the transaction, the Host de-asserts the CS
line."* Sem CS não há transacção, e `spi_slave_transmit` nunca retorna (confirmado no
fórum do Espressif).

Isto não é especulação: o registo `SPI1_CON` tem o **bit CSE (bit2) a zero** —
literalmente *"não usar o sinal SPICS"*. **O hardware não tem pino de CS.**
O ESP32 (original) tem `SPI_CS0_DIS` em `SPI_MISC_REG`; o **ESP32-S3 não tem**.

**(b) A taxa de ISR é insuficiente.** Com clock de 2–4 MHz o período é de 250–500 ns; a
latência de uma ISR no ESP32-S3 (240 MHz) é de ~1–2 µs → **4–8× o período**.

**Solução adoptada:** sampling por ISR otimizada (IRAM, `GPIO.in` directo, sem
`digitalRead()`), com reconciliação de bits em software, **limitada a ~1 MHz**. Para
taxas superiores: Raspberry Pi Pico com PIO.

---

## 5. ★ Endereço do payload empacotado

**Briefing:** *"cria um patch que … faça o memcpy desses 16.4 KB e joga na UART0"*, com
`0x19D75` e tamanho `0x4000`

**Realidade:** `0x19D75` tem **stride 257** (1 header + 256 amostras por chirp). Copiar
16 384 bytes a partir daí inclui headers e desalinha a matriz.

O payload **empacotado** (64×256 int8, contíguo) está em **`0x15B60`** — destino da
rotina `0x1E14E46`:

```asm
1e14e48: c0 ff 75 9d 01 00  r0 = 105845      ; 0x19D75  (src, stride 257)
1e14e50: c2 ff 60 5b 01 00  r2 = 88928       ; 0x15B60  (dst, stride 256)
1e14e6a: 00 e1 01 01        r0 = r0 + 257     ; src stride 257
1e14e6e: 02 e1 00 21        r2 = r2 + 256     ; dst stride 256
```

Para enviar os frames **com** headers: `0x19D74 + 0x4040` (16 448 B).

---

## 6. SPI0 não é o link do radar

**Briefing:** *"a hipótese do agente líder de achar `SPI0_ADR` para o radar é provavelmente
incorreta"* — **confirmado**.

SPI0 (`0x1E1C00`) é a **flash serial externa**: a rotina em `0x1E24900` envia os comandos
`0x6B` (write enable), `0x9F` e `0x4B` (page program / read) para
`0x1E246A8`, `0x1E2473A`, `0x1E247C8`.

O radar é **SPI1** (`0x1E1D00`).

---

## 7. `0x1E241D4` é a UART host, não SPI/DMA

**Briefing:** *"`0x1E241D4` … parece dispatch de comandos/tabela, não DMA/SPI"*

**Realidade:** é o **open/init da UART host**. Prova: a task `app_radar` chama-o e logo a
seguir imprime `"UART INITing...baudrate=%d\n"` com o baud de `[0x19B64]`.

Detalhes: seleciona UART0/1/2 por tabelas de 12 entradas em `0x42CC`/`0x42D8`; structs de
device em `0x215C8` (UART0), `0x21604` (UART1), `0x21640` (UART2); IRQ handler
`0x1E23BFC` registado via `0x1E0D40A(18, 3, …)`.

---

## 8. `0x1E2376A` é init de sistema, não do radar

**Briefing:** *"Analisar `0x1E2376A` … para descobrir a inicialização do radar"*

**Realidade:** é **init genérico de sistema/board**:
* o `strcmp` inicial compara uma string vazia (`0x1E1EF96` = null após `"sys"`)
* a flag `[0x215C4]` evita dupla init
* itera a tabela `0x1E23458–0x1E23470` (entradas de 8 bytes): `0x1E17EF0` (rts),
  `0x1E194F2`, `0x1E0F948`
* configura `0x1E000C`, `0x1F0200` (SFC), `0x1E0400`, `0x1E1920`

---

## 9. As amostras são reais, não I/Q

**Briefing:** *"para plotar o sinal I/Q bruto"*

**Realidade:** o ADC entrega **valores reais** (int8). O I/Q complexo é o **resultado**
da FFT de range, em `0x15360` (intermédio) e `0xCF60` (65×64 complexo).

---

## 10. Modo SPI e ausência de CS

**Briefing:** *"SPI 2_3_0_0"* (do `isd_config.ini`) e *"CPOL=0/CPHA=1"*

**Realidade:** o `isd_config.ini` descreve a configuração declarativa; o registo
`SPI1_CON` é a verdade:

```asm
1e14dd8: c0 ef 04 60        [r6+0] &= 0xFFFFFFFB  ; bit2 CSE=0  → SEM CS
1e14ddc: 00 ef 02 60        [r6+0] |= 0x2         ; bit1 SLAVE=1
1e14dec: c0 ef 40 60        [r6+0] &= 0xFFFFFFBF  ; bit6 CKID=0 → CPOL=0
1e14de0: 00 ef 10 60        [r6+0] |= 0x10        ; bit4 SE=1 → amostra na subida
```

→ **modo 1, slave, 1 bit, single-wire, sem CS.** Confirmado.

---

## Resumo

| # | Tema | Impacto se não corrigido |
|---|---|---|
| 1 | entry de `app_radar` | Analyzing the wrong code |
| 2 | tabela de tasks | ler a entrada errada |
| 3 | **header `& 0x3F`** | **perder frames e corromper o cubo** |
| 4 | **ISR vs PIO** | **sniffer não funciona a 2–4 MHz** |
| 5 | **`0x15B60` vs `0x19D75`** | **payload desalinhado / dados corrompidos** |
| 6 | SPI0 = flash | procurar dados no periférico errado |
| 7 | `0x1E241D4` = UART |— |
| 8 | `0x1E2376A` = board init |— |
| 9 | reais ≠ I/Q | esperar I/Q cru inexistente |
| 10 | modo/sem CS | dimensionar o sniffer com premissas erradas |
