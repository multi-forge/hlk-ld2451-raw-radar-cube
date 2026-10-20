# Container `.ufw` — formato, cifra e CRC

Analisado na sessão anterior (2026-09-28) com as ferramentas `jl-misctools`.

## Estrutura do ficheiro

```
HLK-LD2451_V1.13.ufw   437 280 bytes
├── header              0x40 bytes (64)
├── 7 entradas          0x50 bytes cada (80)  → 0x40 + 7*0x50 = 0x250
└── dados dos ficheiros
```

### Header (0x40 bytes)

| Offset | Tamanho | Campo |
|---|---|---|
| 0x00 | u16 | `hdrcrc` — CRC16 do header (bytes 2..0x40) |
| 0x02 | u16 | `listcrc` — CRC16 da tabela de entradas (0x40..headersize) |
| 0x04 | u32 | `imgsize` — tamanho total da imagem (0x6AC20 = 437 280) |
| 0x08 | u16 | `numents` — 7 |
| 0x0A | u16 | `wa3` — 0x0004 |
| 0x0C | u16 | `wa4` — 0x00000200 |
| 0x0E | 48 B | nome do chip — `AC635N` |

### Entradas (0x50 bytes cada)

```
etype, eindex, edcrc, ewa1, eoffset, esize, esize2, ewa2, ename[16]
```

* `edcrc` — CRC16 dos **dados** do ficheiro
* `ename` — nome ASCII (ex.: `uboot.boot`, `app.bin`, `cfg_tool.bin`, `isd_config.ini`)

### Ficheiros extraídos

| Ficheiro | Tamanho | Notas |
|---|---|---|
| `top/uboot.boot` | 8 168 | SPL (segundo bootloader) |
| `top/isd_config.ini` | 683 | config de hardware: `SPI 2_3_0_0`, `UTTX=PA05`, `UTRX=PB05`, `RESET=PB01`, baud 1 000 000 |
| `files/app.bin` | **165 632** | ★ a aplicação — base `0x1E00120` |
| `files/cfg_tool.bin` | 916 | configuração BLE (AC695X) |

`app.bin` SHA-256: `77d399e7e673c416b98ab3ba0d0f6b14ff0fa6b2d2da09c45ea6444869dab800`
Entrada (`entry-point`): `31457568` = `0x01E00120`.

### `jlfw.json`

```json
{
  "format": "jl-new-fw",
  "base-offset": 0,
  "spl": { "file": "top/uboot.boot", "compressed": false },
  "chip-key": 43023,
  "entry-point": 31457568,
  "app-files": [ "files/app.bin", "files/cfg_tool.bin" ]
}
```

`chip-key = 43023` = `0xA80F`, extraído do `isd_config.ini` (via `chipkeybin_decode`).

---

## Cifras e CRCs (Python puro)

```python
def jl_crc16(data, crc=0x0000):
    """CRC16-CCITT, poly 0x1021, init 0x0000, sem reflexão, MSB-first"""
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def jl_enc_cipher(buff, off, size, key=0xFFFF):
    """Scrambling JieLi 'ENC' — LFSR de 16 bits"""
    for i in range(size):
        buff[off + i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return key
```

* **Chave do header**: `0xFFFF`
* **Área da app**: usa também `jl_sfc_cipher` (região SFC, com o chip-key)
* `jl_crc_cipher` (variante com a constante "孟黎我爱你，玉林") existe mas não é usada
  neste container

---

## Reempacotamento

⚠️ **Só existe o *unpacker*.** O `jl-misctools` traz `fwunpack_newfw.py` (extrair),
`recrypt.py` (re-cifrar uma região) e `bruteforce.py`, mas **não** há um packer.

Para gerar um `.ufw` com o `app.bin` patcheado é preciso:

1. substituir os dados da entrada `files/app.bin` pelos 165 632 bytes patcheados
2. recalcular o `edcrc` dessa entrada
3. recalcular o `listcrc` da tabela de entradas
4. recalcular o `hdrcrc` do header
5. re-cifrar (se aplicável) com `jl_sfc_cipher` usando o chip-key

Alternativa: gravar directamente pela UART de download do AC635N
(`USBDM`/`USBDP`), contornando o container.

### Ferramentas de referência

* `fwunpack_newfw.py` — unpacker principal (`jl-new-fw`)
* `jltech/cipher.py` — `jl_enc_cipher`, `jl_sfc_cipher`, `jl_crc_cipher`
* `jltech/crc.py` — `jl_crc16`
* `jltech/chipkeybin.py` — `chipkeybin_decode` / `chipkeybin_encode`
* `recrypt.py` — re-cifra uma região

---

## Repackager em Python (esqueleto)

```python
import struct
from jltech.crc import jl_crc16
from jltech.cipher import jl_sfc_cipher

def rebuild(ufw: bytearray, new_app: bytes, app_entry_off: int):
    # 1. escrever os novos dados
    ufw[app_entry_off:app_entry_off + len(new_app)] = new_app
    # 2. edcrc da entrada
    hdr_off = 0x40 + app_entry_index * 0x50
    struct.pack_into("<H", ufw, hdr_off + 4, jl_crc16(new_app))
    # 3. listcrc da tabela de entradas
    numents = struct.unpack_from("<H", ufw, 0x08)[0]
    headersize = 0x40 + numents * 0x50
    struct.pack_into("<H", ufw, 0x02, jl_crc16(ufw[0x40:headersize]))
    # 4. hdrcrc do header (bytes 2..0x40)
    struct.pack_into("<H", ufw, 0x00, jl_crc16(ufw[0x02:0x40]))
    return bytes(ufw)
```

⚠️ Este esqueleto **não foi validado** — o `jl_sfc_cipher` tem de ser aplicado no
momento certo (a região da app é cifrada em blocos alinhados a 32 bytes a partir do
`app_area_head`).
