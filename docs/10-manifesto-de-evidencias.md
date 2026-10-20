# Manifesto de evidências

Cada afirmação técnica deste repositório aponta para a evidência que a sustenta.
Formato: `afirmação → como verificar → onde`.

---

## A. Hardware e interface

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| A1 | O AC635N é **escravo** do SPI1 | `SPI1_CON` bit1 = 1 | `rg "1e14ddc" app_objdump.txt` |
| A2 | **Não existe pino de CS** | `SPI1_CON` bit2 (CSE) = 0 | `rg "1e14dd8" app_objdump.txt` |
| A3 | SPI **modo 1** (CPOL=0, CPHA=1) | bit6 (CKID) = 0, bit4 (SE) = 1 | `rg "1e14dec\|1e14de0" app_objdump.txt` |
| A4 | Largura de **1 bit**, single-wire | bits10-11 (DATW) = 0, bit3 (BIDIR) = 1 | `rg "1e14db2\|1e14dae" app_objdump.txt` |
| A5 | CLK em **PB0/PP0**, dados em **PB2/PP2** | manual AC635N (pin mux SPI1CLKA/SPI1DIA) | `research/ac635n_manual.txt` |
| A6 | IRQ 15 = SPI1 | `0x1E0D40A(15, 0, 0x1E1146E)` | `rg "1e14e38\|1e14e32" app_objdump.txt` |

## B. Formato do frame

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| B1 | Frame de **257 bytes** | `r0 = 257` em `[r0+12]`/`[r0+16]` e no `memcpy` | `rg "1e11464\|1e114b4" app_objdump.txt` |
| B2 | `idx = header & 0x3F` | `76 f1 c0 10  r6 = r1 & 0x3F` | `rg "1e1149c" app_objdump.txt` |
| B3 | `status = header >> 7` | `93 a7  r3 = r1 >> 7` | `rg "1e1149a" app_objdump.txt` |
| B4 | Destino = `0x19D74 + idx*257` | `r0 += 3` após `257*idx + 0x19D71` | `rg "1e114b2" app_objdump.txt` |
| B5 | Flag de cubo completo em `0x19D71` | `b[r5+0] = r0` com r0=1 quando idx==64 | `rg "1e114cc" app_objdump.txt` |
| B6 | Erro de sequência após 300 falhas | `if (r0 < 301)` → `b[r5+1] = 1` | `rg "1e114de\|1e114e4" app_objdump.txt` |

## C. Cadeia DSP

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| C1 | Cópia bruto → packed | `0x1E14E46`: src `0x19D75` stride 257 → dst `0x15B60` stride 256 | `rg -A16 "1e14e46:" app_objdump.txt` |
| C2 | `0x15B60` = 64×256 int8 | dst stride 256, 64 iterações | `rg "1e14e6e\|1e14e74" app_objdump.txt` |
| C3 | Janela de range = 256 float32 em `0x1E21F84` | `r6 = 3077`, `0x1E1EF70 + 3077*4` | `rg "1e15b90" app_objdump.txt` + extração de float32 |
| C4 | Janela Doppler = 64 float32 em `0x1E21E84` | `r15 = 3013`, `0x1E1EF70 + 3013*4` | `rg "1e15c12" app_objdump.txt` + extração |
| C5 | FFT de 256 pontos em `0x1E15480` | `call -1868 <0x1E15480>` | `rg "1e15bc8" app_objdump.txt` |
| C6 | FFT de 64 pontos em `0x1E15480` | `call -2046 <0x1E15480>` | `rg "1e15c7a" app_objdump.txt` |
| C7 | Saída complexa em `0xCF60` | `r0 = 53088` | `rg "1e15b74" app_objdump.txt` |
| C8 | Magnitude em `0x4C60` | `r10 = 19552` | `rg "1e15c02" app_objdump.txt` |
| C9 | Amostras **reais** (int8) | `r7 = b[r1++=1] (s)` + `itof(r7)` | `rg "1e15ba4\|1e15bac" app_objdump.txt` |

