# Registo da engenharia reversa

Cronologia das sessões, com os artefactos que cada uma produziu. Serve de índice para
reproduzir ou auditar qualquer conclusão.

---

## Sessão 1 — 2026-09-28: container e protocolo

**Objectivo:** obter e desempacotar o firmware; mapear o protocolo UART.

**Produziu:**
* `HLK-LD2451_V1.13.ufw` (437 280 B) baixado do endpoint OTA oficial da Hi-Link
* Desempacotagem com `jl-misctools` → `app.bin` (165 632 B, base `0x1E00120`),
  `cfg_tool.bin`, `uboot.boot`, `isd_config.ini`
* Cifra e CRC do container decifrados (`jl_enc_cipher`, `jl_sfc_cipher`, `jl_crc16`,
  chip-key `0xA80F`)
* Tabela de despacho de comandos do host localizada
* App Android `com.hlk.hlkradartool` decompilado (frame `F4F3F2F1 … F8F7F6F5`)
* Protocolo LD2451 v1.03 extraído do PDF oficial

**Log bruto:** `research/hlk_research_session.jsonl` (não incluído — ~1,6 MB)

---

## Sessão 2 — 2026-10-15/16: ambiente Ghidra e toolchain

**Objectivo:** montar o ambiente de análise e começar a RE.

**Produziu:**
* VM GCP spot `rea-fw-spot` (us-central1-a) provisionada via `startup-rea-fw-spot.sh`
* Ghidra 12.1.4 + plugin `quarkslab/ghidra-jieli` (linguagem `pi32v2:LE:32:default`)
* Toolchain JieLi Linux 20260730.1 (clang 4.0.1, target `pi32v2`)
* ELF válido reconstruído com o linker JieLi (`ld -m elf32pi32v2 -T fw_link.ld
  -b binary firmware_app.bin`) — a secção `.text` tem de ser marcada `AX` por patch
  Python (`e_shoff+40+8 |= 4`), senão o objdump recusa
* Desassembly completa: `app_objdump.txt` (61 478 linhas, 1 465 `<unknown instruction>`
  correspondentes a pools de literais)
* Scripts Ghidra: `TraceSpi.java`, `ForceAnalyze.java`, `VerifyFw.java`
* Headers BR23 do SDK: `br23.h`, `spi.h`, `uart.h`, `uart_dev.h`, `gpio.h`

---

## Sessão 3 — 2026-10-19/20: a cadeia DSP

**Objectivo:** localizar a origem dos dados do radar e mapear o processamento de sinal.

**Resultado principal — a cadeia completa:**

```
RC2412FR --SPI1 (modo 1, sem CS)--> 0x19D74 (64×257)
   --0x1E14E46--> 0x15B60 (64×256 int8) --0x1E15B5E--> 0xCF60 (complexo) --> 0x4C60 (magnitude)
```

**Descobertas verificadas:**
* `app_radar` = `0x1E16DD2`; loop = `0x1E16B3E`; state machine = `0x1E15FD4`
* `0x1E1146E` = ISR do SPI1 → formato do frame provado a nível de instrução
* `0x1E14E46` = cópia bruto → cubo packed (stride 257 → 256)
* `0x1E15B5E` = janela + FFT 256 + FFT 64 → magnitude
* Janelas confirmadas empiricamente: range em `0x1E21F84` (pico 0.99996), Doppler em
  `0x1E21E84` (pico 0.99943)
* `SPI1_CON` provado: slave, sem CS (CSE=0), modo 1
* Tabela de comandos: 14 entradas em `0x1E21A34`

---

## Sessão 4 — 2026-10-20: sniffer, patch e validação

**Objectivo:** entregar as duas vias de captura.

**Via A (sniffer):**
* sketch ESP32-S3 escrito, com ISR IRAM + leitura directa de `GPIO.in`
* **compilado sem erros** na VM (core 3.3.12) — 281 713 B flash (21%)
* contador de overruns + comando `R` de relatório (pedido pelo líder)
* `capture_cube.py` e `plot_rd.py` escritos e testados com cubos sintéticos
* **Range Profile** com detecção de pico acrescentado ao `plot_rd.py` (pedido pelo líder)
* validado: pico no bin 8 com alvo sintético colocado no bin 8

**Via B (patch):**
* code cave `0x1E27A34` identificado e verificado (0 ponteiros 32-bit para a região)
* primeira tentativa: hook na entrada da função `0x1E15B5E` → **rejeitada** pela
  validação (destruía o prólogo de 6 bytes)
* segunda tentativa: hook nos **dois call sites** (`0x1E1601E`, `0x1E162CC`) → **aceite**
* stub pi32v2 (490 B) compilado com o toolchain JieLi e linkado nas posições exactas
  via linker script
* `patched_firmware.bin` gerado e validado: **391 bytes alterados, 0 fora das regiões
  previstas**
* backup do projeto Ghidra: `/opt/rea-fw/backup/ghidra-hlk-20261020T063241Z.tar.gz`

**Entregáveis no repositório:** este repo, `firmware/patched_firmware.bin` (pronto, não
gravado) e `sniffer/` + `tools/` (prontos a usar na bancada).

---

## Como auditar cada afirmação

| Afirmação | Como verificar |
|---|---|
| Endereços | `rg "<addr>" app_objdump.txt` |
| Registo SPI1 | ver `docs/03-protocolo-spi1.md` §1 (com a disassembly anotada) |
| Formato do frame | `docs/03-protocolo-spi1.md` §3 (ISRs anotados) |
| Cadeia DSP | `docs/02-cadeia-dsp.md` (toda a disassembly) |
| Janelas | extrair float32 do binário em `0x1E21F84` / `0x1E21E84` |
| Patch | `python3 firmware/apply_patch2.py app.bin firmware/patch.elf out.bin 2` e comparar |
| Code cave | scan de ponteiros 32-bit (ver `docs/06-patch-de-firmware.md` §3) |
| Sniffer compila | `arduino-cli compile --fqbn esp32:esp32:esp32s3 …` na VM |
| Pipeline PC | `python3 tools/plot_rd.py cube_sintetico.bin` |
