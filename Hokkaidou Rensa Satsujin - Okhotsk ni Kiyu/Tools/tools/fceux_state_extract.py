#!/usr/bin/env python3
from __future__ import annotations
import argparse, zlib
from pathlib import Path

TAGS={b'RAM\x00':'cpu_ram.bin',b'NTAR':'nametable.bin',b'PRAM':'palette.bin',b'CHRR':'chr_ram.bin',b'WRAM':'wram.bin'}

def main():
 ap=argparse.ArgumentParser(description='Extract useful memory blocks from an FCEUX .fc0 save state.')
 ap.add_argument('state'); ap.add_argument('-o','--out',default='fceux_state_dump'); a=ap.parse_args()
 raw=Path(a.state).read_bytes()
 if raw[:4]!=b'FCSX': raise SystemExit('Not an FCEUX FCSX state')
 # Current FCEUX state used here has a 16-byte outer header and a zlib payload.
 try: dec=zlib.decompress(raw[16:])
 except Exception as e: raise SystemExit(f'Cannot zlib-decompress payload at +0x10: {e}')
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True);(out/'state_decompressed.bin').write_bytes(dec)
 for tag,name in TAGS.items():
  pos=dec.find(tag)
  if pos<0: print(f'{tag!r}: not found'); continue
  size=int.from_bytes(dec[pos+4:pos+8],'little'); data=dec[pos+8:pos+8+size]
  (out/name).write_bytes(data); print(f'{name}: {size} bytes (tag @ 0x{pos:X})')
if __name__=='__main__': main()
