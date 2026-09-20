#!/usr/bin/env python3
from pathlib import Path
import argparse
from okhotsk_common import read_ines
from rle_packbits import encode_exact_length
from font_extract import STREAM_PRG_OFF,OUT_SIZE,ALLOC_END_PRG_OFF


def png_to_chr_bytes(path, scale=4):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit('Pillow is required for PNG input. Linux: sudo apt install python3-pil   Windows: py -m pip install Pillow')
    im=Image.open(path).convert('L'); s=scale
    if im.width%(8*s) or im.height%(8*s):
        raise SystemExit('PNG dimensions must be multiples of 8*scale')
    tw,th=im.width//(8*s),im.height//(8*s)
    vals=[255,170,85,0]
    def q(v): return min(range(4),key=lambda i:abs(vals[i]-v))
    out=bytearray()
    for ty in range(th):
        for tx in range(tw):
            p0=[0]*8;p1=[0]*8
            for y in range(8):
                for x in range(8):
                    v=q(im.getpixel((tx*8*s+x*s,ty*8*s+y*s)))
                    bit=7-x;p0[y]|=(v&1)<<bit;p1[y]|=((v>>1)&1)<<bit
            out.extend(bytes(p0+p1))
    return bytes(out)


def main():
    ap=argparse.ArgumentParser(description='Recompress and insert the confirmed 0x800-byte font CHR block. Input may be .bin or PNG exported by chr_to_png.py.')
    ap.add_argument('rom');ap.add_argument('font');ap.add_argument('-o','--out',required=True)
    ap.add_argument('--scale',type=int,default=4,help='PNG scale used by chr_to_png.py (default 4)')
    a=ap.parse_args()
    info=read_ines(a.rom)
    font=png_to_chr_bytes(a.font,a.scale) if Path(a.font).suffix.lower()=='.png' else Path(a.font).read_bytes()
    if len(font)!=OUT_SIZE: raise SystemExit(f'Font must be exactly 0x{OUT_SIZE:X} bytes; got 0x{len(font):X}')
    stream_len=ALLOC_END_PRG_OFF-STREAM_PRG_OFF
    try:
        packed=encode_exact_length(font,stream_len)
    except ValueError as e:
        raise SystemExit(str(e))
    raw=bytearray(info['raw']);off=info['prg_offset']+STREAM_PRG_OFF
    # IMPORTANT: preserve the original stream length exactly.  Another graphics
    # substream begins immediately at PRG 0x04F3 and the runtime advances to it
    # sequentially.  A shorter but otherwise valid RLE stream misaligns that
    # next substream and breaks the name/password character screens.
    raw[off:off+stream_len]=packed
    Path(a.out).write_bytes(raw);print(f'Inserted exact-length font stream: {len(packed)} bytes -> {a.out}')
if __name__=='__main__':main()
