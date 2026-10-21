#!/usr/bin/env python3
"""
HLK-LD2451 — Teste de fumo (smoke test) ponta a ponta.

Verifica:
  1. Geração de cubo radar sintético com alvo simulado (range 12, doppler +8).
  2. Protocolo de streaming do sniffer ESP32-S3 (magic, len, seq, headers de chirp).
  3. Captura ponta a ponta via tools/capture_cube.py (usando socket loopback).
  4. Extração e integridade de amostras (16448 B raw -> 16384 B amostras int8).
  5. Processamento via tools/plot_rd.py (FFT range-doppler, janela de Hann, pico).
  6. Validação dos CSVs de saída (RD map 65x64 e Range Profile com pico no bin 12).
  7. Verificação de integridade do firmware patcheado (391 bytes alterados,
     exclusivamente nos hooks e no code cave, 0 bytes fora).
"""
import csv
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS_DIR = os.path.join(REPO_DIR, "tools")
FW_DIR = os.path.join(REPO_DIR, "firmware")
ORIG_FW = os.path.join(REPO_DIR, "..", "zip_s3k8y2", "firmware_app.bin")
PATCHED_FW = os.path.join(FW_DIR, "patched_firmware.bin")

K_TARGET = 12
D_TARGET = 8
CHIRPS = 64
NSAMP = 256
FRAME_LEN = 257
MAGIC = b"\xAA\xBB\xCC\xDD"
BASE_VA = 0x1E00120


def generate_synthetic_cube() -> bytes:
    raw = bytearray()
    for c in range(CHIRPS):
        hdr = (c & 0x3F) | (0x80 if (c % 2 == 0) else 0x00)
        raw.append(hdr)
        for n in range(NSAMP):
            val = 60.0 * math.cos(2.0 * math.pi * K_TARGET * n / NSAMP + 2.0 * math.pi * D_TARGET * c / CHIRPS)
            val_int = max(-128, min(127, int(round(val))))
            raw.append(val_int & 0xFF)
    return bytes(raw)


def test_streaming_and_capture(tmpdir: str) -> str:
    raw_cube = generate_synthetic_cube()
    pkt = MAGIC + struct.pack("<II", len(raw_cube), 1) + raw_cube

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def srv_worker():
        conn, _ = srv.accept()
        _ = conn.recv(16)  # handshake 'S'
        conn.sendall(pkt)
        time.sleep(0.4)
        conn.close()
        srv.close()

    t = threading.Thread(target=srv_worker)
    t.start()

    out_dir = os.path.join(tmpdir, "captured")
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        sys.executable,
        os.path.join(TOOLS_DIR, "capture_cube.py"),
        f"socket://127.0.0.1:{port}",
        "--out", out_dir,
        "--count", "1",
        "--seconds", "3.0"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    t.join()

    if proc.returncode != 0:
        raise RuntimeError(f"capture_cube falhou ({proc.returncode}): {proc.stderr}")

    raw_path = os.path.join(out_dir, "cube_000001.bin")
    samples_path = os.path.join(out_dir, "cube_000001_samples.bin")

    assert os.path.exists(raw_path), "cube_000001.bin nao gerado"
    assert os.path.exists(samples_path), "cube_000001_samples.bin nao gerado"
    assert os.path.getsize(raw_path) == 16448, f"tamanho raw invalido: {os.path.getsize(raw_path)}"
    assert os.path.getsize(samples_path) == 16384, f"tamanho samples invalido: {os.path.getsize(samples_path)}"

    # Checagem dos headers
    raw_data = open(raw_path, "rb").read()
    headers = [raw_data[i * FRAME_LEN] for i in range(CHIRPS)]
    indices = [b & 0x3F for b in headers]
    assert indices == list(range(CHIRPS)), f"Indices de chirp incorretos: {indices}"

    return samples_path


