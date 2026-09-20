#!/usr/bin/env python3
from pathlib import Path
import argparse
try:
 from PIL import Image
except ImportError:
 raise SystemExit('Pillow is required. Linux: sudo apt install python3-pil   Windows: py -m pip install Pillow')

def q(v):
 # nearest of 255,170,85,0 -> NES plane value 0..3
 vals=[255,170,85,0]; return min(range(4),key=lambda i:abs(vals[i]-v))

def main():
 ap=argparse.ArgumentParser(description='Convert a 1:1 NES tile-sheet PNG back to 2bpp CHR. Use --scale if source was enlarged.')
 ap.add_argument('input');ap.add_argument('output');ap.add_argument('--scale',type=int,default=4);a=ap.parse_args()
 im=Image.open(a.input).convert('L');s=a.scale
 if im.width%(8*s) or im.height%(8*s): raise SystemExit('Image dimensions must be multiples of 8*scale')
 tw,th=im.width//(8*s),im.height//(8*s);out=bytearray()
 for ty in range(th):
  for tx in range(tw):
   p0=[0]*8;p1=[0]*8
   for y in range(8):
    for x in range(8):
     v=q(im.getpixel((tx*8*s+x*s,ty*8*s+y*s)))
     bit=7-x;p0[y]|=(v&1)<<bit;p1[y]|=((v>>1)&1)<<bit
   out.extend(bytes(p0+p1))
 Path(a.output).write_bytes(out);print(f'{tw*th} tiles -> {a.output}')
if __name__=='__main__':main()
