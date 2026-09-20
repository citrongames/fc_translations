#!/usr/bin/env python3
from pathlib import Path
import argparse,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import katte_codec as kc

OFF=0x3C02;SIZE=131;PAGE=0x70;LN=0x89
RU_INV={b:ch for ch,b in kc.RU_CHAR_TO_BYTE.items() if ch not in '-—'}
RU_INV.update({0xB2:'「',0xB4:'-',0xB6:'!',0xB7:'?',0xBB:'.',0xFF:' '});RU_INV.update({0xF2+i:str(i) for i in range(10)})
def dec(raw):return ''.join(RU_INV.get(b,f'{{{b:02X}}}') for b in raw)
def main():
    ap=argparse.ArgumentParser(description='Extract/insert fixed 131-byte ending staff roll')
    sub=ap.add_subparsers(dest='cmd',required=True)
    e=sub.add_parser('extract');e.add_argument('rom',type=Path);e.add_argument('-o','--output',type=Path,default=Path('credits.txt'))
    i=sub.add_parser('insert');i.add_argument('rom',type=Path);i.add_argument('text',type=Path);i.add_argument('-o','--output',type=Path,default=Path('credits_patched.nes'))
    a=ap.parse_args();rom=bytearray(a.rom.read_bytes())
    if a.cmd=='extract':
        raw=bytes(rom[OFF:OFF+SIZE]);pages=raw.split(bytes([PAGE]));lines=[]
        for n,p in enumerate(pages,1):
            lines.append(f'### PAGE {n}')
            lines += [dec(x) for x in p.split(bytes([LN]))]
            lines.append('')
        a.output.write_text('\n'.join(lines),encoding='utf8');print(a.output);return
    pages=[];cur=None
    for line in a.text.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('### PAGE '):
            if cur is not None:pages.append(cur)
            cur=[]
        elif cur is not None and line!='':cur.append(line)
    if cur is not None:pages.append(cur)
    if len(pages)!=7:raise SystemExit(f'expected 7 pages, got {len(pages)}')
    raw=bytearray()
    for pi,page in enumerate(pages):
        for li,s in enumerate(page):
            raw+=kc.encode(s)
            if li!=len(page)-1:raw.append(LN)
        if pi!=len(pages)-1:raw.append(PAGE)
    if len(raw)>SIZE:raise SystemExit(f'credits use {len(raw)} bytes > fixed {SIZE}')
    # Keep exact 131-byte parser budget. Pad remaining bytes with spaces before final terminator area.
    raw += bytes([0xFF])*(SIZE-len(raw))
    rom[OFF:OFF+SIZE]=raw
    if rom[OFF+SIZE]!=0:raise SystemExit('expected $00 terminator after credit block')
    a.output.write_bytes(rom);print(f'Wrote {a.output}; {len(raw)}/{SIZE} bytes')
if __name__=='__main__':main()
