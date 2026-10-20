# Patch de firmware — desenho, implementação e validação

> ⚠️ **NÃO GRAVADO EM NENHUM MÓDULO.** Só existe um HLK-LD2451 e não há como testar
> com segurança. Os artefactos estão prontos para quando houver um segundo módulo.

---

## 1. Objectivo

Injetar no firmware a capacidade de despejar o **cubo radar bruto** (64×256 int8) pela
UART0 do próprio módulo, sem alterar o comportamento normal do radar.

Quando ligado, o host recebe:

```
AA BB CC DD | len(u32 LE = 0x4000) | seq(u32 LE) | 16384 bytes do cubo (64×256 int8)
```

repetidamente (modo contínuo) ou uma vez (modo one-shot).

---

## 2. Onde fazer o hook

### Ponto de dados

O cubo já está **pronto e empacotado** em `0x15B60` (16 384 bytes contíguos) quando a
cadeia FFT é chamada — a rotina `0x1E14E46` é executada imediatamente antes. Logo:

* **não é preciso** recalcular nada
* **não é preciso** tocar na cadeia DSP
* a cópia pode ser feita **antes** da FFT, porque a FFT só **lê** `0x15B60`
  (fonte: `r10 = 0x15B60`) e escreve em `0x15360` / `0xCF60` / `0x4C60`

### Ponto de código — os call sites

A cadeia FFT (`0x1E15B5E`) é chamada de **dois** sítios:

| Call site | Instrução original | Contexto |
|---|---|---|
| `0x1E1601E` | `bf ea 9e fd` → `call 0x1E15B5E` | logo a seguir a `call 0x1E14E46` (a cópia) |
| `0x1E162CC` | `bf ea 47 fc` → `call 0x1E15B5E` | idem |

### ★ Por que NÃO hookar a entrada da função

A primeira tentativa foi substituir os 4 primeiros bytes de `0x1E15B5E`. A validação por
disassembly do firmware patcheado mostrou que isso **destruía o prólogo**:

```
1e15b5e:    c0 ea 6b 8f       	goto 0x1E27A38      ← hook instalado
1e15b62:    f8 1d             	r0 = r7 + r7      ← LIXO (era `sp += -520`)
```

O prólogo ocupa **6 bytes** (`7f 04` = push de `{rets, r15-r4}` + `f0 e8 f8 1d` =
`sp += -520`) e um hook de 4 bytes não cabe.

**Hooking os call sites** resolve isto de forma inequívoca: o stub é chamado
exactamente onde a original era chamada, com os mesmos argumentos e a mesma
expectativa de registos. O stub devolve **chamando a original**, portanto `r0`–`r3`
ficam com os mesmos valores que o firmware original deixaria.

---

## 3. Code cave

| Endereço | Tamanho | Estado |
|---|---|---|
| `0x1E27A34` | 1 032 B | ★ **escolhido** — flag de controlo (4 B) + stub |
| `0x1E281E9` | 903 B | alternativa (logo após a string `"…riorityDisinherit"`) |
| `0x1E28571` | 99 B | alternativa |
| `0x1E27F4D` | 78 B | alternativa |
| `0x1E27E7B` | 68 B | alternativa |
| `0x1E24514` | 64 B | ⚠️ **PROIBIDO** — é a tabela de vetores copiada para RAM `0x0` no startup |

### Verificação de segurança do cave

```python
import pathlib, struct
b = pathlib.Path('firmware_app.bin').read_bytes()
CAVE, SIZE = 0x1E27A34, 1032
hits = []
for i in range(0, len(b) - 3):
    v = struct.unpack_from('<I', b, i)[0]
    if CAVE <= v < CAVE + SIZE:
        hits.append((i, v))
print("ponteiros 32-bit para dentro do cave:", len(hits))   # → 0
```

* **0 ponteiros de 32 bits** apontam para a região ⇒ não há referências de dados
* O único "branch target" detectado na faixa (`0x1E27CEE`) é um **falso positivo**:
  vem de `objdump` a desassemblar bytes de *dados* como código (`ff ff 03 80 ff ff ff 3f
  ff ff 1f f2 0f` a partir de `0x1E27E60` são claramente dados, não instruções). O
  stub terminado em `0x1E27C1A` fica **antes** dessa zona.

---

## 4. O stub (pi32v2)

Ficheiro: [`firmware/stub3.c`](../firmware/stub3.c)

