#!/usr/bin/env python3
import argparse, struct
from okhotsk_common import *

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('rom'); a=ap.parse_args(); i=read_ines(a.rom)
 print('SHA256:',i['sha256']); print('PRG banks:',i['prg_banks'],f'({len(i["prg"])} bytes)'); print('CHR-ROM banks:',i['chr_banks']); print('Mapper:',i['mapper'])
 r=text_region(i); p=read_pointer_table(r); d=dictionary(r,p)
 print('Text region: PRG banks A-D, 0x10000 bytes'); print('Pointer count:',len(p)); print(f'Dictionary: 0x{p[0]:04X}-0x{p[1]-1:04X}, entries={len(d)}')
 print('First pointers:', ' '.join(f'{x:04X}' for x in p[:16]))
if __name__=='__main__': main()
