#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Murder Club (Famicom) CHR extractor v5.

Known physical CHR bank 0 layout:
  $00-$7F  main text font
  $80-$BF  password font (separate 64-symbol set)
  $C0-$FF  title-screen graphics/name

Exports each region separately to avoid accidental overwrites.
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

RGB_FOR_VALUE = [
    (255, 255, 255),
    (170, 170, 170),
    (85, 85, 85),
    (0, 0, 0),
]


def ines_layout(rom: bytes):
    if len(rom) < 16 or rom[:4] != b"NES\x1a":
        raise SystemExit("Not an iNES ROM")
    trainer = 512 if (rom[6] & 0x04) else 0
    prg_size = rom[4] * 16384
    chr_size = rom[5] * 8192
    chr_start = 16 + trainer + prg_size
    if chr_size == 0:
        raise SystemExit("ROM uses CHR RAM; no CHR ROM to extract")
    if chr_start + chr_size > len(rom):
        raise SystemExit("Truncated ROM")
    return chr_start, chr_size


def tile_to_values(tile: bytes):
    vals = [[0] * 8 for _ in range(8)]
    for y in range(8):
        p0 = tile[y]
        p1 = tile[y + 8]
        for x in range(8):
            bit = 7 - x
            vals[y][x] = ((p0 >> bit) & 1) | (((p1 >> bit) & 1) << 1)
    return vals


def tiles_to_png(tile_bytes: bytes, columns: int, path: Path):
    if len(tile_bytes) % 16:
        raise ValueError("CHR length is not tile-aligned")
    tile_count = len(tile_bytes) // 16
    rows = (tile_count + columns - 1) // columns
    img = Image.new("RGB", (columns * 8, rows * 8), RGB_FOR_VALUE[0])
    px = img.load()

    for n in range(tile_count):
        tx = (n % columns) * 8
        ty = (n // columns) * 8
        vals = tile_to_values(tile_bytes[n * 16:(n + 1) * 16])
        for y in range(8):
            for x in range(8):
                px[tx + x, ty + y] = RGB_FOR_VALUE[vals[y][x]]
    img.save(path)


def save_region(outdir: Path, name: str, data: bytes, columns: int):
    (outdir / f"{name}.chr").write_bytes(data)
    tiles_to_png(data, columns, outdir / f"{name}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=Path)
    ap.add_argument("-o", "--output-dir", type=Path, default=Path("chr_export"))
    ap.add_argument("--all-banks", action="store_true")
    ap.add_argument("--force-rom", action="store_true")
    args = ap.parse_args()

    rom = args.rom.read_bytes()
    sha1 = hashlib.sha1(rom).hexdigest()
    if sha1 != EXPECTED_ROM_SHA1 and not args.force_rom:
        raise SystemExit(
            "ROM SHA-1 differs from the tested dump.\n"
            f"actual: {sha1}\n"
            f"tested: {EXPECTED_ROM_SHA1}\n"
            "Use --force-rom only for a compatible modified ROM."
        )

    chr_start, chr_size = ines_layout(rom)
    chr_data = rom[chr_start:chr_start + chr_size]
    bank0 = chr_data[:0x1000]

    args.output_dir.mkdir(parents=True, exist_ok=True)

    (args.output_dir / "chr_full.bin").write_bytes(chr_data)
    (args.output_dir / "chr_bank00_4k.chr").write_bytes(bank0)
    tiles_to_png(bank0, 16, args.output_dir / "chr_bank00_full.png")

    # Main text font: physical $00-$7F, labelled by text bytes $80-$FF.
    main_font = bank0[0x000:0x800]
    save_region(args.output_dir, "font_direct_80_FF", main_font, 16)

    # Separate password set: physical $80-$BF.
    password = bank0[0x800:0xC00]
    save_region(args.output_dir, "password_font_80_BF", password, 16)

    # Title-screen region: physical $C0-$FF.
    title = bank0[0xC00:0x1000]
    save_region(args.output_dir, "title_region_C0_FF", title, 16)

    # Nearest-neighbour previews.
    for name in ("font_direct_80_FF", "password_font_80_BF", "title_region_C0_FF"):
        p = args.output_dir / f"{name}.png"
        img = Image.open(p)
        img.resize(
            (img.width * 4, img.height * 4),
            Image.Resampling.NEAREST
        ).save(args.output_dir / f"{name}_preview_4x.png")

    if args.all_banks:
        bank_count = chr_size // 0x1000
        for i in range(bank_count):
            b = chr_data[i * 0x1000:(i + 1) * 0x1000]
            tiles_to_png(b, 16, args.output_dir / f"chr_bank{i:02X}.png")

    print(f"CHR start in ROM: ${chr_start:05X}")
    print(f"CHR size: {chr_size} bytes")
    print("Known bank 0 layout:")
    print("  physical $00-$7F : main text font")
    print("  physical $80-$BF : password font")
    print("  physical $C0-$FF : title-screen graphics/name")
    print("Created:")
    for p in sorted(args.output_dir.iterdir()):
        print(" ", p.name)


if __name__ == "__main__":
    main()
