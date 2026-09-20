#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse, hashlib, sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import katte_codec as kc

H=16
BANK=0x4000
B0_POOLS=[(0x0C2D8,0x0C59D),(0x0FF8D,0x0FFCC),(0x0FFF0,0x1000A)]
D_POOL=(0x14156,0x16A8C)
B1_STUB_START=0x10714
EXT=0x54
EXT_BANKS=list(range(8,15))
ACTION_B0={24,39,57,59,62,72,75,76,104,106,135,136,137,138,139,140,141,142,143,144,145}


def put16(buf,off,v):
    buf[off]=v&255;buf[off+1]=(v>>8)&255


def suffix_roots(items):
    unique={}
    for k,p in items.items(): unique.setdefault(p,[]).append(k)
    roots=[]
    for p in unique:
        if not any(len(q)>len(p) and q.endswith(p) for q in unique): roots.append(p)
    mapping={}
    for p,keys in unique.items():
        cands=[r for r in roots if r.endswith(p)]
        r=min(cands,key=lambda x:(len(x),x)); delta=len(r)-len(p)
        for k in keys:mapping[k]=(r,delta)
    return roots,mapping


def binpack(roots,pools):
    slots=[[s,e] for s,e in pools]; pos={}
    for payload in sorted(roots,key=lambda x:(-len(x),x)):
        for sl in slots:
            if sl[1]-sl[0] >= len(payload):
                pos[payload]=sl[0];sl[0]+=len(payload);break
        else:
            raise RuntimeError(f'packing failed for {len(payload)} bytes; free={[(hex(s),e-s) for s,e in slots]}')
    return pos


def text_cells(s:str):
    # Count visible characters in a script fragment, ignoring {tokens}.
    n=0;i=0
    while i<len(s):
        if s[i]=='{':
            j=s.find('}',i+1)
            if j<0: raise ValueError('unclosed token')
            i=j+1
        else:
            n+=1;i+=1
    return n


def validate_layout(E):
    # Final B1 has a 16x3 dialogue window. Expand line/page tokens only; service
    # controls are invisible. Dynamic names are not included in this simple count,
    # so this check is intentionally conservative for ordinary edited prose.
    problems=[]
    for i in range(898):
        s=E[('B1',i)]['text']
        pages=s.split('{NEXT}')
        for pi,p in enumerate(pages):
            lines=p.split('{LN}')
            if len(lines)>3: problems.append(f'B1:{i:03d} page {pi}: {len(lines)} rows > 3')
            for li,line in enumerate(lines):
                if text_cells(line)>16:
                    problems.append(f'B1:{i:03d} page {pi} line {li}: {text_cells(line)} cells > 16')
    return problems


