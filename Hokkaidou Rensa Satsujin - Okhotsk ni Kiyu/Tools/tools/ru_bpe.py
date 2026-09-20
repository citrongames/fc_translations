#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import csv
from okhotsk_common import encode_ru
from translation_codec import RAW_OLD_RE, MARKER_RE, _marker_bytes
from ru_dictionary import PRESERVE_TOKENS, DICT_TOKENS, is_dict_token

@dataclass(frozen=True)
class BPERule:
    token: int
    expansion: bytes
    kind: str = ''
    occurrences: int = 0
    corpus_saving: int = 0


def _parse_token(s: str) -> int:
    s=s.strip().upper()
    if s.startswith('0X'): s=s[2:]
    if s.startswith('$'): s=s[1:]
    v=int(s,16)
    if v not in DICT_TOKENS:
        raise ValueError(f'BPE token must be 60..CF or D0..EF, got {v:02X}')
    if v in PRESERVE_TOKENS:
        raise ValueError(f'token {v:02X} is a preserved original macro')
    return v


def load_bpe_rules(path: str|Path|None) -> list[BPERule]:
    if not path: return []
    p=Path(path)
    if not p.exists(): return []
    lines=[x for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip() and not x.lstrip().startswith('#')]
    if not lines: return []
    rd=csv.DictReader(lines,delimiter='\t')
    if not rd.fieldnames or 'TOKEN' not in rd.fieldnames or 'EXPANSION_HEX' not in rd.fieldnames:
        raise ValueError(f'{p}: expected TOKEN and EXPANSION_HEX columns')
    out=[]; seen=set()
    for row in rd:
        ts=(row.get('TOKEN') or '').strip()
        hs=(row.get('EXPANSION_HEX') or '').strip()
        if not ts or not hs: continue
        tok=_parse_token(ts)
        if tok in seen: raise ValueError(f'{p}: duplicate token {tok:02X}')
        try: exp=bytes.fromhex(hs)
        except ValueError as e: raise ValueError(f'{p}: bad EXPANSION_HEX for {tok:02X}: {e}')
        if not exp or 0xFF in exp:
            raise ValueError(f'{p}: token {tok:02X} expansion must be nonempty and cannot contain FF')
        out.append(BPERule(tok,exp,(row.get('KIND') or ''),int(row.get('OCCURRENCES') or 0),int(row.get('CORPUS_SAVING') or 0)))
        seen.add(tok)
    # TSV order is semantic: later rules may reference earlier rules.
    available=set(PRESERVE_TOKENS)
    for r in out:
        for b in r.expansion:
            if is_dict_token(b) and b not in available:
                raise ValueError(f'{p}: token {r.token:02X} references future/unassigned token {b:02X}')
        available.add(r.token)
    return out


def _replace_nonoverlap(data: bytes, pattern: bytes, token: int) -> tuple[bytes,int]:
    if not pattern: return data,0
    out=bytearray(); i=0; n=0; L=len(pattern)
    while i < len(data):
        if i+L <= len(data) and data[i:i+L] == pattern:
            out.append(token); i += L; n += 1
        else:
            out.append(data[i]); i += 1
    return bytes(out),n


def compress_visible_bytes(data: bytes, rules: list[BPERule]) -> bytes:
    out=bytes(data)
    for r in rules:
        out,_=_replace_nonoverlap(out,r.expansion,r.token)
    return out


def expand_bpe_bytes(data: bytes, rules: list[BPERule], *, max_depth: int=16) -> bytes:
    by={r.token:r.expansion for r in rules}
    memo={}
    def exb(b:int, stack:tuple[int,...]):
        if b not in by: return bytes([b])
        if b in stack or len(stack)>=max_depth: raise ValueError('BPE recursion/depth error')
        if b in memo: return memo[b]
        out=bytearray()
        for x in by[b]: out.extend(exb(x,stack+(b,)))
        memo[b]=bytes(out); return memo[b]
    out=bytearray()
    for b in data: out.extend(exb(b,()))
    return bytes(out)


def rule_depths(rules: list[BPERule]) -> dict[int,int]:
    depth={t:0 for t in PRESERVE_TOKENS}
    out={}
    for r in rules:
        d=1
        for b in r.expansion:
            if b in out: d=max(d,1+out[b])
            elif b in PRESERVE_TOKENS: d=max(d,1)
        out[r.token]=d
    return out


def encode_ru_markup_bpe(text: str, rules: list[BPERule]) -> bytes:
    """Encode RU markup while applying BPE only to visible Russian byte runs.

    F-command arguments are never dictionary-compressed, so a token can never land
    where the engine expects a raw control argument. Original token 60 and 62 macros
    are then used for their exact control sequences.
    """
    out=bytearray(); i=0
    while i < len(text):
        if text[i]=='\n': out.append(0xF8); i+=1; continue
        m=RAW_OLD_RE.match(text,i)
        if m: out.append(int(m.group(1),16)); i=m.end(); continue
        m=MARKER_RE.match(text,i)
        if m: out.extend(_marker_bytes(m.group(1))); i=m.end(); continue
        j=i
        while j<len(text) and text[j]!='\n' and not RAW_OLD_RE.match(text,j) and not MARKER_RE.match(text,j):
            j+=1
        raw=encode_ru(text[i:j])
        out.extend(compress_visible_bytes(raw,rules)); i=j
    # These two original dictionary entries are control macros and remain intact.
    b=bytes(out)
    b=b.replace(b'\xF8\xF1\x0A\xFE\xF9', b'\x62')
    b=b.replace(b'\xF8\xF1\x02', b'\x60')
    return b