```c
typedef void (*uart_send_fn)(void *buf, unsigned len);
typedef void (*void_fn)(void);

#define CAVE_FLAG   0x1E27A34u
#define CUBE_PTR    0x15B60u
#define CUBE_LEN    0x4000u
#define UART0_SEND  0x1E115FAu
#define ORIG_FFT    0x1E15B5Eu

__attribute__((section(".text.stub")))
void hook_stub(void)
{
    unsigned mode = *(volatile unsigned int *)CAVE_FLAG;

    if (mode != 0) {
        unsigned char hdr[12];
        unsigned char *p;
        unsigned i;

        hdr[0] = 0xAA; hdr[1] = 0xBB; hdr[2] = 0xCC; hdr[3] = 0xDD;
        for (i = 0; i < 4; i++)
            hdr[4 + i] = (unsigned char)(CUBE_LEN >> (8 * i));
        for (i = 0; i < 4; i++)
            hdr[8 + i] = 0;

        ((uart_send_fn)UART0_SEND)(hdr, 12);

        p = (unsigned char *)CUBE_PTR;
        for (i = 0; i < CUBE_LEN; i += 512) {
            unsigned n = CUBE_LEN - i;
            if (n > 512) n = 512;
            ((uart_send_fn)UART0_SEND)(p + i, n);
        }

        if (mode == 1)
            *(volatile unsigned int *)CAVE_FLAG = 0;
    }

    /* executa a cadeia FFT original */
    ((void_fn)ORIG_FFT)();
}
```

### Decisões

* **Chamada indirecta** (`call r0`) em vez de `call` relativo — o toolchain pi32v2 não
  suporta assembler, e a chamada via ponteiro de função resolve o endereço absoluto
  sem cálculos manuais de displacement.
* **Blocos de 512 B** — evita transbordar o ring buffer da UART.
* **O cabeçalho é montado na stack** (12 B) — não precisa de secção `.data` (que
  exigiria mais espaço no binário).
* **`ORIG_FFT` é chamada no fim** — o dump não interfere com `r0`–`r3` deixados pela FFT
  original.

### Disassembly gerado (verificado)

```asm
1e27a38: 77 04              [--sp] = {rets, r7-r4}
1e27a3a: e2 9d              sp += -12
1e27a3c: c4 ff 34 7a e2 01  r4 = 31619636      ; 0x1E27A34 (flag)
1e27a42: 45 60              r5 = [r4+0]
1e27a44: 05 f8 e7 00        if (r5 == 0) goto 0x1e27c16   ; modo off → saltar dump
   …  (monta o cabeçalho, chama uart0_send em blocos de 512)
1e27c10: 35 e8 01 00        if (r5 == 1) {              ; modo one-shot
1e27c14: c6 60                [r4+0] = r6                ;   → desliga o flag
              }
1e27c16: c0 ff 5e 5b e1 01  r0 = 31546206      ; 0x1E15B5E
1e27c1c: c0 00              call r0                   ; ★ FFT original
1e27c1e: 02 83              sp += 12
1e27c20: 57 04              {pc, r7-r4} = [sp++]
```

---

## 5. Os hooks

Ficheiro: [`firmware/hooks.s`](../firmware/hooks.s)

```asm
	.section .text.hook1,"ax",@progbits
	.globl hook_entry_1
	.align 2
hook_entry_1:
	call hook_stub

	.section .text.hook2,"ax",@progbits
	.globl hook_entry_2
	.align 2
hook_entry_2:
	call hook_stub
```

Linker script ([`firmware/link_stub.ld`](../firmware/link_stub.ld)) — o linker JieLi
resolve os displacements:

```ld
ENTRY(hook_stub)
SECTIONS
{
  . = 0x1E1601E;
  .text.hook1 : { *(.text.hook1) }

  . = 0x1E162CC;
  .text.hook2 : { *(.text.hook2) }

  . = 0x1E27A38;
  .text.stub : { *(.text.stub) }
}
```

Resultado:

```
.text.hook1   00000004  0000000001e1601e   →  80 ea 0b 8d   call 0x1E27A38
.text.hook2   00000004  0000000001e162cc   →  80 ea b4 8b   call 0x1E27A38
.text.stub    000001ea  0000000001e27a38
```

---

## 6. Aplicação e validação

Ficheiro: [`firmware/apply_patch2.py`](../firmware/apply_patch2.py)

```bash
# compilar
clang -target pi32v2 -O2 -c stub3.c -o stub3.o
clang -target pi32v2 -c hooks.s -o hooks.o

# linkar (posições exactas)
ld -m elf32pi32v2 -T link_stub.ld hooks.o stub3.o -o patch.elf

# aplicar
python3 apply_patch2.py firmware_app.bin patch.elf patched_firmware.bin 2
```

