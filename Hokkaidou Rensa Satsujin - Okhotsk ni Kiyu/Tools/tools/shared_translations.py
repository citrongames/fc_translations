#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path


def _ptr(v) -> int:
    if isinstance(v, int):
        n=v
    else:
        s=str(v).strip()
        if s.startswith('$'): s=s[1:]
        if s.lower().startswith('0x'): s=s[2:]
        n=int(s,16)
    if not 0 <= n <= 0xFFFF:
        raise ValueError(f'shared-stream pointer out of range: {v!r}')
    return n


def load_shared_translations(path: str|Path|None) -> dict[int,str]:
    """Load {"1535":"RU text", ...} or [{"ptr":"1535","tr":"..."}, ...]."""
    if not path:
        return {}
    p=Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    obj=json.loads(p.read_text(encoding='utf-8-sig'))
    out={}
    if isinstance(obj,dict):
        items=obj.items()
    elif isinstance(obj,list):
        items=[]
        for row in obj:
            if not isinstance(row,dict) or 'ptr' not in row or 'tr' not in row:
                raise ValueError('shared translation list rows need ptr and tr')
            items.append((row['ptr'],row['tr']))
    else:
        raise ValueError('shared translations JSON must be an object or list')
    for k,v in items:
        n=_ptr(k)
        if not isinstance(v,str):
            raise ValueError(f'shared translation ${n:04X} is not a string')
        if v=='':
            continue
        if n in out and out[n]!=v:
            raise ValueError(f'duplicate shared translation ${n:04X}')
        out[n]=v
    return out
