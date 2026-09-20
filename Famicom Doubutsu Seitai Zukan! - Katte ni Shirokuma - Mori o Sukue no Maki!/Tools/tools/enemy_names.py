#!/usr/bin/env python3
from pathlib import Path
import argparse, sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import katte_codec as kc

H=16;BANK=0x4000;TABLE=0xA779;COUNT=27;POOL_START=0xA7AF;POOL_END=0xA881
RU_INV={b:ch for ch,b in kc.RU_CHAR_TO_BYTE.items() if ch not in '-—'}
RU_INV.update({0xB2:'「',0xB4:'-',0xB6:'!',0xB7:'?',0xBB:'.',0xFF:' '});RU_INV.update({0xF2+i:str(i) for i in range(10)})

def f3(cpu):return H+3*BANK+(cpu-0x8000)
def decode(raw):return ''.join(RU_INV.get(b,f'{{{b:02X}}}') for b in raw)
def read_names(rom):
    out=[]
    for i in range(COUNT):
        po=f3(TABLE)+i*2;p=rom[po]|rom[po+1]<<8;so=f3(p);end=rom.find(b'\0',so,f3(POOL_END))
        if end<0:raise ValueError(f'entry {i}: no terminator')
        out.append(decode(rom[so:end]))
    return out

def main():
    ap=argparse.ArgumentParser(description='Extract or insert all 27 dynamic battle enemy names')
    sub=ap.add_subparsers(dest='cmd',required=True)
    e=sub.add_parser('extract');e.add_argument('rom',type=Path);e.add_argument('-o','--output',type=Path,default=Path('enemy_names.tsv'))
    i=sub.add_parser('insert');i.add_argument('rom',type=Path);i.add_argument('tsv',type=Path);i.add_argument('-o','--output',type=Path,default=Path('enemy_names_patched.nes'))
    a=ap.parse_args();rom=bytearray(a.rom.read_bytes())
    if a.cmd=='extract':
        names=read_names(rom);a.output.write_text('index\tname\n'+'\n'.join(f'{i}\t{s}' for i,s in enumerate(names))+'\n',encoding='utf8');print(a.output);return
    rows=[]
    for line in a.tsv.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lower().startswith('index\t'):continue
        idx,s=line.split('\t',1);rows.append((int(idx),s))
    if [i for i,_ in rows]!=list(range(COUNT)):raise SystemExit('TSV must contain indices 0..26 exactly once in order')
    a0=POOL_START;ptr=[]
    for idx,s in rows:
        d=kc.encode(s)+b'\0'
        if a0+len(d)>POOL_END:raise SystemExit(f'pool overflow at {idx}:{s}; need ${a0+len(d):04X}, limit ${POOL_END:04X}')
        ptr.append(a0);rom[f3(a0):f3(a0)+len(d)]=d;a0+=len(d)
    rom[f3(a0):f3(POOL_END)]=b'\0'*(POOL_END-a0)
    for idx,p in enumerate(ptr):
        po=f3(TABLE)+idx*2;rom[po:po+2]=bytes((p&255,p>>8))
    a.output.write_bytes(rom);print(f'Wrote {a.output}; pool {a0-POOL_START}/{POOL_END-POOL_START} bytes')
if __name__=='__main__':main()
