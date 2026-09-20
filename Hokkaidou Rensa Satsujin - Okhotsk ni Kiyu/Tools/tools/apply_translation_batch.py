#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

ID_RE=re.compile(r'^@@\s+ID=(\d+)\b')

def main():
    ap=argparse.ArgumentParser(description='Apply an ID->TR JSON translation batch to script_work.txt.')
    ap.add_argument('workfile'); ap.add_argument('batch_json'); ap.add_argument('-o','--out',required=True)
    a=ap.parse_args()
    trans={int(k):v for k,v in json.loads(Path(a.batch_json).read_text(encoding='utf-8-sig')).items()}
    lines=Path(a.workfile).read_text(encoding='utf-8-sig').splitlines()
    out=[]; i=0; cur=None; changed=[]
    while i<len(lines):
        m=ID_RE.match(lines[i])
        if m: cur=int(m.group(1))
        if lines[i]=='TR_BEGIN' and cur in trans:
            out.append(lines[i]); out.extend(trans[cur].split('\n')); changed.append(cur); i+=1
            while i<len(lines) and lines[i]!='TR_END': i+=1
            if i>=len(lines): raise SystemExit(f'Unclosed TR block near ID {cur}')
            out.append('TR_END'); i+=1; continue
        out.append(lines[i]); i+=1
    missing=sorted(set(trans)-set(changed))
    if missing: raise SystemExit(f'IDs not found in workfile: {missing}')
    Path(a.out).write_text('\n'.join(out)+'\n',encoding='utf-8-sig')
    print(f'Applied {len(changed)} translations -> {a.out}')

if __name__=='__main__': main()