## D. RTOS e host

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| D1 | `app_radar` = `0x1E16DD2` | entrada da task | `rg "1e16dd2:" app_objdump.txt` |
| D2 | Loop principal = `0x1E16B3E` | loop infinito | `rg "1e16b3e:" app_objdump.txt` |
| D3 | Tabela de tasks em `0x1E1EE14` | entradas de 12 B | `rg "1e1ee14" app_objdump.txt` |
| D4 | Wrapper de task = `0x1E0D462` | `strcmp` + `os_task_create` | `rg "1e0d462:" app_objdump.txt` |
| D5 | `os_task_create` = `0x2002D58` | destino do call | `rg "1e0d462" app_objdump.txt` |
| D6 | Tabela de comandos: 14 entradas em `0x1E21A34` | 14 × 8 B + sentinela | leitura directa do binário |
| D7 | `0x1E241D4` = open da UART host | string "UART INITing..." | `rg "1e241d4:" app_objdump.txt` |
| D8 | Dispatcher UART0 = `0x1E115FA` | `ctx+80` → tabela de métodos | `rg "1e115fa:" app_objdump.txt` |
| D9 | SPI0 = flash serial | comandos `0x6B/0x9F/0x4B` em `0x1E24900` | `rg "1e24900" app_objdump.txt` |

## E. Patch

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| E1 | Code cave `0x1E27A34` livre | 0 ponteiros 32-bit na faixa | scan de `struct.unpack('<I')` |
| E2 | Hook na entrada quebra o prólogo | disassembly mostra lixo em `0x1E15B62` | desassemblar o binário patcheado |
| E3 | Hook nos call sites preserva a ABI | stub chama a original no fim | `rg "1e27c16" app_objdump.txt` |
| E4 | Patch cirúrgico | 391 bytes alterados, 0 fora das 4 regiões | diff byte a byte do binário |
| E5 | `0x1E24514` não pode ser cave | copiado para RAM `0x0` no startup | `rg "1e00156" app_objdump.txt` |

## F. Sniffer

| # | Afirmação | Evidência | Verificação |
|---|---|---|---|
| F1 | O sketch compila | core 3.3.12, 281 713 B | `arduino-cli compile --fqbn esp32:esp32:esp32s3` |
| F2 | O pipeline PC funciona | cubo sintético → headers_ok=True | `python3 tools/capture_cube.py` (mock) |
| F3 | Range Profile detecta o alvo | pico no bin 8 com alvo sintético no bin 8 | `python3 tools/plot_rd.py cube_alvo.bin` |

---

## Ferramentas para reproduzir

```bash
# desassembly oficial
objdump -mcpu=r3 -d firmware_app_ld.elf > app_objdump.txt

# extração das janelas
python3 - <<'EOF'
import struct, pathlib
b = pathlib.Path('firmware_app.bin').read_bytes(); base = 0x1E00120
for va, n, name in ((0x1E21F84, 256, 'range'), (0x1E21E84, 64, 'doppler')):
    o = va - base
    w = [struct.unpack_from('<f', b, o + i*4)[0] for i in range(n)]
    print(name, 'pico', max(w), 'em', w.index(max(w)))
EOF

# tabela de comandos do host
python3 - <<'EOF'
import struct, pathlib
b = pathlib.Path('firmware_app.bin').read_bytes(); base = 0x1E00120
o = 0x1E21A34 - base
for i in range(14):
    cmd, ptr = struct.unpack_from('<II', b, o + i*8)
    print(f'  cmd=0x{cmd:04X} -> 0x{ptr:08X}')
EOF

# verificação do patch
python3 firmware/apply_patch2.py firmware_app.bin firmware/patch.elf out.bin 2
cmp firmware_app.bin out.bin   # deve diferir
```
