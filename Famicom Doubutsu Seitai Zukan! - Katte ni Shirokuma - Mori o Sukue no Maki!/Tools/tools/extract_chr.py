#!/usr/bin/env python3
from pathlib import Path
import argparse
from PIL import Image

H=16; PRG_UNIT=0x4000; CHR_BANK=0x2000; TILE=16
PALETTE=(0,85,170,255)

def chr_start(rom): return H+rom[4]*PRG_UNIT

def decode_tile(raw):
    px=[]
    for y in range(8):
        p0=raw[y];p1=raw[y+8]
        row=[]
        for x in range(8):
            sh=7-x;row.append(((p1>>sh)&1)*2+((p0>>sh)&1))
        px.append(row)
    return px

def main():
    ap=argparse.ArgumentParser(description='Extract NES 2bpp CHR bank(s) to indexed-looking PNG sheets')
    ap.add_argument('rom',type=Path)
    ap.add_argument('-o','--output-dir',type=Path,default=Path('chr_dump'))
    ap.add_argument('--bank',type=int,help='8 KiB CHR bank index; omit to export all')
    ap.add_argument('--columns',type=int,default=16)
    a=ap.parse_args()
    rom=a.rom.read_bytes()
    if rom[:4]!=b'NES\x1a':raise SystemExit('Not iNES')
    n=rom[5]
    banks=[a.bank] if a.bank is not None else list(range(n))
    a.output_dir.mkdir(parents=True,exist_ok=True)
    start=chr_start(rom)
    for bank in banks:
        if not 0<=bank<n:raise SystemExit(f'CHR bank {bank} out of range 0..{n-1}')
        data=rom[start+bank*CHR_BANK:start+(bank+1)*CHR_BANK]
        tiles=len(data)//TILE;cols=a.columns;rows=(tiles+cols-1)//cols
        im=Image.new('L',(cols*8,rows*8),0);pix=im.load()
        for t in range(tiles):
            tile=decode_tile(data[t*16:t*16+16]);tx=(t%cols)*8;ty=(t//cols)*8
            for y in range(8):
                for x in range(8):pix[tx+x,ty+y]=PALETTE[tile[y][x]]
        out=a.output_dir/f'chr_bank_{bank:02d}.png';im.save(out)
        print(out)
if __name__=='__main__':main()
