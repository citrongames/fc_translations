#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

TILE=16

def apply(data:bytes)->bytes:
    if len(data)!=0x800: raise ValueError(f'expected 0x800-byte / 128-tile font, got {len(data)}')
    b=bytearray(data)
    def cp(dst,src): b[dst*TILE:(dst+1)*TILE]=b[src*TILE:(src+1)*TILE]
    # User font: lowercase а..я at 41..61. Keep original UI arrows at 40
    # (right) and 3B (down). Mirror ю/я into ordinary direct kana slots 2C/2D.
    cp(0x2C,0x60) # ю
    cp(0x2D,0x61) # я
    # Password/name input also exposes original code $2E.  In RU it must be a
    # real Cyrillic glyph, not the leftover Japanese ん.  Mirror lowercase э
    # here; the normal text encoder still uses direct code $5F for э.
    cp(0x2E,0x5F) # э (input/password mirror)
    # User QA replacement for digit 0: the original oval 0 was too close to
    # Cyrillic О on the password screen.  Keep this asymmetric 8x8 zero in
    # BOTH the legacy digit slot $74 and direct RU digit slot $22.
    zero = bytes.fromhex('3C 46 4A 4A 52 52 62 3C 00 00 00 00 00 00 00 00')
    b[0x74*TILE:(0x74+1)*TILE] = zero
    # D0..D9 used to invoke glyphs 74..7D. D0..EF are dictionary tokens now,
    # so mirror 0..9 into spare direct tiles/codes 22..2B.
    for i in range(10): cp(0x22+i,0x74+i)
    return bytes(b)

def main():
    ap=argparse.ArgumentParser(description='Prepare user Russian font for v0.8: direct lowercase + direct digits.')
    ap.add_argument('input');ap.add_argument('output');a=ap.parse_args()
    out=apply(Path(a.input).read_bytes());Path(a.output).write_bytes(out)
    print('Preserved arrows 40/3B; installed distinct user 0 at 74/22; mirrored 60->2C (ю), 61->2D (я), 5F->2E (э input mirror), 74..7D -> 22..2B (digits 0..9)')
    print('Wrote:',a.output)
if __name__=='__main__':main()
