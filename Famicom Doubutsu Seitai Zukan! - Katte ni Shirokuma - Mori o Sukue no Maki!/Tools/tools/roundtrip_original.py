#!/usr/bin/env python3
from pathlib import Path
import subprocess,tempfile,hashlib,sys
ROOT=Path(__file__).resolve().parent
if len(sys.argv)!=2:
    raise SystemExit('Usage: python roundtrip_original.py original.nes')
rom=Path(sys.argv[1])
if not rom.exists():raise SystemExit(f'Not found: {rom}')
with tempfile.TemporaryDirectory() as td:
    td=Path(td);script=td/'script.txt';out=td/'out.nes'
    subprocess.run([sys.executable,str(ROOT/'extract_text.py'),str(rom),'-o',str(script),'--mode','jp'],check=True)
    subprocess.run([sys.executable,str(ROOT/'repack_original.py'),str(rom),str(script),'-o',str(out)],check=True)
    a=rom.read_bytes();b=out.read_bytes()
    print('Original SHA256:',hashlib.sha256(a).hexdigest())
    print('Roundtrip SHA256:',hashlib.sha256(b).hexdigest())
    if a!=b:raise SystemExit('FAIL: ROM differs after extract -> repack')
    print('PASS: byte-identical original-ROM round-trip')
