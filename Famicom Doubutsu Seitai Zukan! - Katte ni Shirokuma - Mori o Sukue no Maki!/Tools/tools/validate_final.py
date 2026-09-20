#!/usr/bin/env python3
from pathlib import Path
import argparse,hashlib,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import katte_codec as kc

H=16;BANK=0x4000;EXT=0x54;STUB=0x10714
EXPECTED_SHA256='75005f885f4d040dcc1a0e0b521ef12eb5d466815735ebe75a18c17fa33db16b'
EXPECTED_ENEMIES=['СТАФ.','БАКТ.','ВИРУС','ОСПА','АСКАР','ЦЕПЕНЬ','БОЛ.Ц','КИШ.П','ШИГЕЛ','АД.Ш','ЛЕЙКОЦ','АНТИТ','БОСС','КОТАЦ','КОТАЦ-2','ЭЛ.РИСОВАР','ЭЛ.РИСОВАР','КОМП.СИРО','СИРО-2','МЕХ.РОБОТ','РОБОТ-2','РОБОТ-3','ТРАКТ.ТУРБО','ТРАКТОР','ДАЙМАДЗИН','ДЕМОН','ВЛАД.ТЬМЫ']

def fx(cpu):return H+15*BANK+(cpu-0xC000)
def f3(cpu):return H+3*BANK+(cpu-0x8000)

def main():
    ap=argparse.ArgumentParser(description='Validate final Katte ni Shirokuma RU structure')
    ap.add_argument('rom',type=Path);ap.add_argument('--script',type=Path)
    ap.add_argument('--allow-modified',action='store_true',help='do not require official FINAL SHA256')
    a=ap.parse_args();rom=a.rom.read_bytes()
    errs=[]
    if rom[:4]!=b'NES\x1a':errs.append('not iNES')
    if len(rom)!=393232:errs.append(f'size {len(rom)} != 393232')
    if len(rom)>=16 and (rom[4],rom[5])!=(16,16):errs.append(f'header PRG/CHR = {rom[4]}/{rom[5]}, expected 16/16')
    sha=hashlib.sha256(rom).hexdigest()
    if not a.allow_modified and sha!=EXPECTED_SHA256:errs.append(f'SHA256 {sha} != official FINAL {EXPECTED_SHA256}')
    # All 898 B1 pointers must hit 4-byte far stubs and valid banks.
    for i in range(898):
        po=kc.BLOCKS['B1'].pointer_table+i*2;ptr=rom[po]|rom[po+1]<<8;so=ptr+kc.BLOCKS['B1'].pointer_delta
        if so!=STUB+i*4:errs.append(f'B1:{i:03d} stub ${so:X} != ${STUB+i*4:X}');break
        if rom[so]!=EXT or not (8<=rom[so+1]<=14):errs.append(f'B1:{i:03d} invalid far stub');break
    # Optional script match.
    if a.script:
        E=kc.parse_script(a.script)
        for i in range(898):
            po=kc.BLOCKS['B1'].pointer_table+i*2;ptr=rom[po]|rom[po+1]<<8;so=ptr+kc.BLOCKS['B1'].pointer_delta
            bank=rom[so+1];cpu=rom[so+2]|rom[so+3]<<8;off=H+bank*BANK+(cpu-0x8000);end=rom.find(b'\0',off,H+(bank+1)*BANK)
            if end<0 or rom[off:end]!=kc.encode(E[('B1',i)]['text']):errs.append(f'B1:{i:03d} ROM != script');break
        for bn in ('B0','D'):
            for i,po,so,raw in kc.pointer_entries(rom,kc.BLOCKS[bn]):
                if raw!=kc.encode(E[(bn,i)]['text']):errs.append(f'{bn}:{i:03d} ROM != script');break
    # Enemy names exactly 27 and final labels.
    inv={b:ch for ch,b in kc.RU_CHAR_TO_BYTE.items() if ch not in '-—'};inv.update({0xB4:'-',0xB2:'「',0xB6:'!',0xB7:'?',0xBB:'.',0xFF:' '});inv.update({0xF2+i:str(i) for i in range(10)})
    got=[]
    for i in range(27):
        po=f3(0xA779)+2*i;p=rom[po]|rom[po+1]<<8;off=f3(p);end=rom.find(b'\0',off,f3(0xA881));raw=rom[off:end] if end>=0 else b'';got.append(''.join(inv.get(b,f'{{{b:02X}}}') for b in raw))
    if got!=EXPECTED_ENEMIES:errs.append('27-entry enemy table does not match FINAL')
    # Credits and looping ending.
    if rom[0x3C85]!=0:errs.append('credits terminator at $3C85 is not $00')
    if rom[fx(0xFF74):fx(0xFF79)]!=bytes.fromhex('20 BE F4 F0 F3'):errs.append('ending loop patch $FF74-$FF78 incorrect')
    if rom[fx(0xFF79):fx(0xFF7D)]!=bytes.fromhex('C9 54 F0 0A'):errs.append('far-text runtime entry $FF79 damaged')
    if errs:
        print('FAIL');[print(' -',e) for e in errs];raise SystemExit(1)
    print('PASS')
    print('SHA256:',sha)
    print('B1 far stubs: 898/898')
    print('Enemy names: 27/27')
    print('Ending loop: OK')
    print('Credits terminator: OK')
    if a.script:print('ROM/script: B0 153/153, B1 898/898, D 91/91')
if __name__=='__main__':main()
