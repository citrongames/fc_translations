#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import csv

# 0x60 and 0x62 are original bytecode macros with flow-control effects and are
# deliberately preserved. In v0.8 the original D/E handlers are repurposed as
# a SECOND dictionary range, giving 32 more tokens (D0..EF).
PRESERVE_TOKENS = {0x60, 0x62}
MAIN_DICT_TOKENS = tuple(range(0x60, 0xD0))
EXTRA_DICT_TOKENS = tuple(range(0xD0, 0xF0))
DICT_TOKENS = frozenset(MAIN_DICT_TOKENS + EXTRA_DICT_TOKENS)
TOKEN_POOL = [b for b in MAIN_DICT_TOKENS if b not in PRESERVE_TOKENS] + list(EXTRA_DICT_TOKENS)

# Extra dictionary lives in bank A at text-region offset $194A / CPU $994A.
# This address is inside a contiguous original text-stream hole in the FULL-RU
# build. repack_pool.py reserves exactly the bytes occupied by this table.
EXTRA_DICT_START = 0x194A
EXTRA_DICT_CPU = 0x8000 + EXTRA_DICT_START


def is_dict_token(v: int) -> bool:
    return v in DICT_TOKENS


def _parse_token(s: str) -> int:
    s=s.strip().upper()
    if s.startswith('0X'): s=s[2:]
    if s.startswith('$'): s=s[1:]
    v=int(s,16)
    if v not in DICT_TOKENS:
        raise ValueError(f'dictionary token must be 60..CF or D0..EF, got {v:02X}')
    if v in PRESERVE_TOKENS:
        raise ValueError(f'token {v:02X} is a preserved control macro')
    return v


def load_ru_dictionary(path: str | Path | None):
    """Return (token_to_text, text_to_token) from a TSV file.

    Expected columns: TOKEN, TEXT. Lines beginning with # are ignored.
    Empty TEXT rows are allowed and are ignored by the encoder.
    """
    if not path:
        return {}, {}
    p=Path(path)
    if not p.exists():
        return {}, {}
    token_to_text={}
    with p.open('r',encoding='utf-8-sig',newline='') as f:
        rows=[line for line in f if not line.lstrip().startswith('#')]
    if not rows:
        return {}, {}
    rd=csv.DictReader(rows,delimiter='\t')
    if not rd.fieldnames or 'TOKEN' not in rd.fieldnames or 'TEXT' not in rd.fieldnames:
        raise ValueError(f'{p}: TSV must contain TOKEN and TEXT columns')
    for row in rd:
        ts=(row.get('TOKEN') or '').strip(); text=(row.get('TEXT') or '')
        if not ts: continue
        tok=_parse_token(ts)
        if tok in token_to_text:
            raise ValueError(f'{p}: duplicate token {tok:02X}')
        token_to_text[tok]=text
    text_to_token={}
    for tok,text in token_to_text.items():
        if not text: continue
        if text in text_to_token:
            raise ValueError(f'{p}: duplicate dictionary text {text!r}')
        text_to_token[text]=tok
    return token_to_text,text_to_token


def sorted_text_matches(text_to_token: dict[str,int]):
    return sorted(text_to_token.items(), key=lambda kv:(-len(kv[0]), kv[1], kv[0]))