O aplicador **verifica** que os bytes nos call sites são os originais antes de os
substituir (`assert bytes(blob[off:off+4]) == orig[off:off+4]`).

### Resultado da validação

```
total de bytes alterados: 391
  região VA 0x01E1601E len 4   : 3 bytes alterados
  região VA 0x01E162CC len 4   : 3 bytes alterados
  região VA 0x01E27A34 len 4   : 1 byte alterado    (flag)
  região VA 0x01E27A38 len 490 : 384 bytes alterados (stub)
  bytes alterados FORA das regiões esperadas: 0
```

Verificação independente: reconstruir o ELF a partir do binário patcheado
(`ld -m elf32pi32v2 -T fw_link.ld -b binary patched_firmware.bin -o patched_ld.elf`,
marcando `.text` como `AX`) e desassemblar com o `objdump` oficial:

```asm
 1e1601a:    bf ea 14 f7       	call -4568 <0x1E14E46>     ; cópia do cubo (intacta)
 1e1601e:    80 ea 0b 8d       	call 72214 <0x1E27A38>    ; ★ hook → stub
 1e16022:    40 e0 d8 0a       	r0 = 2776                ; código original intacto
```

SHA-256 do `patched_firmware.bin` (flag = 2, contínuo):
`df856512018bec11ba41354bcd1e3bfedc2158d073157305badc427f0649ff22`

---

## 7. Flag de controlo

4 bytes em `0x1E27A34` (little-endian):

| Valor | Comportamento |
|---|---|
| `0` | **desligado** — comportamento idêntico ao firmware original |
| `1` | one-shot — um dump e desliga-se |
| `2` | contínuo — um dump por chamada da cadeia FFT |

Para desligar sem reflash: escrever `0` no offset `0x1E27A34 - 0x1E00120 = 0x27914` do
`app.bin`.

---

## 8. Vazão

| Baud | 16 KB | Taxa de cubos |
|---|---|---|
| 1 000 000 | ~131 ms | ~7,6 /s |
| 460 800 | ~284 ms | ~3,5 /s |
| 115 200 | ~1,14 s | ~0,9 /s |

⚠️ O dump bloqueia a task do radar durante o envio. O ISR do SPI continua a encher
`0x19D74`, mas o processamento perde ciclos (perda de cubos, não de integridade).

---

## 9. Alternativas de hook (para referência)

Se fosse necessário um **comando de host** (em vez de modo contínuo):

| Estratégia | Nota |
|---|---|
| Repurposar a entrada 13 (`0xA7` → `0x0099`) | ⚠️ quebra a função de baudrate/leitura de registador se o host a usar |
| Hook em `0x1E16D4E` (leitura de `b[r4+6]`, o cmd) | ★ recomendado — não toca na tabela |
| Dump automático no boot | útil para bancada, mas polui a UART do host |

Leitura do comando no buffer host:

```asm
1e16d4e: 50 ee 46 a0        r10 = b[r4+6] (u)     ; ← cmd do host
1e16d52: 00 e1 e8 f0        r0 = r15 + 232
1e16d56: a1 16              r1 = r10
1e16d58: bf ea 43 ab        call -43386 <0x1E0C3E2>
```

O payload do comando seria `b[buf+7]`, e o modo poderia ir em `b[buf+8]`
(0=off, 1=one-shot, 2=contínuo), com `b[buf+7] == 0` exigido pelo handler.

---

## 10. Riscos

| Risco | Mitigação |
|---|---|
| **Brick** | Dump da flash original antes de qualquer gravação. Só testar em módulo de descarte. |
| OTA rejeita o `.ufw` | Recalcular CRCs (ver [`05-container-ufw.md`](05-container-ufw.md)); ou gravar directo por USB |
| Patch corrompe BSS/stack | Usar o cave `0x1E27A34`; nunca `0x1E24514` |
| RST do RC2412 durante a gravação | O RC2412 é o master do SPI1 — se mandar clock durante o flash, corrompe. Considerar segurar o RST |
| Sem packer `.ufw` | Reimplementar a escrita do container, ou gravar directo |
| Sobrescrever a tabela de vectores | `0x1E24514` está excluído |

---

## 11. Artefactos na VM

```
/opt/rea-fw/out/patch/
├── patched_firmware.bin    165 632 B   (flag = 2, contínuo)
├── patch.elf               3 368 B     (stub + hooks linkados)
├── stub3.c                 1 648 B
├── hooks.s                 411 B
├── link_stub.ld            186 B
└── apply_patch2.py         2 468 B
```
