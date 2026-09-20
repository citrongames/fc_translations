#!/usr/bin/env python3
from __future__ import annotations
import re
from okhotsk_common import RU_UPPER_ENC, RU_LOWER_BASE_ENC, RU_LOWER_DIRECT_ENC, RU_PUNCT_ENC, RU_DIGIT_ENC

RAW_OLD_RE = re.compile(r'<\$([0-9A-Fa-f]{2})>')
MARKER_RE = re.compile(r'\[([^\[\]\n]+)\]')


def _hex8(s: str) -> int:
    s = s.strip()
    if s.startswith('$'):
        s = s[1:]
    v = int(s, 16)
    if not 0 <= v <= 0xFF:
        raise ValueError(f'byte out of range: {s}')
    return v


def _marker_bytes(body: str) -> bytes:
    body = body.strip()
    up = body.upper()
    if up.startswith('RAW:$') and len(up) == 7:
        return bytes([_hex8(up.split(':',1)[1])])
    if up.startswith('GLYPH:$'):
        v=_hex8(body.split(':',1)[1])
        # Original engine rendered D0..D9 through its legacy numeric-glyph
        # handler (D0+n -> tile 74+n).  v0.8 repurposes D0..EF as the
        # secondary RU dictionary, so emitting raw Dn here would expand a
        # dictionary phrase (e.g. D1 -> "Продавщица") instead of a digit.
        # The RU font mirrors the same 0..9 glyphs at direct codes 22..2B.
        if 0xD0 <= v <= 0xD9:
            return bytes([0x22 + (v-0xD0)])
        return bytes([v])
    if up.startswith('DICT:$'):
        return bytes([_hex8(body.split(':',1)[1])])
    if up.startswith('E:'):
        n=int(body.split(':',1)[1],0)
        if not 0 <= n <= 15: raise ValueError('E run length must be 0..15')
        return bytes([0xE0|n])
    if up.startswith('F0:'):
        vals = [_hex8(x) for x in body.split(':',1)[1].split(',') if x.strip()]
        if not vals or not (vals[-1] & 0x80):
            raise ValueError('F0 marker must end with an argument whose bit7 is set')
        return bytes([0xF0, *vals])
    if up.startswith('F1:'):
        return bytes([0xF1, _hex8(body.split(':',1)[1])])
    if up.startswith('F2:'):
        s = body.split(':',1)[1].strip()
        if s.startswith('$'): s = s[1:]
        v = int(s,16)
        if not 0 <= v <= 0xFFFF: raise ValueError('F2 target out of range')
        return bytes([0xF2, v & 0xFF, v >> 8])
    if up in ('F3','F4','F7','F9','FA','FE'):
        return bytes([0xF0 | int(up[1:],16)])
    if up.startswith('F5:'):
        vals=[_hex8(x) for x in body.split(':',1)[1].split(',')]
        if len(vals)!=2: raise ValueError('F5 requires exactly 2 arguments')
        return bytes([0xF5,*vals])
    if up.startswith('F6:'):
        return bytes([0xF6,_hex8(body.split(':',1)[1])])
    if up.startswith('FB:'):
        return bytes([0xFB,_hex8(body.split(':',1)[1])])
    if up.startswith('FC:'):
        return bytes([0xFC,_hex8(body.split(':',1)[1])])
    if up.startswith('FD:'):
        return bytes([0xFD,_hex8(body.split(':',1)[1])])
    raise ValueError(f'unsupported control marker [{body}]')


def encode_ru_markup(text: str, text_to_token: dict[str,int] | None = None) -> bytes:
    """Encode Russian work-file text plus symbolic F-control markers.

    Newlines become F8. The final FF is NOT appended here.
    If text_to_token is supplied, visible Russian dictionary strings are matched
    greedily (longest first) and emitted as one-byte 60..CF tokens.
    """
    matches=[]
    if text_to_token:
        matches=sorted(text_to_token.items(), key=lambda kv:(-len(kv[0]),kv[1],kv[0]))
    out=bytearray(); i=0
    while i < len(text):
        if text[i] == '\n':
            out.append(0xF8); i += 1; continue
        m = RAW_OLD_RE.match(text,i)
        if m:
            out.append(int(m.group(1),16)); i=m.end(); continue
        m = MARKER_RE.match(text,i)
        if m:
            out.extend(_marker_bytes(m.group(1))); i=m.end(); continue
        hit=False
        for phrase,tok in matches:
            if phrase and text.startswith(phrase,i):
                out.append(tok); i += len(phrase); hit=True; break
        if hit: continue
        ch=text[i]
        if ch in RU_UPPER_ENC:
            out.append(RU_UPPER_ENC[ch]); i += 1; continue
        if ch in RU_LOWER_DIRECT_ENC:
            out.append(RU_LOWER_DIRECT_ENC[ch]); i += 1; continue
        if ch in RU_PUNCT_ENC:
            out.append(RU_PUNCT_ENC[ch]); i += 1; continue
        if ch in RU_DIGIT_ENC:
            out.append(RU_DIGIT_ENC[ch]); i += 1; continue
        raise ValueError(f'unsupported Russian/markup character at position {i}: {text[i:i+24]!r}')
    return bytes(out)
