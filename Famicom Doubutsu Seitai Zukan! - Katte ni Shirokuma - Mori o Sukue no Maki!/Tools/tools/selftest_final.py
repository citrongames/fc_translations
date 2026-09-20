#!/usr/bin/env python3
from pathlib import Path
import hashlib,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parent
PKG=ROOT.parent
ROM=PKG/'Katte_Shirokuma_RU_FINAL_v1.0.nes'
SCRIPT=PKG/'script'/'script_ru_final.txt'

def run(*args):
    subprocess.run([sys.executable,*map(str,args)],check=True)

def same(a,b,label):
    aa=Path(a).read_bytes();bb=Path(b).read_bytes()
    if aa!=bb:
        raise SystemExit(f'FAIL {label}: {hashlib.sha256(aa).hexdigest()} != {hashlib.sha256(bb).hexdigest()}')
    print('PASS',label,hashlib.sha256(aa).hexdigest())

def main():
    run(ROOT/'validate_final.py',ROM,'--script',SCRIPT)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        ext=td/'script.txt';out=td/'text.nes'
        run(ROOT/'extract_text.py',ROM,'-o',ext,'--mode','ru')
        run(ROOT/'insert_text.py',ROM,ext,'-o',out)
        same(ROM,out,'text extract->insert')
        chrdir=td/'chr';out=td/'chr.nes'
        run(ROOT/'extract_chr.py',ROM,'--bank','2','-o',chrdir)
        run(ROOT/'insert_chr.py',ROM,chrdir/'chr_bank_02.png','--bank','2','-o',out)
        same(ROM,out,'CHR bank2 extract->insert')
        tsv=td/'enemy.tsv';out=td/'enemy.nes'
        run(ROOT/'enemy_names.py','extract',ROM,'-o',tsv)
        run(ROOT/'enemy_names.py','insert',ROM,tsv,'-o',out)
        same(ROM,out,'enemy names extract->insert')
        txt=td/'credits.txt';out=td/'credits.nes'
        run(ROOT/'credits_tool.py','extract',ROM,'-o',txt)
        run(ROOT/'credits_tool.py','insert',ROM,txt,'-o',out)
        same(ROM,out,'credits extract->insert')
    print('ALL FINAL SELF-TESTS PASS')
if __name__=='__main__':main()
