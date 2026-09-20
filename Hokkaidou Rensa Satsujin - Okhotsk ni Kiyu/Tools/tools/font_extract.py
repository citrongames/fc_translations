#!/usr/bin/env python3
from pathlib import Path
import argparse
from okhotsk_common import read_ines
from rle_packbits import decode

# Confirmed for this ROM revision:
# PRG bank 0, CPU block begins at $8018. Bytes $8018-$801B are a header.
# RLE payload at PRG +0x001C decodes exactly 0x800 bytes used at CHR-RAM $1000-$17FF.
STREAM_PRG_OFF=0x001C
OUT_SIZE=0x0800
ALLOC_END_PRG_OFF=0x04F3

def main():
 ap=argparse.ArgumentParser(description='Extract the confirmed 0x800-byte static text-font CHR block from the ROM.')
 ap.add_argument('rom');ap.add_argument('-o','--out',default='font_chr_1000_17ff.bin');a=ap.parse_args()
 info=read_ines(a.rom);src=info['prg'][STREAM_PRG_OFF:ALLOC_END_PRG_OFF]
 out,used=decode(src,OUT_SIZE)
 if used != len(src): print(f'Warning: decoder used {used} of allocated {len(src)} bytes')
 Path(a.out).write_bytes(out);print(f'Wrote {a.out}: {len(out)} bytes; compressed source {used} bytes')
if __name__=='__main__':main()
