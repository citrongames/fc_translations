#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Murder Club (Famicom) safe in-place text inserter.

ВАЖНО:
- Этот вариант НЕ двигает строки и НЕ переносит указатели.
- Перевод должен помещаться в исходную byte-capacity.
- Конец исходного блока (00) остаётся на том же offset.
- Если перевод короче, остаток заполняется FF (пробелами).
  Это специально сделано, чтобы не сдвигать границы и не ломать
  существующие указатели/ссылки на части строк.

Игра действительно использует ссылки на середину некоторых строк,
поэтому такой режим намного безопаснее обычного "записать новый 00 раньше".
"""

from __future__ import annotations
import argparse
import csv
import hashlib
import re
import unicodedata
from pathlib import Path

EXPECTED_ROM_SHA1 = "bb1fb4700ad1cf83bd32acb640747f2a9d337238"


def load_tbl(path: Path):
    b2t = {}
    t2b = {}
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
        b = int(left, 16)
        b2t[b] = right
        if right and right != "<END>":
            # Нормализуем и саму таблицу так же, как вводимый текст.
            key = unicodedata.normalize("NFD", right)
            key = key.replace("\u3099", "゛").replace("\u309A", "゜")
            # Если одинаковый текст задан несколько раз, оставляем первый.
            t2b.setdefault(key, b)
    return b2t, t2b


def normalize_for_rom(s: str) -> str:
    # Разлагаем が -> か + dakuten, パ -> ハ + handakuten.
    s = unicodedata.normalize("NFD", s)
    s = s.replace("\u3099", "゛").replace("\u309A", "゜")
    # Небольшие удобные алиасы.
    s = s.replace("…", "・・・")
    s = s.replace("?", "？")
    return s


RAW_TOKEN = re.compile(r"<([0-9A-Fa-f]{2})>")
NAMED_TOKEN = re.compile(r"<[^<>]+>")


def display_length(text: str) -> int:
    """
    Count visible screen positions, not ROM bytes.

    Examples:
      じ -> 1 visible character, although it becomes 2 ROM bytes.
      <CURSOR_RIGHT> -> 1 visible tile.
    """
    text = unicodedata.normalize("NFC", text)
    count = 0
    i = 0
    while i < len(text):
        if text[i] == "<":
            m = RAW_TOKEN.match(text, i) or NAMED_TOKEN.match(text, i)
            if m:
                count += 1
                i = m.end()
                continue

        ch = text[i]
        if unicodedata.combining(ch):
            i += 1
            continue

        count += 1
        i += 1

    return count


def encode_text(text: str, t2b: dict[str, int]) -> bytes:
    text = normalize_for_rom(text)

    # Самые длинные словарные строки должны выигрывать у одиночных знаков.
    tokens = sorted(t2b.keys(), key=len, reverse=True)

    out = bytearray()
    i = 0
    while i < len(text):
        m = RAW_TOKEN.match(text, i)
        if m:
            out.append(int(m.group(1), 16))
            i = m.end()
            continue

        matched = None
        for tok in tokens:
            if text.startswith(tok, i):
                matched = tok
                break

        if matched is None:
            context = text[max(0, i-10):i+20]
            raise ValueError(
                f"Cannot encode character/text at position {i}: {text[i]!r}\n"
                f"Context: {context!r}\n"
                "Add a mapping to murder_club_ru.tbl (and, for a real translation, "
                "put the corresponding glyph into the game's CHR font)."
            )

        out.append(t2b[matched])
        i += len(matched)

    if 0x00 in out:
        raise ValueError("Encoded text contains 00 terminator")
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=Path)
    ap.add_argument("tsv", type=Path)
    ap.add_argument("-t", "--table", type=Path,
                    default=Path(__file__).with_name("murder_club_ru.tbl"))
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--force-rom", action="store_true",
                    help="allow a ROM with a different SHA-1")
    args = ap.parse_args()

    src = args.rom.read_bytes()
    if len(src) < 16 or src[:4] != b"NES\x1a":
        raise SystemExit("Not an iNES ROM")

    actual_sha = hashlib.sha1(src).hexdigest()
    if actual_sha != EXPECTED_ROM_SHA1 and not args.force_rom:
        raise SystemExit(
            "ROM SHA-1 differs from the tested dump.\n"
            f"actual: {actual_sha}\n"
            f"tested: {EXPECTED_ROM_SHA1}\n"
            "Use --force-rom only if you know the offsets are compatible."
        )

    if args.output.resolve() == args.rom.resolve():
        raise SystemExit("Refusing to overwrite the source ROM. Choose another -o path.")

    _, t2b = load_tbl(args.table)
    data = bytearray(src)

    changed = 0
    with args.tsv.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        required = {
            "id", "prg_offset", "capacity",
            "original_hex", "original_text", "translation"
        }
        missing = required - set(r.fieldnames or [])
        if missing:
            raise SystemExit(f"TSV missing columns: {sorted(missing)}")

        for row in r:
            translation = row["translation"]
            if translation == "":
                continue

            rid = row["id"]
            prg_off = int(row["prg_offset"], 16)

            # New v3 TSVs can specify an independent visual UI width limit.
            # Old TSVs remain compatible because the column is optional.
            display_limit_raw = (row.get("display_limit") or "").strip()
            if display_limit_raw:
                display_limit = int(display_limit_raw)
                visible_len = display_length(translation)
                if visible_len > display_limit:
                    raise SystemExit(
                        f"{rid}: translation uses {visible_len} visible characters, "
                        f"but this UI line allows only {display_limit}.\n"
                        f"PRG offset ${prg_off:05X}."
                    )

            file_off = prg_off + 16
            capacity = int(row["capacity"])
            original = bytes.fromhex(row["original_hex"])

            if len(original) != capacity:
                raise SystemExit(f"{rid}: original_hex length != capacity")

            current = bytes(data[file_off:file_off + capacity])
            if current != original:
                raise SystemExit(
                    f"{rid}: source ROM bytes no longer match the extracted TSV "
                    f"at PRG ${prg_off:05X}"
                )

            # Терминатор обязан остаться на исходной позиции.
            term_pos = file_off + capacity
            if data[term_pos] != 0x00:
                raise SystemExit(
                    f"{rid}: expected 00 terminator at file ${term_pos:05X}, "
                    f"found {data[term_pos]:02X}"
                )

            try:
                enc = encode_text(translation, t2b)
            except ValueError as e:
                raise SystemExit(f"{rid}: {e}")

            if len(enc) > capacity:
                raise SystemExit(
                    f"{rid}: translation is {len(enc)} bytes, capacity is {capacity}.\n"
                    f"PRG offset ${prg_off:05X}.\n"
                    "This safe inserter does not relocate text. Shorten/compress it "
                    "or leave this block for the later pointer-repacking stage."
                )

            data[file_off:file_off + capacity] = enc + bytes([0xFF]) * (capacity - len(enc))
            # data[term_pos] stays 00
            changed += 1
            print(f"{rid}: {len(enc)}/{capacity} bytes")

    args.output.write_bytes(data)
    print(f"Patched {changed} blocks -> {args.output}")
    print("Source ROM was not modified.")


if __name__ == "__main__":
    main()