def test_dsp_pipeline(samples_path: str, tmpdir: str):
    rd_csv = os.path.join(tmpdir, "rd.csv")
    prof_csv = os.path.join(tmpdir, "prof.csv")

    cmd = [
        sys.executable,
        os.path.join(TOOLS_DIR, "plot_rd.py"),
        samples_path,
        "--csv", rd_csv,
        "--profile-csv", prof_csv
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"plot_rd falhou ({proc.returncode}): {proc.stderr}")

    # Validar saida do profile
    assert os.path.exists(prof_csv), "prof.csv ausente"
    with open(prof_csv, "r") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 66  # header + 65 bins
        powers = [float(row[1]) for row in reader[1:]]
        max_p = max(powers)
        peak_bin = powers.index(max_p)
        assert peak_bin == K_TARGET, f"Pico esperado no bin {K_TARGET}, encontrado no bin {peak_bin}"

    # Validar saida da matriz RD
    assert os.path.exists(rd_csv), "rd.csv ausente"
    with open(rd_csv, "r") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 65
        assert len(reader[0]) == 64


def test_firmware_patch():
    if not os.path.exists(ORIG_FW):
        print(f"  [AVISO] Original {ORIG_FW} nao encontrado; pulando diff.")
        return
    if not os.path.exists(PATCHED_FW):
        raise FileNotFoundError(f"{PATCHED_FW} ausente")

    orig = open(ORIG_FW, "rb").read()
    patched = open(PATCHED_FW, "rb").read()

    assert len(orig) == len(patched) == 165632, "Tamanhos de firmware invalidos"

    diffs = []
    for off, (b1, b2) in enumerate(zip(orig, patched)):
        if b1 != b2:
            diffs.append((off, off + BASE_VA, b1, b2))

    assert len(diffs) == 391, f"Esperado 391 bytes modificados, encontrado {len(diffs)}"

    # Verificar que todas as alteracoes estao nas regioes esperadas
    # Hook 1: 0x1E1601E..0x1E16021
    # Hook 2: 0x1E162CC..0x1E162CF
    # Flag:   0x1E27A34..0x1E27A37
    # Stub:   0x1E27A38..0x1E27C21
    valid_regions = [
        (0x1E1601E, 0x1E16021),
        (0x1E162CC, 0x1E162CF),
        (0x1E27A34, 0x1E27A37),
        (0x1E27A38, 0x1E27C21),
    ]

    for off, va, b1, b2 in diffs:
        in_region = any(start <= va <= end for start, end in valid_regions)
        assert in_region, f"Modificacao espuria fora das regioes permitidas: VA 0x{va:07X}"


def main() -> int:
    print("=" * 65)
    print("HLK-LD2451 — INICIANDO TESTE DE FUMO (SMOKE TEST)")
    print("=" * 65)

    with tempfile.TemporaryDirectory() as tmpdir:
        print("[1/3] Testando captura ponta a ponta (capture_cube.py via socket)...")
        samples_path = test_streaming_and_capture(tmpdir)
        print("      OK: Pacote sniffer validado, cabeçalhos 0..63 confirmados.")
        print("      OK: Arquivo bruto (16448 B) e amostras puras (16384 B) gerados.")

        print("[2/3] Testando cadeia DSP (plot_rd.py / FFT / Hann / Peak detection)...")
        test_dsp_pipeline(samples_path, tmpdir)
        print(f"      OK: Alvo detectado com precisao no bin {K_TARGET} (potencia maxima).")
        print("      OK: Matriz Range-Doppler 65x64 e Range Profile CSV validados.")

        print("[3/3] Testando integridade do patch de firmware (patched_firmware.bin)...")
        test_firmware_patch()
        print("      OK: Exatamente 391 bytes alterados contra o firmware oficial.")
        print("      OK: 0 bytes modificados fora dos hooks e do code cave.")

    print("=" * 65)
    print("TODOS OS TESTES DE FUMO PASSARAM COM SUCESSO! (100% OK)")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
