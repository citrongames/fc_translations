#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the FINAL built Murder Club Russian ROM."""
from pathlib import Path
import argparse, hashlib, csv, re, unicodedata

EXPECTED_FINAL_SHA1="fb47326f07ef46194a9ffca6a34ca8db4989954f"
BANK=0x2000
EXPECTED_BASE=bytes.fromhex("10 00 80 12 00 80 14 00 80 16 00 80")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("rom",type=Path)
    a=ap.parse_args()
    d=a.rom.read_bytes()
    errs=[]

    if d[:4]!=b"NES\x1a": errs.append("not iNES")
    if len(d)>=16:
        if d[4]!=16: errs.append(f"PRG units={d[4]}, expected 16")
        if d[5]!=16: errs.append(f"CHR units={d[5]}, expected 16")

    prg=d[16:16+0x40000]
    if len(prg)!=0x40000:
        errs.append(f"PRG size={len(prg)}")
    else:
        if prg[0x1C259:0x1C265]!=EXPECTED_BASE:
            errs.append("relocated text base table differs")
        if prg[30*BANK+0x259:30*BANK+0x265]!=EXPECTED_BASE:
            errs.append("fixed-bank copy base table differs")
        if prg[14*BANK:15*BANK]!=prg[30*BANK:31*BANK]:
            errs.append("bank14 != runtime fixed bank30")
        if prg[15*BANK:16*BANK]!=prg[31*BANK:32*BANK]:
            errs.append("bank15 != runtime fixed bank31")

        # Hardcoded Japanese てん removed from score/stat display.
        if prg[0x2563]!=0x00 or prg[0x2569]!=0x00:
            errs.append("hardcoded てん suffix patch missing")

        # Real fixed inline epilogue must no longer begin with original Japanese.
        # Translation begins with Cyrillic У = $94 in current RU table.
        if prg[0x2B98]!=0x94:
            errs.append("final inline epilogue patch missing")

    sha=hashlib.sha1(d).hexdigest()
    print("sha1",sha)
    print("expected",EXPECTED_FINAL_SHA1)
    if sha!=EXPECTED_FINAL_SHA1:
        errs.append("SHA1 differs from tested FINAL reference build")

    print("errors",len(errs))
    for e in errs:
        print(" -",e)
    raise SystemExit(1 if errs else 0)

if __name__=="__main__":
    main()
