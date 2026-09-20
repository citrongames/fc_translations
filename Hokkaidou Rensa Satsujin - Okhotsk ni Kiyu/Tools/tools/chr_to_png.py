#!/usr/bin/env python3
from pathlib import Path
import argparse
try:
 from PIL import Image
except ImportError:
 raise SystemExit('Pillow is required. Linux: sudo apt install python3-pil   Windows: py -m pip install Pillow')

def tile_pixels(t):
 px=[]
 for y in range(8):
  a=t[y];b=t[y+8]
  px.append([((a>>(7-x))&1)|(((b>>(7-x))&1)<<1) for x in range(8)])
 return px

def main():
 ap=argparse.ArgumentParser(description='Render NES 2bpp CHR binary to a PNG tile sheet.')
 ap.add_argument('input');ap.add_argument('output');ap.add_argument('--columns',type=int,default=16);ap.add_argument('--scale',type=int,default=4);a=ap.parse_args()
 data=Path(a.input).read_bytes()
 if len(data)%16: raise SystemExit('CHR length must be a multiple of 16 bytes')
 n=len(data)//16;rows=(n+a.columns-1)//a.columns;s=a.scale
 im=Image.new('L',(a.columns*8*s,rows*8*s),255)
 vals=(255,170,85,0)
 for i in range(n):
  p=tile_pixels(data[i*16:(i+1)*16]); ox=(i%a.columns)*8*s;oy=(i//a.columns)*8*s
  for y in range(8):
   for x in range(8):
    v=vals[p[y][x]]
    for yy in range(s):
     for xx in range(s): im.putpixel((ox+x*s+xx,oy+y*s+yy),v)
 im.save(a.output);print(a.output)
if __name__=='__main__':main()
