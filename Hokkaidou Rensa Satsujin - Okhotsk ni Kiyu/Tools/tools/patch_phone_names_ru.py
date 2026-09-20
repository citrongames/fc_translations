#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import RU_UPPER_ENC

# Special fixed-slot surname table used only when a dialled telephone number
# resolves to an unrelated/wrong-number household.  It is NOT part of the
# normal root/F2 script graph.
#
# Text-region offset $0E4E in PRG bank A -> PRG-relative $28E4E.
PHONE_TABLE_TEXT = 0x0E4E
PHONE_TABLE_PRG = 0x0A * 0x4000 + PHONE_TABLE_TEXT
SLOT_SIZE = 5
SLOT_COUNT = 10

JP_NAMES = (
    'すずき','さとう','やまだ','たなか','なかむら',
    'いとう','もりた','ふじた','きむら','さわだ',
)
# Exact original bytes from the studied FC ROM.  Each surname occupies a fixed
# 5-byte slot, terminated/padded with FF.
JP_TABLE = bytes.fromhex(
    '08 48 02 FF FF '
    '06 0F 17 FF FF '
    '24 1F 4B FF FF '
    '0B 1A 01 FF FF '
    '1A 01 21 27 FF '
    '16 0F 17 FF FF '
    '23 28 0B FF FF '
    '12 47 0B FF FF '
    '02 21 27 FF FF '
    '06 2C 4B FF FF'
)

# These callers are explicitly wrong-number strangers and never participate in
# the mystery.  Russian transliterations of many originals exceed the 4-letter
# payload limit, so use short, ordinary Japanese surnames that fit naturally.
# Two originals (Sato/Ito) are preserved because their Russian forms fit.
RU_NAMES = (
    'КАТО', 'САТО', 'АБЭ', 'ОДА', 'АОКИ',
    'ИТО', 'МОРИ', 'ХАРА', 'ОНО', 'КУБО',
)


def encode_slot(name: str) -> bytes:
    try:
        body = bytes(RU_UPPER_ENC[ch] for ch in name)
    except KeyError as e:
        raise ValueError(f'Unsupported phone-name character: {e.args[0]!r}') from None
    if len(body) > SLOT_SIZE - 1:
        raise ValueError(f'Phone surname {name!r} needs {len(body)} glyphs; max is {SLOT_SIZE-1}')
    return body + b'\xFF' * (SLOT_SIZE - len(body))


RU_TABLE = b''.join(encode_slot(x) for x in RU_NAMES)
assert len(JP_TABLE) == len(RU_TABLE) == SLOT_COUNT * SLOT_SIZE


def patch(raw: bytes, *, allow_already_patched: bool = True) -> bytes:
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    if raw[4] != 16:
        raise ValueError(f'Expected 16 PRG banks, got {raw[4]}')
    prg_off = 16 + (512 if raw[6] & 4 else 0)
    out = bytearray(raw)
    a = prg_off + PHONE_TABLE_PRG
    b = a + len(JP_TABLE)
    cur = bytes(out[a:b])
    if cur == RU_TABLE and allow_already_patched:
        return bytes(out)
    if cur != JP_TABLE:
        raise ValueError(
            f'phone surname table: unexpected bytes at text ${PHONE_TABLE_TEXT:04X}: {cur.hex(" ")}'
        )
    out[a:b] = RU_TABLE
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description='Patch the fixed 10x5 wrong-number surname table to short Russian-display Japanese surnames.')
    ap.add_argument('rom')
    ap.add_argument('-o','--out',required=True)
    args = ap.parse_args()
    raw = Path(args.rom).read_bytes()
    out = patch(raw)
    Path(args.out).write_bytes(out)
    print('Patched wrong-number surname table at text $0E4E-$0E7F:')
    for jp,ru in zip(JP_NAMES,RU_NAMES):
        print(f'  {jp} -> {ru}')
    print('Wrote:', args.out)

if __name__ == '__main__':
    main()
