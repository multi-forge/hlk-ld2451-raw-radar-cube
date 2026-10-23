#!/usr/bin/env python3
"""
HLK-LD2451 / JieLi BR23 — Empacotador e Verificador de Firmware UFW (.ufw)

Implementação em Python puro (sem dependências externas) das cifras e CRCs:
  - CRC16-CCITT (poly 0x1021, init 0x0000, MSB-first)
  - JieLi ENC cipher (scrambling LFSR de 16 bits para header e descritores)
  - JieLi SFC cipher (cifra de flash SPI em blocos de 32 bytes usando chip-key)

Permite:
  1. Inspecionar e validar containers .ufw (hdrcrc, listcrc, edcrc).
  2. Extrair partições e decifrar app.bin original.
  3. Substituir app.bin pelo firmware patcheado e reempacotar com CRCs válidos.
"""

import argparse
import os
import struct
import sys
from typing import Dict, List, Tuple


def jl_crc16(data: bytes, crc: int = 0x0000) -> int:
    """CRC16-CCITT JieLi: poly 0x1021, init 0x0000, sem reflexão, MSB-first."""
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def jl_enc_cipher(buff: bytearray, off: int, size: int, key: int = 0xFFFF) -> int:
    """Scrambling JieLi 'ENC' — LFSR de 16 bits sobre cabeçalho e descritores."""
    for i in range(size):
        buff[off + i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return key


def jl_sfc_cipher(buff: bytearray, off: int, size: int, base: int, key: int, blocksize: int = 32) -> None:
    """Cifra JieLi 'SFC' — aplicada na partição flash.bin em blocos de 32 bytes."""
    for i in range(0, size, blocksize):
        block_len = min(size - i, blocksize)
        block_key = key ^ ((off + i - base) >> 2)
        jl_enc_cipher(buff, off + i, block_len, block_key & 0xFFFF)


FLASH_BIN_OFF = 0x000400
FLASH_BIN_LEN = 180224
APP_IN_FLASH_OFF = 0x003140
APP_LEN = 165632
CHIP_KEY_DEFAULT = 0xA80F
BASE_DEFAULT = 0x3020 - 0x3140  # -0x120


def parse_header(ufw: bytes) -> Dict[str, any]:
    """Decifra e lê o cabeçalho principal de 64 bytes."""
    hdr_raw = bytearray(ufw[:0x40])
    jl_enc_cipher(hdr_raw, 0, 0x40, key=0xFFFF)
    hdrcrc, listcrc, imgsize, numents, wa3, wa4, chipraw = struct.unpack("<HHIHHI48s", hdr_raw)
    chipname = chipraw.split(b"\x00")[0].decode("ascii", errors="replace")
    calc_hdrcrc = jl_crc16(hdr_raw[2:0x40])
    return {
        "hdrcrc": hdrcrc,
        "calc_hdrcrc": calc_hdrcrc,
        "hdrcrc_ok": (hdrcrc == calc_hdrcrc),
        "listcrc": listcrc,
        "imgsize": imgsize,
        "numents": numents,
        "wa3": wa3,
        "wa4": wa4,
        "chipname": chipname,
    }


def parse_entries(ufw: bytes, numents: int) -> List[Dict[str, any]]:
    """Decifra e lê as entradas da tabela de partições."""
    entries = []
    for i in range(numents):
        e_off = 0x40 + i * 0x50
        e_raw = bytearray(ufw[e_off : e_off + 0x50])
        jl_enc_cipher(e_raw, 0, 0x50, key=0xFFFF)
        etype, eindex, edcrc, ewa1, eoffset, esize, esize2, ewa2, _pad, ename = struct.unpack(
            "<HHHHIIII40s16s", e_raw
        )
        name = ename.split(b"\x00")[0].decode("ascii", errors="replace")
        data_slice = ufw[eoffset : eoffset + esize]
        calc_edcrc = jl_crc16(data_slice)
        entries.append({
            "index": i,
            "type": etype,
            "eindex": eindex,
            "edcrc": edcrc,
            "calc_edcrc": calc_edcrc,
            "edcrc_ok": (edcrc == calc_edcrc),
            "offset": eoffset,
            "size": esize,
            "size2": esize2,
            "name": name,
        })
    return entries


def verify_ufw(ufw_bytes: bytes) -> bool:
    """Verifica completamente a integridade do container UFW."""
    if len(ufw_bytes) < 0x250:
        print("[-] Arquivo muito pequeno para ser um container .ufw válido.")
        return False

    hdr = parse_header(ufw_bytes)
    print(f"[*] Chip: {hdr['chipname']}, ImgSize: {hdr['imgsize']} B, Entradas: {hdr['numents']}")
    print(f"[*] Header CRC:  0x{hdr['hdrcrc']:04X} (calc: 0x{hdr['calc_hdrcrc']:04X}) -> {'OK' if hdr['hdrcrc_ok'] else 'FAIL'}")

    header_size = 0x40 + hdr["numents"] * 0x50
    calc_listcrc = jl_crc16(ufw_bytes[0x40:header_size])
    listcrc_ok = (hdr["listcrc"] == calc_listcrc)
    print(f"[*] List CRC:    0x{hdr['listcrc']:04X} (calc: 0x{calc_listcrc:04X}) -> {'OK' if listcrc_ok else 'FAIL'}")

    entries = parse_entries(ufw_bytes, hdr["numents"])
    flash_entry_ok = False
    for e in entries:
        status = "OK" if e["edcrc_ok"] else ("MISMATCH (aux)" if e["type"] != 0 else "FAIL")
        if e["type"] == 0 and e["edcrc_ok"]:
            flash_entry_ok = True
        print(f"    - Entrada {e['index']} [{e['name']}]: off=0x{e['offset']:06X}, len={e['size']:6d} B, CRC=0x{e['edcrc']:04X} -> {status}")

    valid = hdr["hdrcrc_ok"] and listcrc_ok and flash_entry_ok
    print(f"[*] Status Global (OTA Container): {'100% VALIDO E PRONTO PARA FLASH' if valid else 'CORROMPIDO'}")
    return valid


def extract_app_bin(ufw_bytes: bytes, chip_key: int = CHIP_KEY_DEFAULT) -> bytes:
    """Extrai e decifra o app.bin da partição flash.bin."""
    flash_bin = ufw_bytes[FLASH_BIN_OFF : FLASH_BIN_OFF + FLASH_BIN_LEN]
    enc_app = bytearray(flash_bin[APP_IN_FLASH_OFF : APP_IN_FLASH_OFF + APP_LEN])
    jl_sfc_cipher(enc_app, 0, len(enc_app), BASE_DEFAULT, chip_key)
    return bytes(enc_app)


def patch_ufw_app(orig_ufw_bytes: bytes, new_app_bytes: bytes, chip_key: int = CHIP_KEY_DEFAULT) -> bytes:
    """Substitui o app.bin, recifra e recalcula todos os CRCs do container."""
    if len(new_app_bytes) != APP_LEN:
        raise ValueError(f"Tamanho do app.bin invalido: {len(new_app_bytes)} != {APP_LEN}")

    ufw = bytearray(orig_ufw_bytes)
    flash_bin = bytearray(ufw[FLASH_BIN_OFF : FLASH_BIN_OFF + FLASH_BIN_LEN])

    # 1. Cifrar novo app.bin usando a cifra SFC
    enc_app = bytearray(new_app_bytes)
    jl_sfc_cipher(enc_app, 0, len(enc_app), BASE_DEFAULT, chip_key)

    # 2. Injetar na partição flash.bin
    flash_bin[APP_IN_FLASH_OFF : APP_IN_FLASH_OFF + len(enc_app)] = enc_app
    new_flash_crc = jl_crc16(flash_bin)
    ufw[FLASH_BIN_OFF : FLASH_BIN_OFF + FLASH_BIN_LEN] = flash_bin

    # 3. Atualizar Entry 0 (descritor de flash.bin)
    ENTRY0_OFF = 0x40
    ENTRY_LEN = 0x50
    e0_raw = bytearray(ufw[ENTRY0_OFF : ENTRY0_OFF + ENTRY_LEN])
    jl_enc_cipher(e0_raw, 0, ENTRY_LEN, key=0xFFFF)
    struct.pack_into("<H", e0_raw, 4, new_flash_crc)
    jl_enc_cipher(e0_raw, 0, ENTRY_LEN, key=0xFFFF)
    ufw[ENTRY0_OFF : ENTRY0_OFF + ENTRY_LEN] = e0_raw

    # 4. Recalcular listcrc sobre todas as entradas
    hdr_info = parse_header(orig_ufw_bytes)
    header_size = 0x40 + hdr_info["numents"] * ENTRY_LEN
    new_listcrc = jl_crc16(ufw[ENTRY0_OFF:header_size])

    # 5. Atualizar header principal
    hdr_raw = bytearray(ufw[:0x40])
    jl_enc_cipher(hdr_raw, 0, 0x40, key=0xFFFF)
    struct.pack_into("<H", hdr_raw, 2, new_listcrc)
    new_hdrcrc = jl_crc16(hdr_raw[2:0x40])
    struct.pack_into("<H", hdr_raw, 0, new_hdrcrc)
    jl_enc_cipher(hdr_raw, 0, 0x40, key=0xFFFF)
    ufw[:0x40] = hdr_raw

    return bytes(ufw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manipulador e Repacker de Firmware .ufw do HLK-LD2451")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # inspect / verify
    p_verify = subparsers.add_parser("verify", help="Verifica a integridade de um arquivo .ufw")
    p_verify.add_argument("ufw", help="Caminho do arquivo .ufw")

    # extract-app
    p_extract = subparsers.add_parser("extract-app", help="Extrai e decifra o app.bin de um arquivo .ufw")
    p_extract.add_argument("ufw", help="Caminho do arquivo .ufw")
    p_extract.add_argument("out_app", help="Destino do app.bin decifrado")

    # repack
    p_repack = subparsers.add_parser("repack", help="Substitui o app.bin e recria o .ufw com CRCs válidos")
    p_repack.add_argument("orig_ufw", help="Arquivo .ufw original")
    p_repack.add_argument("new_app", help="Arquivo app.bin patcheado")
    p_repack.add_argument("out_ufw", help="Arquivo .ufw de saída")

    args = parser.parse_args()

    if args.cmd == "verify":
        with open(args.ufw, "rb") as f:
            data = f.read()
        return 0 if verify_ufw(data) else 1

    elif args.cmd == "extract-app":
        with open(args.ufw, "rb") as f:
            data = f.read()
        app = extract_app_bin(data)
        with open(args.out_app, "wb") as f:
            f.write(app)
        print(f"[+] Extraido app.bin ({len(app)} bytes) para {args.out_app}")
        return 0

    elif args.cmd == "repack":
        with open(args.orig_ufw, "rb") as f:
            orig_data = f.read()
        with open(args.new_app, "rb") as f:
            new_app = f.read()
        patched_ufw = patch_ufw_app(orig_data, new_app)
        with open(args.out_ufw, "wb") as f:
            f.write(patched_ufw)
        print(f"[+] Gerado {args.out_ufw} ({len(patched_ufw)} bytes)")
        print("[*] Validando o container recém-gerado:")
        return 0 if verify_ufw(patched_ufw) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
