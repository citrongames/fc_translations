#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import struct, hashlib, re

PRG_BANK_SIZE = 0x4000
TEXT_BANK_FIRST = 0x0A
TEXT_BANK_COUNT = 4
TEXT_REGION_SIZE = TEXT_BANK_COUNT * PRG_BANK_SIZE
EXPECTED_PRG_BANKS = 16

# Direct text codes confirmed from the runtime font + first scene.
DIRECT = {0x00: ' '}
for i, ch in enumerate('かきくけこさしすせそたちつてとはひふへほ', 0x01):
    DIRECT[i] = ch
for i, ch in enumerate('あいうえおなにぬねのまみむめも', 0x15):
    DIRECT[i] = ch
DIRECT.update({
    0x24:'や',0x25:'ゆ',0x26:'よ',0x27:'ら',0x28:'り',0x29:'る',0x2A:'れ',0x2B:'ろ',
    0x2C:'わ',0x2D:'を',0x2E:'ん',0x2F:'っ',0x30:'ゃ',0x31:'ゅ',0x32:'ょ',0x33:'ー',
    # 34 and some 35..3E are UI/punctuation symbols not all identified yet.
    0x35:'！',0x36:'？',0x39:'・',0x3A:'「',0x3C:'＊',0x3D:'…',0x3E:'、',0x3F:'。',
})
for i, ch in enumerate('がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ', 0x41):
    DIRECT[i] = ch

REVERSE_DIRECT = {v:k for k,v in DIRECT.items() if len(v)==1}


def read_ines(path: str | Path):
    raw = Path(path).read_bytes()
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    prg_banks = raw[4]
    chr_banks = raw[5]
    flags6, flags7 = raw[6], raw[7]
    mapper = (flags6 >> 4) | (flags7 & 0xF0)
    trainer = bool(flags6 & 0x04)
    off = 16 + (512 if trainer else 0)
    prg_size = prg_banks * PRG_BANK_SIZE
    if len(raw) < off + prg_size:
        raise ValueError('ROM is truncated')
    return {
        'raw': raw, 'prg': raw[off:off+prg_size], 'prg_offset': off,
        'prg_banks': prg_banks, 'chr_banks': chr_banks, 'mapper': mapper,
        'trainer': trainer, 'sha256': hashlib.sha256(raw).hexdigest(),
    }


def text_region(info):
    prg = info['prg']
    a = TEXT_BANK_FIRST * PRG_BANK_SIZE
    b = a + TEXT_REGION_SIZE
    if len(prg) < b:
        raise ValueError('ROM does not contain banks A-D')
    return prg[a:b]


def read_pointer_table(region: bytes):
    first = struct.unpack_from('<H', region, 0)[0]
    if first % 2:
        raise ValueError(f'First pointer 0x{first:04X} is not aligned')
    count = first // 2
    ptrs = [struct.unpack_from('<H', region, i*2)[0] for i in range(count)]
    return ptrs


def dictionary(region: bytes, ptrs):
    if len(ptrs) < 2:
        raise ValueError('Pointer table too small')
    start, end = ptrs[0], ptrs[1]
    if not (0 <= start < end <= len(region)):
        raise ValueError('Dictionary bounds are invalid')
    parts = region[start:end].split(b'\xFF')
    if parts and parts[-1] == b'':
        parts = parts[:-1]
    return parts


