#!/usr/bin/env python3
"""
Aplica o patch de dump do cubo bruto no firmware_app.bin do HLK-LD2451.

  hook1 @0x1E1601E  call 0x1E15B5E  ->  call hook_stub
  hook2 @0x1E162CC  call 0x1E15B5E  ->  call hook_stub
  stub  @0x1E27A38  codigo pi32v2 (no code cave)
  flag  @0x1E27A34  4 bytes: 0=off 1=one-shot 2=continuo

O stub envia o cubo 64x256 (0x15B60, 0x4000 B) pela UART0 e DEPOIS
executa a cadeia FFT original, preservando o comportamento do radar.

Uso: apply_patch2.py <app.bin> <patch.elf> <saida.bin> [modo]
"""
import struct, subprocess, sys, pathlib

TOOL = "/opt/rea-fw/tools/jieli-toolchain/pi32v2/bin"
BASE = 0x1E00120
CAVE_FLAG_VA = 0x1E27A34
CAVE_STUB_VA = 0x1E27A38
HOOKS = {".text.hook1": 0x1E1601E, ".text.hook2": 0x1E162CC}

def sec_bytes(elf, name):
    subprocess.run([f"{TOOL}/objcopy", "-O", "binary", "-j", name, elf, "/tmp/_s.bin"],
                   check=True, capture_output=True)
    return pathlib.Path("/tmp/_s.bin").read_bytes()

def sec_addr(elf, name):
    out = subprocess.run([f"{TOOL}/objdump", "-h", elf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) > 3 and p[1] == name:
            return int(p[3], 16)
    raise SystemExit(f"secao {name} ausente")

def main():
    src, elf, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    mode = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    blob = bytearray(pathlib.Path(src).read_bytes())
    orig = bytes(blob)

    stub = sec_bytes(elf, ".text.stub")
    assert sec_addr(elf, ".text.stub") == CAVE_STUB_VA
    assert len(stub) <= 1024, "stub grande demais para o cave"

    # flag
    blob[CAVE_FLAG_VA - BASE: CAVE_FLAG_VA - BASE + 4] = struct.pack("<I", mode)
    # stub
    blob[CAVE_STUB_VA - BASE:CAVE_STUB_VA - BASE + len(stub)] = stub

    diffs = []
    for sec, va in HOOKS.items():
        b = sec_bytes(elf, sec)
        assert len(b) == 4 and sec_addr(elf, sec) == va
        off = va - BASE
        assert bytes(blob[off:off+4]) == orig[off:off+4], f"hook {sec} nao bate"
        blob[off:off+4] = b
        diffs.append((va, orig[off:off+4].hex(), b.hex()))

    pathlib.Path(dst).write_bytes(bytes(blob))
    print(f"patch aplicado: {dst}")
    print(f"  flag  @0x{CAVE_FLAG_VA:X} = {mode} (0=off 1=one-shot 2=continuo)")
    print(f"  stub  @0x{CAVE_STUB_VA:X} ({len(stub)} bytes)")
    for va, o, n in diffs:
        print(f"  hook  @0x{va:X}: {o} -> {n}")

if __name__ == "__main__":
    main()
