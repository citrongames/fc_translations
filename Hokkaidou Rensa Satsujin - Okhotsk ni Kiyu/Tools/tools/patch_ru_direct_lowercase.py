#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import read_ines, PRG_BANK_SIZE

CPU_ADDR=0xC743
PRG_BANK=15
BANK_CPU_BASE=0xC000
ORIGINAL=bytes.fromhex('8A A2 7E C9 15 90 03 E8 E9 05 86 6B 85 6C 20 A5 C6 20 9A C6 60')
PATCHED=bytes.fromhex('8A 18 69 40 85 6C A9 00 85 6B 20 A5 C6 20 9A C6 60 EA EA EA EA')

def patch(data:bytes)->bytes:
    info=read_ines_bytes(data)
    off=info['prg_offset']+PRG_BANK*PRG_BANK_SIZE+(CPU_ADDR-BANK_CPU_BASE)
    cur=data[off:off+len(ORIGINAL)]
    if cur==PATCHED:
        return data
    if cur!=ORIGINAL:
        raise ValueError(f'unexpected bytes at CPU ${CPU_ADDR:04X}: {cur.hex(" ").upper()}')
    out=bytearray(data);out[off:off+len(PATCHED)]=PATCHED
    return bytes(out)

def read_ines_bytes(raw:bytes):
    if len(raw)<16 or raw[:4]!=b'NES\x1a': raise ValueError('Not an iNES ROM')
    trainer=bool(raw[6]&4); off=16+(512 if trainer else 0)
    return {'prg_offset':off}

def main():
    ap=argparse.ArgumentParser(description='Patch Okhotsk text renderer: bytes 40..5F become direct lowercase glyphs 40..5F.')
    ap.add_argument('rom');ap.add_argument('-o','--out',required=True);args=ap.parse_args()
    raw=Path(args.rom).read_bytes(); out=patch(raw);Path(args.out).write_bytes(out)
    print(f'Patched direct lowercase handler at CPU ${CPU_ADDR:04X}: 40..5F -> glyph 40..5F')
    print(f'Wrote: {args.out}')
if __name__=='__main__':main()