def hira_to_kata(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        out.append(chr(o + 0x60) if 0x3041 <= o <= 0x3096 else ch)
    return ''.join(out)


def kata_to_hira(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        out.append(chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else ch)
    return ''.join(out)


def decode_bytes(bs: bytes, dict_entries, *, stop_at_ff=True, depth=0):
    if depth > 8:
        return '<DICT-DEPTH>', {'unknown': 1, 'controls': 0}
    out, unknown, controls = [], 0, 0
    i = 0
    while i < len(bs):
        b = bs[i]; i += 1
        if b == 0xFF and stop_at_ff:
            break
        if b in DIRECT:
            out.append(DIRECT[b]); continue
        if 0x60 <= b <= 0xCF:
            idx = b - 0x60
            if idx < len(dict_entries):
                s, st = decode_bytes(dict_entries[idx], dict_entries, stop_at_ff=False, depth=depth+1)
                out.append(s); unknown += st['unknown']; controls += st['controls']
            else:
                out.append(f'<DICT:{b:02X}>'); unknown += 1
            continue
        # Katakana/lower-font run. Static engine analysis confirms E1..EF:
        # low nibble = number of following direct character codes to render from the +0x40 tile set.
        if 0xE1 <= b <= 0xEF:
            n = b & 0x0F
            if i + n <= len(bs) and all(x in DIRECT for x in bs[i:i+n]):
                s = ''.join(DIRECT[x] for x in bs[i:i+n]); i += n
                out.append(hira_to_kata(s)); continue
            out.append(f'<${b:02X}>'); unknown += 1; controls += 1
            continue
        if b == 0xF8:
            out.append('\n'); controls += 1; continue
        # Keep every unknown/control byte visible so extraction is loss-aware.
        out.append(f'<${b:02X}>'); unknown += 1
        if b >= 0xD0: controls += 1
    return ''.join(out), {'unknown': unknown, 'controls': controls}


def get_record(region: bytes, ptr: int, max_len=0x1000):
    if ptr == 0xFFFF or ptr >= len(region):
        return b''
    end = region.find(b'\xFF', ptr, min(len(region), ptr + max_len))
    if end < 0:
        return region[ptr:min(len(region), ptr+max_len)]
    return region[ptr:end+1]


def classify_record(raw: bytes, dict_entries):
    if not raw:
        return 'invalid'
    text, st = decode_bytes(raw, dict_entries)
    # Pure text allows direct chars/dictionary, E2-E7 katakana, F8 newline, FF terminator.
    # Unknown controls are intentionally classified as mixed rather than guessed.
    return 'text' if st['unknown'] == 0 else 'mixed'


# Russian translation font layout supplied for this project.
# Text byte 00 is space. Uppercase letters are direct codes 01..21 (decimal 1..33).
# The engine command E1..EF renders the next 1..15 direct character codes from
# the +0x40 tile set, so the same base codes become lowercase tiles 41..61.
RU_ALPHABET_UPPER = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
RU_ALPHABET_LOWER = RU_ALPHABET_UPPER.lower()
RU_UPPER_ENC = {ch: i for i, ch in enumerate(RU_ALPHABET_UPPER, 1)}
RU_LOWER_BASE_ENC = {ch: i for i, ch in enumerate(RU_ALPHABET_LOWER, 1)}
# v0.8.3 preserves the original UI arrows at tiles 40 (right) and 3B (down).
# Lowercase а..э remain direct 41..5F. ю/я are mirrored from their user-font
# glyphs 60/61 into two ordinary kana slots 2C/2D, which are direct text codes.
# This keeps every Russian letter one byte without sacrificing navigation arrows.
RU_LOWER_DIRECT_ENC = {ch: 0x41+i for i, ch in enumerate(RU_ALPHABET_LOWER[:31])}
RU_LOWER_DIRECT_ENC[RU_ALPHABET_LOWER[31]] = 0x2C  # ю
RU_LOWER_DIRECT_ENC[RU_ALPHABET_LOWER[32]] = 0x2D  # я
RU_LOWER_DIRECT_DEC = {v:k for k,v in RU_LOWER_DIRECT_ENC.items()}
RU_BASE_DEC = {i: ch for i, ch in enumerate(RU_ALPHABET_UPPER, 1)}
RU_PUNCT_ENC = {' ': 0x00, '-': 0x33, '—': 0x33, '!': 0x35, '?': 0x36, ':': 0x3A, '…': 0x3D, ',': 0x3E, '.': 0x3F}
# v0.8 extended dictionary repurposes D0..EF. Digits are copied to spare
# direct glyph tiles/codes 22..2B, so numeric text no longer conflicts with it.
RU_DIGIT_ENC = {str(i): 0x22+i for i in range(10)}
RU_DIGIT_DEC = {v:k for k,v in RU_DIGIT_ENC.items()}
RU_PUNCT_DEC = {v: k for k, v in RU_PUNCT_ENC.items()}


def encode_ru(text: str, *, newline=0xF8):
    """Encode Russian text for the v0.8 direct-lowercase engine patch.

    Uppercase letters use 01..21. Lowercase а..э use 41..5F directly.
    ю/я use spare direct kana slots 2C/2D so UI arrows 40/3B stay original.
    Raw bytes may still be inserted as <$AB> escapes.
    """
    out = bytearray(); i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\n':
            out.append(newline); i += 1; continue
        m = ESC_RE.match(text, i)
        if m:
            out.append(int(m.group(1), 16)); i = m.end(); continue
        if ch in RU_UPPER_ENC:
            out.append(RU_UPPER_ENC[ch]); i += 1; continue
        if ch in RU_LOWER_DIRECT_ENC:
            out.append(RU_LOWER_DIRECT_ENC[ch]); i += 1; continue
        if ch in RU_PUNCT_ENC:
            out.append(RU_PUNCT_ENC[ch]); i += 1; continue
        if ch in RU_DIGIT_ENC:
            out.append(RU_DIGIT_ENC[ch]); i += 1; continue
        raise ValueError(f'Russian character not supported at position {i}: {text[i:i+12]!r}')
    return bytes(out)


def decode_ru_bytes(bs: bytes, *, stop_at_ff=True):
    """Decode Russian records using the v0.8 direct-lowercase layout.

    Legacy E1..EF runs are still accepted for inspecting older test ROMs.
    """
    out=[]; i=0
    while i < len(bs):
        b=bs[i]; i+=1
        if b == 0xFF and stop_at_ff: break
        if b == 0xF8:
            out.append('\n'); continue
        if b in RU_BASE_DEC:
            out.append(RU_BASE_DEC[b]); continue
        if b in RU_LOWER_DIRECT_DEC:
            out.append(RU_LOWER_DIRECT_DEC[b]); continue
        if b in RU_PUNCT_DEC:
            out.append(RU_PUNCT_DEC[b]); continue
        if b in RU_DIGIT_DEC:
            out.append(RU_DIGIT_DEC[b]); continue
        if 0xE1 <= b <= 0xEF:
            n=b&0x0F
            if i+n > len(bs):
                out.append(f'<${b:02X}:TRUNC>'); break
            for x in bs[i:i+n]:
                if x in RU_BASE_DEC: out.append(RU_BASE_DEC[x].lower())
                elif x in RU_PUNCT_DEC: out.append(RU_PUNCT_DEC[x])
                else: out.append(f'<${x:02X}>')
            i += n; continue
        out.append(f'<${b:02X}>')
    return ''.join(out)


def ru_render_tile_indices(bs: bytes, *, stop_at_ff=True):
    """Return modeled tile indices for v0.8 direct-lowercase Russian text."""
    out=[]; i=0; run=0
    while i < len(bs):
        b=bs[i]; i+=1
        if b == 0xFF and stop_at_ff: break
        if b == 0xF8:
            out.append(None); continue
        if b == 0xFB and i < len(bs):
            out.append(bs[i]); i+=1; continue
        if 0xE0 <= b <= 0xEF:
            run=b&0x0F; continue
        code=b
        if b in RU_LOWER_DIRECT_DEC:
            # Patched 4x/5x handler writes the byte itself as glyph index;
            # code 3B (я) is already a normal direct glyph.
            code=b
        elif run:
            run -= 1
            if 0 < code < 0x33: code += 0x40
        out.append(code)
    return out


def load_table(path: str | Path):
    enc, dec = {}, {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip('\n\r')
        if not line or line.lstrip().startswith('#'):
            continue
        if '=' not in line:
            continue
        a, b = line.split('=', 1)
        code = int(a.strip(), 16)
        # Escape common textual sequences in table values.
        val = b.replace('\\n','\n').replace('\\s',' ')
        dec[code] = val
        if val and val not in enc:
            enc[val] = code
    return enc, dec

ESC_RE = re.compile(r'<\$([0-9A-Fa-f]{2})>')


def encode_with_table(text: str, char_to_byte: dict[str,int], *, newline=0xF8):
    out = bytearray(); i = 0
    keys = sorted(char_to_byte, key=len, reverse=True)
    while i < len(text):
        if text[i] == '\n':
            out.append(newline); i += 1; continue
        m = ESC_RE.match(text, i)
        if m:
            out.append(int(m.group(1), 16)); i = m.end(); continue
        matched = False
        for k in keys:
            if text.startswith(k, i):
                out.append(char_to_byte[k]); i += len(k); matched = True; break
        if matched: continue
        raise ValueError(f'Character/sequence not in table at position {i}: {text[i:i+12]!r}')
    return bytes(out)
