#!/usr/bin/env python3
"""Reproduce FINAL v1.0 from the known v0.23 RU base.

This source file documents the two post-v0.23 QA fixes only:
  1) all 27 dynamic battle enemy names;
  2) looping ending without overwriting the far-text runtime at $FF79.
"""
from pathlib import Path
import argparse,hashlib,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'tools'))
import katte_codec as kc
H=16;BANK=0x4000
ENEMY=['СТАФ.','БАКТ.','ВИРУС','ОСПА','АСКАР','ЦЕПЕНЬ','БОЛ.Ц','КИШ.П','ШИГЕЛ','АД.Ш','ЛЕЙКОЦ','АНТИТ','БОСС','КОТАЦ','КОТАЦ-2','ЭЛ.РИСОВАР','ЭЛ.РИСОВАР','КОМП.СИРО','СИРО-2','МЕХ.РОБОТ','РОБОТ-2','РОБОТ-3','ТРАКТ.ТУРБО','ТРАКТОР','ДАЙМАДЗИН','ДЕМОН','ВЛАД.ТЬМЫ']
def f3(cpu):return H+3*BANK+(cpu-0x8000)
def fx(cpu):return H+15*BANK+(cpu-0xC000)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('v023',type=Path);ap.add_argument('-o','--output',type=Path,default=Path('Katte_Shirokuma_RU_FINAL_v1.0.nes'));a=ap.parse_args()
    rom=bytearray(a.v023.read_bytes())
    if rom[:4]!=b'NES\x1a' or rom[4]!=16:raise SystemExit('Expected expanded v0.23-style ROM')
    # 27 enemy pointers + pool.
    table=0xA779;start=0xA7AF;end=0xA881;after=bytes(rom[f3(end):f3(end)+64]);cur=start;ptr=[]
    for s in ENEMY:
        d=kc.encode(s)+b'\0'
        if cur+len(d)>end:raise SystemExit('enemy pool overflow')
        ptr.append(cur);rom[f3(cur):f3(cur)+len(d)]=d;cur+=len(d)
    rom[f3(cur):f3(end)]=b'\0'*(end-cur)
    for i,p in enumerate(ptr):rom[f3(table)+i*2:f3(table)+i*2+2]=bytes((p&255,p>>8))
    assert bytes(rom[f3(end):f3(end)+64])==after
    # v0.23 holding loop -> original-style looping ending.
    old=bytes(rom[fx(0xFF74):fx(0xFF79)])
    if old!=bytes.fromhex('20 64 C1 F0 FB'):raise SystemExit(f'Unexpected v0.23 ending bytes: {old.hex(" ")}')
    runtime=bytes(rom[fx(0xFF79):fx(0xFFC0)])
    rom[fx(0xFF74):fx(0xFF79)]=bytes.fromhex('20 BE F4 F0 F3')
    assert bytes(rom[fx(0xFF79):fx(0xFFC0)])==runtime
    a.output.write_bytes(rom)
    print('Wrote',a.output);print('SHA256',hashlib.sha256(rom).hexdigest())
if __name__=='__main__':main()
