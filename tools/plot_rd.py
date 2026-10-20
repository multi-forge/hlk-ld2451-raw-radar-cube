#!/usr/bin/env python3
"""
HLK-LD2451 — processa o cubo bruto 64 x 256 (int8) e produz:
  - Range-Doppler map (65 x 64) reproduzindo a cadeia do firmware
  - CSV da magnitude por range/doppler
  - estatisticas basicas

Cadeia do firmware (verificada em app_objdump.txt):
  1. amostras int8 (64 chirps x 256) em 0x15B60
  2. janela (256 floats, 0x1E21F84) + FFT de 256 pontos  -> 65 bins de range
  3. FFT de 64 pontos sobre os 64 chirps (Doppler)       -> 64 bins de doppler
  4. magnitude                                        -> 0x4C60 (65 x 64)

Uso:
    python3 plot_rd.py cube_000000_samples.bin
    python3 plot_rd.py cube_000000_samples.bin --csv rd.csv
"""
import argparse
import csv
import struct
import sys

CHIRPS = 64
NSAMP = 256
NFFT = 256
NRANGE = 65          # NFFT/2 + 1
NDOPPLER = 64


def read_cube(path: str) -> list:
    with open(path, "rb") as f:
        data = f.read()
    need = CHIRPS * NSAMP
    if len(data) < need:
        raise SystemExit(f"arquivo curto: {len(data)} bytes, esperado >= {need}")
    return [list(struct.unpack_from("<256b", data, c * NSAMP)) for c in range(CHIRPS)]


def fft(x: list) -> list:
    """FFT iterativa radix-2 em Python puro (sem numpy)."""
    n = len(x)
    if n & (n - 1):
        raise ValueError("tamanho nao e potencia de 2")
    a = list(x)
    # bit reversal
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    import cmath
    while length <= n:
        ang = -2.0 * cmath.pi / length
        wlen = cmath.cos(ang) + 1j * cmath.sin(ang)
        for i in range(0, n, length):
            w = complex(1.0, 0.0)
            half = length >> 1
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * w
                a[i + k] = u + v
                a[i + k + half] = u - v
                w *= wlen
        length <<= 1
    return a


def hann(n: int) -> list:
    import math
    return [0.5 * (1.0 - math.cos(2.0 * math.pi * i / n)) for i in range(n)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cube")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--profile-csv", default=None, help="CSV do Range Profile")
    args = ap.parse_args()

    cube = read_cube(args.cube)
    win = hann(NFFT)

    # passo 1: FFT de range por chirp -> 65 bins complexos
    range_fft = []
    for c in range(CHIRPS):
        row = [cube[c][i] * win[i] for i in range(NSAMP)]
        spec = fft(row)
        range_fft.append(spec[:NRANGE])

    # passo 2: FFT de doppler sobre os 64 chirps, por bin de range
    rd = []
    for b in range(NRANGE):
        col = [range_fft[c][b] for c in range(CHIRPS)]
        spec = fft(col)
        # shift de doppler: bring DC to centre
        half = NDOPPLER // 2
        shifted = spec[half:] + spec[:half]
        rd.append([abs(v) for v in shifted])

    peak = max(max(row) for row in rd)
    print(f"cubo: {args.cube}")
    print(f"range-doppler: {NRANGE} x {NDOPPLER}, pico={peak:.4f}")

    # estatisticas das amostras brutas
    flat = [v for row in cube for v in row]
    print(f"amostras: min={min(flat)} max={max(flat)} media={sum(flat)/len(flat):.2f}")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            for b in range(NRANGE):
                w.writerow([f"{v:.6f}" for v in rd[b]])
        print(f"CSV escrito em {args.csv}")

    # --- Range Profile -------------------------------------------------
    # Potencia media de cada bin de distancia, integrada sobre todos os
    # bins de doppler. Se a captura estiver correta, deve aparecer um pico
    # claro na distancia do objeto a frente do radar.
    profile = []
    for b in range(NRANGE):
        acc = 0.0
        for d in range(NDOPPLER):
            acc += rd[b][d] * rd[b][d]      # potencia
        profile.append(acc / NDOPPLER)

    pmax = max(profile) if profile else 0.0
    ppeak = profile.index(pmax) if pmax > 0 else 0

    print(f"\nRange Profile (potencia media por bin de distancia), pico no bin {ppeak}:")
    if pmax > 0:
        for b in range(NRANGE):
            frac = profile[b] / pmax
            bar = "#" * int(frac * 50)
            mark = " <== PICO" if b == ppeak else ""
            print(f"  bin {b:2d} | {profile[b]:12.4f} | {bar}{mark}")
    else:
        print("  (sinal nulo)")

    # deteccao de alvo: primeiro pico local acima de -10 dB do max
    if pmax > 0:
        thr = pmax * 0.1          # -10 dB
        for b in range(1, NRANGE - 1):
            if profile[b] > thr and profile[b] >= profile[b - 1] and profile[b] >= profile[b + 1]:
                print(f"\npossivel alvo: bin de range {b} "
                      f"({profile[b]:.4f}, {100*profile[b]/pmax:.1f}% do pico)")
                break

    if args.profile_csv:
        with open(args.profile_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["range_bin", "power"])
            for b in range(NRANGE):
                w.writerow([b, f"{profile[b]:.6f}"])
        print(f"Range Profile CSV em {args.profile_csv}")

    # ASCII map (sem matplotlib no ambiente Android)
    chars = " .:-=+*#%@"
    print("\nRange-Doppler (eixo Y = range 0..64, eixo X = doppler -32..+31):")
    for b in range(NRANGE - 1, -1, -1):
        line = "".join(
            chars[min(9, int(9 * rd[b][d] / peak))] if peak > 0 else " " for d in range(NDOPPLER)
        )
        print(f"{b:3d}|{line}|")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
