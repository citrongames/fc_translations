#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Murder Club (Famicom) text extractor.

Извлекает нуль-терминированные текстовые блоки в TSV.
По умолчанию сканирует основные диалоговые банки PRG.
С --all сканирует весь PRG и может поймать немного ложных совпадений.

ROM offsets:
  PRG offset = offset внутри PRG без 16-байтного iNES header
  file offset = реальный offset в .nes
"""

from __future__ import annotations
import argparse
import csv
import hashlib
import re
import unicodedata
from pathlib import Path

EXPECTED_ROM_SHA1 = "bb1fb4700ad1cf83bd32acb640747f2a9d337238"
EXPECTED_NOHEADER_SHA1 = "8c79c09a31470072eb0ed70e58d147b7b2cd0960"

# Основные текстовые банки.
# Последний банк содержит текст только примерно до PRG $EF20,
# дальше уже явно нетекстовые таблицы/код.
DIALOG_RANGES = [
    (0x4000, 0x6000),
    (0x6000, 0x8000),
    (0x8000, 0xA000),
    (0xA000, 0xC000),
    (0xC000, 0xE000),
    (0xE000, 0xEF20),
]

# Подтверждённый компактный блок меню/команд.
UI_RANGES = [
    (0x1C3BD, 0x1C509),
]

# 7 подтверждённых строк меню действий.
# Визуальный лимит каждой строки: максимум 10 символов.
COMMAND_MENU_OFFSETS = {
    0x1C3BD,  # そうさにでかける
    0x1C3C7,  # かんしきかにいく
    0x1C3D0,  # しりょうしつにいく
    0x1C3DA,  # けんじのところにいく
    0x1C3E6,  # とりしらべしつにいく
    0x1C3F2,  # セーブ
    0x1C3F7,  # ロード
}
COMMAND_MENU_DISPLAY_LIMIT = 10

# Подтверждённые однобайтовые словарные коды.
LOW_TEXT_CODES = set(range(0x05, 0x0E))


def load_tbl(path: Path):
    b2t = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip("\n\r")
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        left = left.strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", left):
            continue
        b2t[int(left, 16)] = right
    return b2t


def compose_kana(s: str) -> str:
    # В ROM дакутен/хандакутен отдельными тайлами.
    # Для TXT удобнее показывать が/ぱ как обычные Unicode-символы.
    s = s.replace("゛", "\u3099").replace("゜", "\u309A")
    return unicodedata.normalize("NFC", s)


def decode_bytes(data: bytes, b2t: dict[int, str]) -> str:
    out = []
    for b in data:
        if b in b2t and b != 0x00:
            out.append(b2t[b])
        else:
            out.append(f"<{b:02X}>")
    return compose_kana("".join(out))


def is_text_candidate(data: bytes, min_len: int) -> bool:
    if len(data) < min_len:
        return False
    valid = 0
    visible = 0
    for b in data:
        if b >= 0x80 or b in LOW_TEXT_CODES:
            valid += 1
        if b >= 0x80:
            visible += 1
    # Для основных банков настоящий текст почти полностью состоит
    # из $80-$FF + словарных $05-$0D.
    return visible >= 3 and valid / len(data) >= 0.97


def iter_zero_strings(prg: bytes, start: int, end: int, min_len: int):
    pos = start
    while pos < end:
        zero = prg.find(b"\x00", pos, end)
        if zero < 0:
            break
        raw = prg[pos:zero]
        if is_text_candidate(raw, min_len):
            yield pos, raw
        pos = zero + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=Path)
    ap.add_argument("-t", "--table", type=Path,
                    default=Path(__file__).with_name("murder_club_jp.tbl"))
    ap.add_argument("-o", "--output", type=Path, default=Path("dialogues.tsv"))
    ap.add_argument("--all", action="store_true",
                    help="scan whole PRG instead of the known text ranges")
    ap.add_argument("--include-ui", action="store_true",
                    help="also extract the confirmed menu/action block at PRG $1C3BD-$1C508")
    ap.add_argument("--min-len", type=int, default=4)
    args = ap.parse_args()

    rom = args.rom.read_bytes()
    if len(rom) < 16 or rom[:4] != b"NES\x1a":
        raise SystemExit("Not an iNES ROM")

    prg_size = rom[4] * 16384
    prg = rom[16:16 + prg_size]
    if len(prg) != prg_size:
        raise SystemExit("Truncated PRG")

    full_sha = hashlib.sha1(rom).hexdigest()
    nohdr_sha = hashlib.sha1(rom[16:]).hexdigest()
    if full_sha != EXPECTED_ROM_SHA1:
        print("WARNING: ROM SHA-1 differs from the tested dump:")
        print(" actual :", full_sha)
        print(" tested :", EXPECTED_ROM_SHA1)
    if nohdr_sha != EXPECTED_NOHEADER_SHA1:
        print("WARNING: headerless SHA-1 differs from the tested dump:")
        print(" actual :", nohdr_sha)
        print(" tested :", EXPECTED_NOHEADER_SHA1)

    b2t = load_tbl(args.table)

    if args.all:
        ranges = [(0, len(prg))]
    else:
        ranges = list(DIALOG_RANGES)
        if args.include_ui:
            ranges += UI_RANGES

    rows = []
    seq = 1
    for start, end in ranges:
        end = min(end, len(prg))
        for off, raw in iter_zero_strings(prg, start, end, args.min_len):
            display_limit = ""
            if off in COMMAND_MENU_OFFSETS:
                display_limit = str(COMMAND_MENU_DISPLAY_LIMIT)

            rows.append({
                "id": f"D{seq:04d}",
                "bank8k": f"{off // 0x2000:02X}",
                "prg_offset": f"{off:05X}",
                "file_offset": f"{off + 16:05X}",
                "capacity": str(len(raw)),
                "display_limit": display_limit,
                "original_hex": raw.hex(" ").upper(),
                "original_text": decode_bytes(raw, b2t),
                "translation": "",
            })
            seq += 1

    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id", "bank8k", "prg_offset", "file_offset",
                "capacity", "display_limit",
                "original_hex", "original_text", "translation"
            ],
            delimiter="\t",
            quoting=csv.QUOTE_MINIMAL,
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Extracted {len(rows)} text blocks -> {args.output}")
    print("Edit only the 'translation' column. Leave it empty to keep a block unchanged.")


if __name__ == "__main__":
    main()
