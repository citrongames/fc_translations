#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib
from PIL import Image

H=16; PRG_UNIT=0x4000; CHR_BANK=0x2000
LEVELS=(0,85,170,255)

def nearest(v): return min(range(4),key=lambda i:abs(v-LEVELS[i]))
def chr_start(rom): return H+rom[4]*PRG_UNIT

def encode_tile(im,x0,y0):
    p0=[];p1=[]
    for y in range(8):
        a=b=0
        for x in range(8):
            v=nearest(im.getpixel((x0+x,y0+y)))
            a=(a<<1)|(v&1);b=(b<<1)|((v>>1)&1)
        p0.append(a);p1.append(b)
    return bytes(p0+p1)

def main():
    ap=argparse.ArgumentParser(description='Insert a PNG sheet back into one NES 8 KiB CHR bank')
    ap.add_argument('rom',type=Path)
    ap.add_argument('png',type=Path)
    ap.add_argument('--bank',type=int,required=True)
    ap.add_argument('-o','--output',type=Path,default=Path('chr_patched.nes'))
    a=ap.parse_args()
    base=a.rom.read_bytes()
    if base[:4]!=b'NES\x1a':raise SystemExit('Not iNES')
    if not 0<=a.bank<base[5]:raise SystemExit(f'bank must be 0..{base[5]-1}')
    im=Image.open(a.png).convert('L')
    if im.width%8 or im.height%8:raise SystemExit('PNG dimensions must be multiples of 8')
    tiles=(im.width//8)*(im.height//8)
    if tiles!=512:raise SystemExit(f'Expected exactly 512 tiles for an 8 KiB bank; PNG has {tiles}')
    raw=bytearray()
    for ty in range(im.height//8):
        for tx in range(im.width//8):raw+=encode_tile(im,tx*8,ty*8)
    rom=bytearray(base);start=chr_start(rom)+a.bank*CHR_BANK
    rom[start:start+CHR_BANK]=raw
    a.output.write_bytes(rom)
    print(f'Wrote {a.output}; bank={a.bank}; SHA256={hashlib.sha256(rom).hexdigest()}')
if __name__=='__main__':main()
