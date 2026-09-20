#!/usr/bin/env python3
from __future__ import annotations
import argparse,struct,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import read_ines,text_region,read_pointer_table,TEXT_BANK_FIRST,PRG_BANK_SIZE
from stream_codec import parse_stream
from ru_bpe import load_bpe_rules,encode_ru_markup_bpe

ROOT_ID=1291
ENDING_RU='''КУРОКИ:САРУВАТАРИ…\n[F1:$02]А РЯДОМ МАКИКО.\n[F1:$0A][FE][F9]СЧАСТЛИВАЯ ПАРА.\n[F1:$02]ШЕФ,ЧЕГО ЗАГРУСТИЛИ?\n[F1:$0A][FE][F9]НЕУЖЕЛИ ВЫ ТОЖЕ\n[F1:$02]ЛЮБИЛИ МАКИКО?\n[F1:$0A][FE][F9]НУ СКАЖИТЕ!\n[F1:$02]ШЕФ!НУ ШЕФ…\n[F1:$0A][FE][F9]'''

# The ending-photo screen uses background pattern table 1.  On that screen
# tiles 41-5F are photo graphics, not the ordinary RU lowercase glyphs.
# Therefore this one root must render using only uppercase RU tiles 01-21,
# digits/punctuation and control macros.  The compact uppercase translation
# is deliberately <= the already allocated v0.8.22 physical record.

def main():
    ap=argparse.ArgumentParser(description='Fix final photo dialogue: use only safe uppercase RU glyphs on the photo CHR set.')
    ap.add_argument('rom')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--ru-bpe',default=str(ROOT/'project_template/ru_bpe.tsv'))
    a=ap.parse_args()

    info=read_ines(a.rom); region=text_region(info); ptrs=read_pointer_table(region)
    p=ptrs[ROOT_ID]
    if not (0 <= p < len(region)):
        raise SystemExit(f'ID {ROOT_ID} has invalid pointer ${p:04X}')
    old,_,ok=parse_stream(region,p)
    if not ok: raise SystemExit(f'ID {ROOT_ID} stream is truncated')

    rules=load_bpe_rules(a.ru_bpe)
    payload=encode_ru_markup_bpe(ENDING_RU,rules)+b'\xFF'
    if len(payload)>len(old):
        raise SystemExit(f'ending payload grew: {len(payload)} > slot {len(old)}')

    # Strong safety assertion: no ordinary lowercase direct glyph codes and
    # no ordinary BPE tokens.  Only 60/62 are allowed >=60; both are original
    # control macros (newline/F1 sequences), not visible glyphs.
    bad=[b for b in payload if 0x41 <= b <= 0x5F]
    if bad: raise SystemExit('ending payload still contains lowercase direct glyph bytes')
    allowed_hi={0x60,0x62,0xF1,0xF9,0xFE,0xFF}
    bad_hi=[b for b in payload if b>=0x60 and b not in allowed_hi]
    if bad_hi: raise SystemExit('ending payload contains BPE/high glyph tokens unsafe for photo CHR: '+','.join(f'{b:02X}' for b in sorted(set(bad_hi))))

    raw=bytearray(info['raw'])
    base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    q=base+p
    cur=bytes(raw[q:q+len(old)])
    # Idempotence: if already exactly patched, leave it alone.
    if cur[:len(payload)]==payload and all(x==0 for x in cur[len(payload):]):
        Path(a.out).write_bytes(raw)
        print(f'ID {ROOT_ID}: already patched at text ${p:04X}; {len(payload)}/{len(old)} bytes')
        print('Wrote:',a.out);return
    raw[q:q+len(old)]=payload+bytes(len(old)-len(payload))
    Path(a.out).write_bytes(raw)
    print(f'ID {ROOT_ID}: final-photo RU uppercase, text ${p:04X}, {len(payload)}/{len(old)} bytes')
    print('Wrote:',a.out)

if __name__=='__main__':main()