def main():
    ap=argparse.ArgumentParser(description='Repack edited text into Katte ni Shirokuma FINAL expanded RU ROM')
    ap.add_argument('rom',type=Path,help='FINAL/expanded RU ROM (16 PRG banks)')
    ap.add_argument('script',type=Path,help='Editable 1142-entry script')
    ap.add_argument('-o','--output',type=Path,default=Path('Katte_Shirokuma_RU_EDITED.nes'))
    ap.add_argument('--skip-layout-check',action='store_true')
    a=ap.parse_args()

    base=a.rom.read_bytes()
    if len(base)<16 or base[:4]!=b'NES\x1a': raise SystemExit('Not an iNES ROM')
    if base[4] != 16: raise SystemExit(f'Expected expanded 16-PRG-bank RU ROM, got {base[4]} banks')
    if base[5] != 16: raise SystemExit(f'Expected 16 CHR banks, got {base[5]}')
    rom=bytearray(base)
    E=kc.parse_script(a.script)
    expected={('B0',i) for i in range(153)}|{('B1',i) for i in range(898)}|{('D',i) for i in range(91)}
    if set(E)!=expected:
        missing=sorted(expected-set(E));extra=sorted(set(E)-expected)
        raise SystemExit(f'Script key mismatch; missing={missing[:5]} extra={extra[:5]}')

    enc={}
    for k,e in E.items():
        try: enc[k]=kc.encode(e['text'])
        except Exception as ex: raise SystemExit(f'{k}: {ex}')

    # Reserved far-text opcode and obsolete BA chain byte may not occur literally in B1.
    bad54=[k for k,p in enc.items() if k[0]=='B1' and 0x54 in p]
    badba=[k for k,p in enc.items() if k[0]=='B1' and 0xBA in p]
    if bad54: raise SystemExit(f'B1 contains reserved $54: {bad54[:10]}')
    if badba: raise SystemExit(f'B1 contains reserved/obsolete $BA: {badba[:10]}')

    for i in range(153):
        if text_cells(E[('B0',i)]['text'])>6:
            raise SystemExit(f'B0:{i:03d} exceeds compact 6-cell label limit: {E[("B0",i)]["text"]!r}')
    if not a.skip_layout_check:
        probs=validate_layout(E)
        if probs:
            print('\n'.join(probs[:30]))
            raise SystemExit(f'Layout check failed: {len(probs)} problem(s); use --skip-layout-check only when you verified layout manually')

    # B0: suffix-pack into the known local bank-3 pools.
    payload={i:enc[('B0',i)]+b'\0' for i in range(153)}
    roots,mapping=suffix_roots(payload)
    pos=binpack(roots,B0_POOLS)
    for s,e in B0_POOLS: rom[s:e]=b'\0'*(e-s)
    for p,so in pos.items(): rom[so:so+len(p)]=p
    for i in range(153):
        root,delta=mapping[i];so=pos[root]+delta
        put16(rom,kc.BLOCKS['B0'].pointer_table+i*2,so-kc.BLOCKS['B0'].pointer_delta)

    # Dictionary: suffix-pack into retired original B1 storage.
    payload={i:enc[('D',i)]+b'\0' for i in range(91)}
    roots,mapping=suffix_roots(payload)
    pos=binpack(roots,[D_POOL])
    # Do not clear the whole retired B1 area: FINAL keeps unrelated/unused legacy
    # bytes there. Only overwrite the packed dictionary roots, matching the canonical build.
    for p,so in pos.items(): rom[so:so+len(p)]=p
    for i in range(91):
        root,delta=mapping[i];so=pos[root]+delta
        put16(rom,kc.BLOCKS['D'].pointer_table+i*2,so-kc.BLOCKS['D'].pointer_delta)

    # B1: rebuild external banks 8..14; exact duplicates share one payload.
    for bank in EXT_BANKS:
        rom[H+bank*BANK:H+(bank+1)*BANK]=b'\xff'*BANK
    loc={}; seen={}; bi=0;cur=0
    for i in range(898):
        p=enc[('B1',i)]+b'\0'
        if p in seen:
            loc[i]=seen[p];continue
        if len(p)>BANK: raise SystemExit(f'B1:{i:03d} exceeds 16K')
        if cur+len(p)>BANK: bi+=1;cur=0
        if bi>=len(EXT_BANKS): raise SystemExit('B1 text exceeds expanded banks 8..14')
        bank=EXT_BANKS[bi];cpu=0x8000+cur;off=H+bank*BANK+cur
        rom[off:off+len(p)]=p;seen[p]=(bank,cpu);loc[i]=(bank,cpu);cur+=len(p)
    for i in range(898):
        bank,cpu=loc[i];stub=B1_STUB_START+i*4
        put16(rom,kc.BLOCKS['B1'].pointer_table+i*2,stub-kc.BLOCKS['B1'].pointer_delta)
        rom[stub:stub+4]=bytes([EXT,bank,cpu&255,cpu>>8])

    a.output.write_bytes(rom)
    print(f'Wrote {a.output}')
    print(f'B1 unique strings: {len(seen)}; external banks used: {bi+1}')
    print('SHA256:',hashlib.sha256(rom).hexdigest())

if __name__=='__main__':main()
