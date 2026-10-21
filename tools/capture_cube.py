#!/usr/bin/env python3
"""
HLK-LD2451 — captura o cubo bruto (64 x 256 amostras int8) vindo do sniffer.

Protocolo do sniffer (ESP32-S3, USB CDC):
    AA BB CC DD | len(u32 LE) | seq(u32 LE) | payload (16448 bytes)
O payload contem 64 frames de 257 bytes: [header, 256 amostras].

O script:
  1. envia 'S' periodicamente para o sniffer comecar a capturar
  2. procura o magic, valida o cabecalho e grava o .bin
  3. separa o payload (64 x 256 int8) do payload com headers (64 x 257)

Uso:
    python3 capture_cube.py /dev/ttyACM0
    python3 capture_cube.py COM7          (Windows)
"""
import argparse
import struct
import sys
import time

MAGIC = b"\xAA\xBB\xCC\xDD"
FRAME_LEN = 257
CHIRPS = 64
CUBE = FRAME_LEN * CHIRPS          # 16448
PAYLOAD = CHIRPS * 256              # 16384


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--out", default=".")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = infinito")
    ap.add_argument("--count", type=int, default=0, help="0 = infinito, N = para apos N cubos")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("ERRO: instale pyserial (pip install pyserial)", file=sys.stderr)
        return 1

    if "://" in args.port:
        ser = serial.serial_for_url(args.port, baudrate=args.baud, timeout=0.2)
    else:
        try:
            ser = serial.Serial(args.port, args.baud, timeout=0.2)
        except PermissionError:
            ser = serial.Serial(args.port, args.baud, timeout=0.2, dsrdtr=True, rtscts=True)
    buf = bytearray()
    last_s = 0.0
    t0 = time.time()
    n = 0

    print(f"aguardando cubos em {args.port} @ {args.baud}")
    while True:
        if args.seconds and time.time() - t0 > args.seconds:
            break
        if args.count and n >= args.count:
            break
        now = time.time()
        if now - last_s > 1.0:
            try:
                ser.write(b"S")
            except serial.SerialException:
                pass
            last_s = now

        chunk = ser.read(8192)
        if chunk:
            buf.extend(chunk)
            # log do sketch
            for line in chunk.split(b"\n"):
                if line.startswith(b"#"):
                    print("ESP32:", line.decode(errors="replace").strip())

        i = buf.find(MAGIC)
        if i < 0:
            if len(buf) > 4:
                del buf[:-4]
            if args.seconds and time.time() - t0 > args.seconds:
                break
            continue

        if len(buf) < i + 12 + CUBE:
            if args.seconds and time.time() - t0 > args.seconds:
                break
            continue

        _, length, seq = struct.unpack_from("<4sII", buf, i)
        if length != CUBE:
            print(f"magic em {i} mas len={length} (esperado {CUBE}); descartando")
            del buf[: i + 4]
            continue

        raw = bytes(buf[i + 12 : i + 12 + CUBE])
        del buf[: i + 12 + CUBE]

        fn = f"{args.out}/cube_{seq:06d}.bin"
        with open(fn, "wb") as f:
            f.write(raw)
        n += 1

        # validacao dos headers: idx = byte & 0x3F deve progredir 0..63
        hdr = raw[0::FRAME_LEN]
        idx = [b & 0x3F for b in hdr]
        status = [b >> 7 for b in hdr]
        ok = idx == list(range(CHIRPS))
        print(f"{fn} seq={seq} headers_ok={ok} status_bits={set(status)}")
        if not ok:
            print("  idx:", idx)

        # payload puro 64 x 256 (sem os bytes de header)
        with open(fn.replace(".bin", "_samples.bin"), "wb") as f:
            for c in range(CHIRPS):
                off = c * FRAME_LEN + 1
                f.write(raw[off : off + 256])
        if args.count and n >= args.count:
            break

    print(f"capturados {n} cubos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
