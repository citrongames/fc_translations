#!/usr/bin/env python3
import argparse
from okhotsk_common import *
def main():
 ap=argparse.ArgumentParser();ap.add_argument('rom');a=ap.parse_args();i=read_ines(a.rom);r=text_region(i);p=read_pointer_table(r);d=dictionary(r,p)
 for n,e in enumerate(d):
  s,_=decode_bytes(e,d,stop_at_ff=False);print(f'{0x60+n:02X}\t{e.hex(" ").upper()}\t{s.replace(chr(10),"\\n")}')
if __name__=='__main__':main()
