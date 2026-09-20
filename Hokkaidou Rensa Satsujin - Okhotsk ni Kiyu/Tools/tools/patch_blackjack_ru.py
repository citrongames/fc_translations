#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

# PRG-relative locations (iNES header is handled by patch()).
BLACKJACK_OPPONENT_NAME_PRG = 0x00934
BLACKJACK_OPPONENT_NAME_JP = bytes.fromhex('47 71 6E')  # シュン in the static card-screen nametable template
BLACKJACK_OPPONENT_NAME_RU = bytes.fromhex('13 20 0F')  # СЮН

# Separate blackjack name compositor.  Original JP code treats every byte >=40 as
# dakuten/handakuten kana.  RU lowercase lives at 41..5F, so raise the JP threshold
# above all RU text codes. FF terminator is checked immediately before this CMP.
BLACKJACK_NAME_THRESHOLD_PRG = 0x3F5B2
BLACKJACK_NAME_THRESHOLD_JP = b'\x40'
BLACKJACK_NAME_THRESHOLD_RU = b'\xF0'

# Decimal formatter used by blackjack [FD:$00]/[FD:$01] RAM strings (and other
# dynamic decimal displays).  Original writes D0..D9 text codes.  v0.8 uses
# D0..EF as the secondary RU dictionary, so those bytes expand into phrases.
# Write the direct RU digit codes 22..2B instead.
BLACKJACK_DECIMAL_FORMATTER_PRG = 0x3F9AC
BLACKJACK_DECIMAL_FORMATTER_JP = bytes.fromhex(
    '48 A9 01 85 CB 8A 09 D0 91 14 C8 A9 FF 91 14 68 60'
)
BLACKJACK_DECIMAL_FORMATTER_RU = bytes.fromhex(
    '48 E6 CB 8A 18 69 22 91 14 C8 A9 FF 91 14 68 60 EA'
)
assert len(BLACKJACK_DECIMAL_FORMATTER_JP) == len(BLACKJACK_DECIMAL_FORMATTER_RU) == 17


def _patch_exact(out: bytearray, base: int, old: bytes, new: bytes, label: str) -> None:
    cur = bytes(out[base:base+len(old)])
    if cur == new:
        return
    if cur != old:
        raise ValueError(f'{label}: unexpected bytes at PRG ${base:05X}: {cur.hex(" ").upper()}')
    out[base:base+len(new)] = new


def patch(raw: bytes) -> bytes:
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    if raw[4] != 16:
        raise ValueError(f'Expected 16 PRG banks, got {raw[4]}')
    prg_off = 16 + (512 if raw[6] & 4 else 0)
    out = bytearray(raw)
    _patch_exact(out, prg_off + BLACKJACK_OPPONENT_NAME_PRG,
                 BLACKJACK_OPPONENT_NAME_JP, BLACKJACK_OPPONENT_NAME_RU,
                 'blackjack opponent name')
    _patch_exact(out, prg_off + BLACKJACK_NAME_THRESHOLD_PRG,
                 BLACKJACK_NAME_THRESHOLD_JP, BLACKJACK_NAME_THRESHOLD_RU,
                 'blackjack player-name dakuten threshold')
    _patch_exact(out, prg_off + BLACKJACK_DECIMAL_FORMATTER_PRG,
                 BLACKJACK_DECIMAL_FORMATTER_JP, BLACKJACK_DECIMAL_FORMATTER_RU,
                 'dynamic decimal formatter')
    return bytes(out)


def main():
    ap=argparse.ArgumentParser(description='Patch blackjack static names, RU player-name compositor and D0..D9 dynamic decimal output.')
    ap.add_argument('rom'); ap.add_argument('-o','--out',required=True)
    a=ap.parse_args()
    raw=Path(a.rom).read_bytes(); out=patch(raw); Path(a.out).write_bytes(out)
    print('Blackjack RU patches:')
    print('  シュン static label -> СЮН')
    print('  player-name JP dakuten threshold $40 -> $F0')
    print('  dynamic decimal D0..D9 -> direct RU digits $22..$2B')
    print('Wrote:',a.out)

if __name__=='__main__': main()
