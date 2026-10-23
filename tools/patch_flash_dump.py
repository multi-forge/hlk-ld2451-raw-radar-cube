#!/usr/bin/env python3
"""
HLK-LD2451 — Injetor de firmware patcheado no dump físico da SPI Flash (512 KB).

Permite gravar o firmware patcheado diretamente via programador CH341A (clip SOIC-8)
preservando 100% dos dados de calibração de fábrica e configurações BLE.

Estrutura da Flash SPI (Puya P25D40SH — 512 KB):
  0x000000 - 0x0001FF : Cabeçalho de boot físico JieLi (SFC header)
  0x000200 - 0x00313F : Bootloader SPL (uboot.boot)
  0x003140 - 0x02B7DF : app.bin (165.632 bytes, cifrado com SFC key=0xA80F)
  0x02B7E0 - 0x02C000 : Padding / descritores
  0x02C000 - 0x07FFFF : NVRAM, calibração de fábrica, parâmetros BLE, MAC address

Uso:
  python3 patch_flash_dump.py <backup_512k.bin> <patched_firmware.bin> <saida_512k.bin>
"""

import os
import struct
import sys

FLASH_SIZE = 512 * 1024  # 524.288 bytes
APP_OFFSET = 0x003140
APP_SIZE = 165632
CHIP_KEY = 0xA80F
BASE_OFFSET = 0x3020 - 0x3140  # -0x120


def jl_enc_cipher(buff: bytearray, off: int, size: int, key: int = 0xFFFF) -> int:
    """Scrambling LFSR JieLi."""
    for i in range(size):
        buff[off + i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return key


def jl_sfc_cipher(buff: bytearray, off: int, size: int, base: int, key: int, blocksize: int = 32) -> None:
    """Cifra JieLi SFC para execução direta da SPI Flash (XIP)."""
    for i in range(0, size, blocksize):
        block_len = min(size - i, blocksize)
        block_key = key ^ ((off + i - base) >> 2)
        jl_enc_cipher(buff, off + i, block_len, block_key & 0xFFFF)


def main():
    if len(sys.argv) < 4:
        print(f"Uso: {sys.argv[0]} <backup_512k.bin> <patched_firmware.bin> <saida_512k.bin>")
        sys.exit(1)

    backup_path = sys.argv[1]
    patched_app_path = sys.argv[2]
    out_path = sys.argv[3]

    backup_data = bytearray(open(backup_path, "rb").read())
    if len(backup_data) != FLASH_SIZE:
        print(f"[!] Erro: O arquivo de backup deve ter exatamente {FLASH_SIZE} bytes (512 KB), encontrado: {len(backup_data)}")
        sys.exit(1)

    patched_app = open(patched_app_path, "rb").read()
    if len(patched_app) != APP_SIZE:
        print(f"[!] Erro: patched_firmware.bin deve ter exatamente {APP_SIZE} bytes, encontrado: {len(patched_app)}")
        sys.exit(1)

    print(f"[*] Carregado backup de flash: {backup_path} ({len(backup_data)} bytes)")
    print(f"[*] Injetando novo app.bin cifrado no offset 0x{APP_OFFSET:06X}...")

    # Cifra o novo app.bin com a SFC key
    enc_app = bytearray(patched_app)
    jl_sfc_cipher(enc_app, 0, len(enc_app), BASE_OFFSET, CHIP_KEY)

    # Injeta no dump
    backup_data[APP_OFFSET : APP_OFFSET + APP_SIZE] = enc_app

    # Salva o arquivo de 512 KB pronto para o flashrom
    with open(out_path, "wb") as f:
        f.write(backup_data)

    print(f"[+] Gerado {out_path} ({len(backup_data)} bytes)")
    print(f"[*] Preservados 100% dos setores 0x02C000..0x080000 (calibração e NVRAM)")
    print(f"[+] Pronto para gravar: flashrom -p ch341a_spi -c \"P25D40\" -w {out_path}")


if __name__ == "__main__":
    main()
