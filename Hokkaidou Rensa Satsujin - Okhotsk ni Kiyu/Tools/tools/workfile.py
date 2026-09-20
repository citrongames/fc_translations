#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import re

HEADER_RE = re.compile(r'^@@\s+(.*)$')
KV_RE = re.compile(r'([A-Z_]+)=([^\s]+)')


def parse_header(line: str) -> dict:
    m=HEADER_RE.match(line)
    if not m: raise ValueError(f'bad block header: {line!r}')
    d={k:v for k,v in KV_RE.findall(m.group(1))}
    if 'ID' in d: d['id']=int(d['ID'])
    if 'PTR' in d: d['ptr']=int(d['PTR'].replace('$',''),16)
    if 'LEN' in d: d['len']=int(d['LEN'])
    if 'IDS' in d:
        d['ids']=[int(x) for x in d['IDS'].split(',') if x]
    elif 'id' in d:
        d['ids']=[d['id']]
    else: d['ids']=[]
    return d


def parse_work(path):
    lines=Path(path).read_text(encoding='utf-8-sig').splitlines()
    out=[]; i=0
    while i<len(lines):
        if not lines[i].startswith('@@ '): i+=1; continue
        rec=parse_header(lines[i]); rec['tr']=''; rec['jp']=''; rec['jp_expanded']=''
        i+=1
        while i<len(lines) and not lines[i].startswith('@@ '):
            tag=lines[i]
            if tag in ('JP_BEGIN','JP_EXPANDED_BEGIN','TR_BEGIN'):
                endtag={'JP_BEGIN':'JP_END','JP_EXPANDED_BEGIN':'JP_EXPANDED_END','TR_BEGIN':'TR_END'}[tag]
                key={'JP_BEGIN':'jp','JP_EXPANDED_BEGIN':'jp_expanded','TR_BEGIN':'tr'}[tag]
                i+=1; buf=[]
                while i<len(lines) and lines[i]!=endtag:
                    buf.append(lines[i]); i+=1
                rec[key]='\n'.join(buf)
            i+=1
        out.append(rec)
    return out
