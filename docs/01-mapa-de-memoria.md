# Mapa de Memória — HLK-LD2451 (AC635N / BR23)

Todos os endereços verificados contra o binário `app.bin` v1.13 (base `0x1E00120`).

## Referência de espaço de endereçamento

```
hs_base = 0x1F0000      ls_base = 0x1E0000
map_adr(grp, adr) = (64 * grp + adr) * 4
```

| Periférico | Base | Notas |
|---|---|---|
| SPI0 | `0x1E1C00` | **flash serial externa** (comandos `0x6B`/`0x9F`/`0x4B` em `0x1E24900`) |
| SPI1 | `0x1E1D00` | ★ **link do radar** (RC2412FR) |
| SPI2 | `0x1E1E00` | |
| UART0 | `0x1E2000` | link host (protocolo `FD FC FB FA`) |
| UART1 | `0x1E2100` | |
| UART2 | `0x1E2200` | |
| DMA | `0x1E3F00` | |
| SFC | `0x1F0200` | flash controller (SFC), `SFCENC` em `0x1F0300` |
| Portas GPIO | `0x1E05000` (A) / `0x1E05040` (B) / `0x1E05080` (C) | |

`JL_SPI_TypeDef` (de `br23.h`): `CON(0) BAUD(4) BUF(8) ADR(12) CNT(16)`.

## Buffers e globais do radar

| Endereço | Tamanho | Conteúdo | Verificação |
|---|---|---|---|
| `0x19D71` | 3 B | flags: `[0]`=cubo completo, `[1]`=erro, `[2]`=status do último frame | `1e114cc: b[r5+0] = r0` |
| `0x19D74` | 64 × 257 = **16 448 B** | **buffer bruto SPI** — stride 257 (1 header + 256 amostras) | `1e114b2: r0 += 3` |
| `0x19D75` | 16 384 B úteis | amostras do chirp 0 (pulando o header) | `1e14e48: r0 = 105845` |
| `0x15B60` | **16 384 B** | ★ **cubo packed 64 × 256 int8** (destino de `0x1E14E46`) | `1e14e50: r2 = 88928` |
| `0x15360` | 4 096 B | buffer complexo intermédio da FFT de range | `1e15b8a: r4 = 86880` |
| `0xCF60` | 33 280 B | **Range-Doppler complexo** (65 × 64 × 2 float32) | `1e15b74: r0 = 53088` |
| `0x4C60` | 16 640 B | **magnitude Range-Doppler** (65 × 64 float32) | `1e15c02: r10 = 19552` |
| `0x4B60` | — | buffer de trace/targets do radar | `1e16004: r7 = 19296` |
| `0x1DDB4` | 257 B | staging do frame SPI (origem da cópia no ISR) | `1e11490` |

## Tabelas e constantes estáticas (flash)

| Endereço | Tamanho | Conteúdo |
|---|---|---|
| `0x1E21F84` | 1 024 B | **janela de range** — 256 float32 (verificada: simétrica, pico 0.99996) |
| `0x1E21E84` | 256 B | **janela Doppler** — 64 float32 (verificada: pico 0.99943) |
| `0x1E1EF70` | — | base de globals/strings do firmware |
| `0x1E1F47C` | — | parâmetros da FFT de 256 pontos |
| `0x1E1F46C` | — | parâmetros da FFT de 64 pontos |
| `0x1E21A34` | 112 B | **tabela de despacho de comandos host** (14 × 8 B) |
| `0x1E204BC` | 32 B | tabela de baudrates (8 × u32) |
| `0x1E1EE14` | — | **tabela de tasks do RTOS** (12 B por entrada) |
| `0x1E24514` | 17 124 B | tabela de vetores / imagem de dados inicial (copiada para RAM 0x0) — ⚠️ **não usar como code cave** |
| `0x1E27A34` | 1 032 B | **code cave** (zeros) — destino do stub do patch |

## Contexto do radar e UART

| Endereço | Conteúdo |
|---|---|
| `0x1E230` | contexto do radar (`ctx`): `ctx+1` = próximo índice de chirp esperado; `ctx+76` = contador de erros; `ctx+80` = handle do device UART; `ctx+828` = buffer de recepção host |
| `0x1E280` | handle do device UART0 |
| `0x1E215C8` / `0x1E21604` / `0x1E21640` | structs de device UART0 / UART1 / UART2 |
| `0x19C70` | buffer de TX da UART host |
| `0x19B64` | baudrate efectivo da UART host |
| `0x4248` | contador de micros (usado para timestamps e para o cálculo do baud SPI) |
| `0x1E0600` | registo de controlo escrito pela task `app_radar` (`= 0x4000`) |

## Mapa de tarefas (RTOS JieLi)

Tabela em `0x1E1EE14`, entradas de **12 bytes**, formato
`{ name_ptr, (stack<<16)|priority, qsize }` — **sem ponteiro de função**.

A criação é feita pelo wrapper `0x1E0D462` (recebe `r0=func`, `r1=arg`, `r2=name`,
procura o nome via `strcmp` em `0x21127B8` e chama `os_task_create` em `0x2002D58`).

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

Chamadas de criação: `0x1E008A0` (systimer), `0x1E08B12` (btstack), `0x1E0DC34`
(app_core), `0x1E0E522` (app_radar), `0x1E0E74A`.

## Funções relevantes

| Endereço | Função |
|---|---|
| `0x1E16DD2` | entry de `app_radar` |
| `0x1E16B3E` | loop principal de `app_radar` |
| `0x1E15FD4` | state machine de processamento do radar |
| `0x1E241D4` | open/init da UART host |
| `0x1E2376A` | init genérico de sistema/board |
| `0x1E14C9C` | rotina de flags |
| `0x1E14D64` | **init do SPI1** (slave, sem CS, modo 1) |
| `0x1E14E46` | **cópia bruto → cubo packed** (64×256, stride 257→256) |
| `0x1E15B5E` | **cadeia FFT** (janela → FFT 256 → range → FFT 64 → magnitude) |
| `0x1E15480` | rotina de FFT (256 e 64 pontos) |
| `0x1E1146E` | **ISR do SPI1** (frame 257 B → `0x19D74 + idx*257`) |
| `0x1E1144E` | setup do DMA do SPI1 (257 bytes por transação) |
| `0x1E115FA` | dispatcher de escrita da UART0 (`r0=buffer`, `r1=len`) |
| `0x1E108E0` / `0x1E108A0` | construtor do frame de alvos `F4F3F2F1 … F8F7F6F5` |
| `0x1E0D462` | wrapper de `os_task_create` |
| `0x2002D58` | `os_task_create` (ROM) |
| `0x21127B8` | `strcmp` (ROM) |
| `0x21127A8` | `memcpy` (ROM) |
| `0x1E23BFC` | IRQ handler da UART |
| `0x1E23CD0` | rotina de TX da UART (da sessão anterior) |
