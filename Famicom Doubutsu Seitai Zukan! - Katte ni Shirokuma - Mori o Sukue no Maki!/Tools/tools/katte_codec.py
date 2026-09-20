#!/usr/bin/env python3
from __future__ import annotations
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

EXPECTED_DATA_CRC32 = 0xF8C1A690

@dataclass(frozen=True)
class Block:
    name: str
    pointer_table: int
    count: int
    pointer_delta: int
    dictionary_codes: bool = True

BLOCKS = {
    "B0": Block("B0", 0x0C1A6, 153, 0x4010, True),
    "B1": Block("B1", 0x10010, 898, 0x8010, True),
    "D":  Block("D",  0x17A99, 91,  0x8010, False),
}

# Direct one-byte glyphs / punctuation confirmed from the ROM and known script.
BYTE_TO_CHAR = {
    0x8B:'が',0x8C:'ぎ',0x8D:'ぐ',0x8E:'げ',0x8F:'ご',
    0x90:'ざ',0x91:'じ',0x92:'ず',0x93:'ぜ',0x94:'ぞ',
    0x95:'だ',0x96:'ぢ',0x97:'づ',0x98:'で',0x99:'ど',
    0x9A:'ば',0x9B:'び',0x9C:'ぶ',0x9D:'べ',0x9E:'ぼ',
    0x9F:'ド',
    0xA1:'ダ',0xA2:'ジ',0xA3:'ポ',
    0xA4:'ぱ',0xA5:'ぴ',0xA6:'ぷ',0xA7:'ぺ',0xA8:'ぽ',
    0xA9:'H',0xAA:'P',0xAB:'I',0xAC:'Q',
    0xAD:'ロ',0xAE:'ウ',0xAF:'リ',
    0xB2:'「',0xB4:'ー',0xB5:'‥',0xB6:'!',0xB7:'?',0xBA:'>',0xBB:'.',
    0xBD:'イ',0xBE:'ン',0xBF:'ト',
    0xC0:'ゃ',0xC1:'ゅ',0xC2:'ょ',0xC3:'っ',0xC4:'を',
    0xC5:'あ',0xC6:'い',0xC7:'う',0xC8:'え',0xC9:'お',
    0xCA:'か',0xCB:'き',0xCC:'く',0xCD:'け',0xCE:'こ',
    0xCF:'さ',0xD0:'し',0xD1:'す',0xD2:'せ',0xD3:'そ',
    0xD4:'た',0xD5:'ち',0xD6:'つ',0xD7:'て',0xD8:'と',
    0xD9:'な',0xDA:'に',0xDB:'ぬ',0xDC:'ね',0xDD:'の',
    0xDE:'は',0xDF:'ひ',0xE0:'ふ',0xE1:'へ',0xE2:'ほ',
    0xE3:'ま',0xE4:'み',0xE5:'む',0xE6:'め',0xE7:'も',
    0xE8:'や',0xE9:'ゆ',0xEA:'よ',0xEB:'ら',0xEC:'り',
    0xED:'る',0xEE:'れ',0xEF:'ろ',0xF0:'わ',0xF1:'ん',
    0xF2:'0',0xF3:'1',0xF4:'2',0xF5:'3',0xF6:'4',
    0xF7:'5',0xF8:'6',0xF9:'7',0xFA:'8',0xFB:'9',
    0xFD:'メ',0xFE:'シ',0xFF:' ',
}
CHAR_TO_BYTE = {v:k for k,v in BYTE_TO_CHAR.items()}

# Russian encoding uses only direct-render text tile codes (>= $A9),
# avoiding the voiced-kana renderer path and the UI graphics at $8B-$A8.
# NOTE: $B8 is NOT a printable free tile in the dialogue renderer.
# It is an original screen/appearance effect command (used before the God appears).
# Earlier builds incorrectly assigned Cyrillic uppercase Й to $B8, which triggered
# that effect in names such as ДАЙ.  Uppercase Й is therefore placed at printable
# code $FD instead; the user font copies the Й glyph from tile $B8 to $FD.
RU_UPPER_CODES = [
    0xA9,0xAA,0xAB,0xAC,0xAD,0xAE,0xAF,0xB0,0xB1,0xB5,0xFD,0xB9,0xBC,0xBD,0xBE,0xBF,
    *range(0xC0,0xD1),
]
RU_LOWER_CODES = list(range(0xD1,0xF2))
RU_UPPER = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
RU_LOWER = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
RU_CHAR_TO_BYTE = dict(zip(RU_UPPER, RU_UPPER_CODES))
RU_CHAR_TO_BYTE.update(dict(zip(RU_LOWER, RU_LOWER_CODES)))
RU_CHAR_TO_BYTE['-'] = 0xB4
RU_CHAR_TO_BYTE['—'] = 0xB4
CHAR_TO_BYTE.update(RU_CHAR_TO_BYTE)

