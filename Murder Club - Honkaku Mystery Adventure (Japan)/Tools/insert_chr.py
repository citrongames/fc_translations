#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Murder Club (Famicom) CHR PNG inserter v5.

Safe named regions in physical CHR bank 0:
  main-font : tiles $00-$7F  (128x64 PNG)
  password  : tiles $80-$BF  (128x32 PNG)
  title     : tiles $C0-$FF  (128x32 PNG)
  bank0     : tiles $00-$FF  (128x128 PNG)

Default is main-font.

WARNING:
  password and title are NOT free space.
  Patch them only when intentionally editing those screens.
"""

from __future__ import annotations
import argparse
import hashlib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit(
        "Pillow is required.\n"
        "Windows: py -m pip install pillow\n"
        "Kubuntu/Debian: sudo apt install python3-pil"
    )

EXPECTED_ROM_SHA1 = "bb1fb4700ad1cf83bd32acb640747f2a9d337238"

RGB_TO_VALUE = {
    (255, 255, 255): 0,
    (170, 170, 170): 1,
    (85, 85, 85): 2,
    (0, 0, 0): 3,
}

REGIONS = {
    "main-font": {
        "chr_offset": 0x000,
        "size": 0x800,
        "png_size": (128, 64),
        "desc": "main text font: physical tiles $00-$7F",
    },
    "password": {
        "chr_offset": 0x800,
        "size": 0x400,
        "png_size": (128, 32),
        "desc": "password font: physical tiles $80-$BF",
    },
    "title": {
        "chr_offset": 0xC00,
        "size": 0x400,
        "png_size": (128, 32),
        "desc": "title-screen region: physical tiles $C0-$FF",
    },
    "bank0": {
        "chr_offset": 0x000,
        "size": 0x1000,
        "png_size": (128, 128),
        "desc": "full physical CHR bank 0: tiles $00-$FF",
    },
}


def ines_layout(rom: bytes):
    if len(rom) < 16 or rom[:4] != b"NES\x1a":
        raise SystemExit("Not an iNES ROM")
    trainer = 512 if (rom[6] & 0x04) else 0
    prg_size = rom[4] * 16384
    chr_size = rom[5] * 8192
    chr_start = 16 + trainer + prg_size
    if chr_size == 0:
        raise SystemExit("ROM uses CHR RAM; no CHR ROM to patch")
    if chr_start + chr_size > len(rom):
        raise SystemExit("Truncated ROM")
    return chr_start, chr_size


def png_to_chr(path: Path, expected_size: tuple[int, int]) -> bytes:
    img = Image.open(path).convert("RGB")
    if img.size != expected_size:
        raise SystemExit(
            f"Wrong PNG size: {img.size[0]}x{img.size[1]}.\n"
            f"Expected exactly {expected_size[0]}x{expected_size[1]}."
        )

    allowed = set(RGB_TO_VALUE)
    bad = set()
    for y in range(img.height):
        for x in range(img.width):
            rgb = img.getpixel((x, y))
            if rgb not in allowed:
                bad.add(rgb)
                if len(bad) >= 12:
                    break
        if len(bad) >= 12:
            break

    if bad:
        sample = ", ".join(map(str, sorted(bad)))
        raise SystemExit(
            "PNG contains colors outside the exact 4-color CHR palette.\n"
            f"Examples: {sample}\n"
            "Use Pencil/no antialiasing and only:\n"
            "  255,255,255\n"
            "  170,170,170\n"
            "   85, 85, 85\n"
            "    0,  0,  0"
        )

    cols = img.width // 8
    rows = img.height // 8
    out = bytearray()

    for ty in range(rows):
        for tx in range(cols):
            p0_rows = []
            p1_rows = []
            for y in range(8):
                p0 = 0
                p1 = 0
                for x in range(8):
                    v = RGB_TO_VALUE[img.getpixel((tx * 8 + x, ty * 8 + y))]
                    bit = 7 - x
                    p0 |= (v & 1) << bit
                    p1 |= ((v >> 1) & 1) << bit
                p0_rows.append(p0)
                p1_rows.append(p1)
            out.extend(p0_rows)
            out.extend(p1_rows)

    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=Path)
    ap.add_argument("png", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument(
        "--region",
        choices=sorted(REGIONS),
        default="main-font",
        help="CHR region to patch; default: main-font"
    )
    ap.add_argument(
        "--bank0",
        action="store_true",
        help="legacy alias for --region bank0"
    )
    ap.add_argument("--force-rom", action="store_true")
    args = ap.parse_args()

    if args.bank0:
        args.region = "bank0"

    src = args.rom.read_bytes()
    if args.output.resolve() == args.rom.resolve():
        raise SystemExit("Refusing to overwrite the source ROM.")

    sha1 = hashlib.sha1(src).hexdigest()
    if sha1 != EXPECTED_ROM_SHA1 and not args.force_rom:
        raise SystemExit(
            "ROM SHA-1 differs from the tested original.\n"
            f"actual: {sha1}\n"
            f"tested: {EXPECTED_ROM_SHA1}\n"
            "Use --force-rom for your already text-patched compatible ROM."
        )

    chr_start, _ = ines_layout(src)
    info = REGIONS[args.region]
    patch = png_to_chr(args.png, info["png_size"])

    if len(patch) != info["size"]:
        raise SystemExit(
            f"Internal size mismatch: got {len(patch)}, expected {info['size']}"
        )

    patch_off = chr_start + info["chr_offset"]
    data = bytearray(src)
    data[patch_off:patch_off + len(patch)] = patch
    args.output.write_bytes(data)

    print(f"Patched: {info['desc']}")
    print(f"ROM offset: ${patch_off:05X}")
    print(f"Bytes written: {len(patch)}")
    print(f"Output: {args.output}")
    print("Source ROM was not modified.")


if __name__ == "__main__":
    main()