CONTROL_TO_BYTE = {
    'ED':0x01,
    'FACE02':0x02,
    'FACE03':0x03,
    'FACE04':0x04,
    'LN':0x89,
    'NEXT':0xB3,
}
BYTE_TO_CONTROL = {v:k for k,v in CONTROL_TO_BYTE.items()}

ENTRY_RE = re.compile(r'^@@\s+(B0|B1|D):(\d{3})\s+PTR=([0-9A-Fa-f]+)\s+STR=([0-9A-Fa-f]+)\s+LEN=(\d+)(?:\s+CODE=([0-9A-Fa-f]+))?\s*$')
TOKEN_RE = re.compile(r'\{([^{}]+)\}')


def check_rom(rom: bytes, strict=True) -> int:
    if len(rom) < 16 or rom[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    crc = zlib.crc32(rom[16:]) & 0xffffffff
    if strict and crc != EXPECTED_DATA_CRC32:
        raise ValueError(f'Unexpected ROM CRC32: {crc:08X}; expected {EXPECTED_DATA_CRC32:08X}')
    return crc


def pointer_entries(rom: bytes, block: Block):
    out=[]
    for i in range(block.count):
        po = block.pointer_table + i*2
        ptr = rom[po] | (rom[po+1] << 8)
        so = ptr + block.pointer_delta
        try:
            end = rom.index(0, so)
        except ValueError:
            raise ValueError(f'No terminator for {block.name}:{i:03d} at ${so:X}')
        raw = rom[so:end]
        out.append((i, po, so, raw))
    return out


def build_dictionary(rom: bytes):
    dblock = BLOCKS['D']
    entries = pointer_entries(rom, dblock)
    return [raw for _,_,_,raw in entries]


def decode_direct(raw: bytes) -> str:
    out=[]
    for b in raw:
        if b in BYTE_TO_CONTROL:
            out.append('{' + BYTE_TO_CONTROL[b] + '}')
        elif b in BYTE_TO_CHAR:
            out.append(BYTE_TO_CHAR[b])
        else:
            out.append(f'{{{b:02X}}}')
    return ''.join(out)


def decode(raw: bytes, dictionary: list[bytes] | None, expand_dict=True) -> str:
    out=[]
    for b in raw:
        if expand_dict and dictionary is not None and 0x05 <= b <= 0x5F:
            idx=b-0x05
            if idx < len(dictionary):
                annotation=decode_direct(dictionary[idx]).replace('{','<').replace('}','>')
                out.append(f'{{D{idx:02d}:{annotation}}}')
                continue
        if b in BYTE_TO_CONTROL:
            out.append('{' + BYTE_TO_CONTROL[b] + '}')
        elif b in BYTE_TO_CHAR:
            out.append(BYTE_TO_CHAR[b])
        else:
            out.append(f'{{{b:02X}}}')
    return ''.join(out)


def _encode_token(tok: str) -> int:
    if tok in CONTROL_TO_BYTE:
        return CONTROL_TO_BYTE[tok]
    if tok.startswith('D'):
        m=re.match(r'^D(\d{1,2})(?::.*)?$', tok, re.S)
        if m:
            idx=int(m.group(1))
            if not 0 <= idx <= 90:
                raise ValueError(f'Dictionary index out of range: {idx}')
            return 0x05 + idx
    if re.fullmatch(r'[0-9A-Fa-f]{2}', tok):
        return int(tok,16)
    raise ValueError(f'Unknown token {{{tok}}}')


def encode(text: str) -> bytes:
    out=bytearray()
    pos=0
    for m in TOKEN_RE.finditer(text):
        plain=text[pos:m.start()]
        for ch in plain:
            if ch not in CHAR_TO_BYTE:
                raise ValueError(f'Character not in current table: {ch!r} U+{ord(ch):04X}')
            out.append(CHAR_TO_BYTE[ch])
        out.append(_encode_token(m.group(1)))
        pos=m.end()
    for ch in text[pos:]:
        if ch not in CHAR_TO_BYTE:
            raise ValueError(f'Character not in current table: {ch!r} U+{ord(ch):04X}')
        out.append(CHAR_TO_BYTE[ch])
    return bytes(out)


def parse_script(path: Path):
    lines=path.read_text(encoding='utf-8').splitlines()
    entries={}
    i=0
    while i < len(lines):
        m=ENTRY_RE.match(lines[i])
        if not m:
            i+=1; continue
        block=m.group(1); idx=int(m.group(2))
        ptr=int(m.group(3),16); st=int(m.group(4),16); ln=int(m.group(5)); code=m.group(6)
        i+=1
        text_lines=[]
        while i < len(lines) and lines[i] != '@@END':
            text_lines.append(lines[i]); i+=1
        if i >= len(lines):
            raise ValueError(f'Missing @@END for {block}:{idx:03d}')
        text='\n'.join(text_lines)
        if '\n' in text:
            raise ValueError(f'Physical newline inside {block}:{idx:03d}; use {{LN}} token instead')
        entries[(block,idx)]={'ptr':ptr,'str':st,'len':ln,'code':code,'text':text}
        i+=1
    return entries
