#!/usr/bin/env python3
from __future__ import annotations
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import read_ines,text_region,PRG_BANK_SIZE,TEXT_BANK_FIRST
from rle_packbits import decode,encode_exact_length
from font_extract import STREAM_PRG_OFF,ALLOC_END_PRG_OFF,OUT_SIZE
from ru_bpe import load_bpe_rules,encode_ru_markup_bpe
from stream_codec import parse_stream

# v0.8.21 compacted blackjack ID 1353 reintroduced the ORIGINAL JP F2 target
# $EC53.  Localize that old shared slot in place so the loss-by-no-chips branch
# cannot fall back to Japanese.  14-byte RU stream fits in the original 17 bytes.
LOSS_SHARED_TEXT='Сюн:Продолжим\n[F1:$02]расследование!\n[F1:$0A][FE][F9]'
LOSS_SHARED_ADDR=0xEC53
LOSS_SHARED_OLD=bytes.fromhex('65 06 15 00 0A 17 06 74 4A 2F 05 17 07 6B 35 62 FF')

# User-supplied replacement digit 0.  Asymmetric inner strokes distinguish 0
# from Cyrillic О, especially on password/memo screens.
ZERO_TILE=bytes.fromhex('3C 46 4A 4A 52 52 62 3C 00 00 00 00 00 00 00 00')
ZERO_DIRECT_TILE=0x22
ZERO_LEGACY_TILE=0x74


def _ines(raw:bytes):
    if len(raw)<16 or raw[:4]!=b'NES\x1a': raise ValueError('Not an iNES ROM')
    off=16+(512 if raw[6]&4 else 0)
    return off,raw[4]*PRG_BANK_SIZE


def patch(raw:bytes,bpe_path:Path)->bytes:
    prg_off,prg_size=_ines(raw)
    out=bytearray(raw)
    prg=bytearray(out[prg_off:prg_off+prg_size])

    # 1) Main text/password font.  Patch both direct digit $22 and legacy/input
    # digit $74, then preserve the exact compressed-stream byte length.
    packed_src=bytes(prg[STREAM_PRG_OFF:ALLOC_END_PRG_OFF])
    font,used=decode(packed_src,OUT_SIZE)
    expected_len=ALLOC_END_PRG_OFF-STREAM_PRG_OFF
    if used!=expected_len:
        raise ValueError(f'font stream consumed {used}, expected {expected_len}')
    fb=bytearray(font)
    for tile in (ZERO_DIRECT_TILE,ZERO_LEGACY_TILE):
        fb[tile*16:(tile+1)*16]=ZERO_TILE
    repacked=encode_exact_length(bytes(fb),expected_len)
    prg[STREAM_PRG_OFF:ALLOC_END_PRG_OFF]=repacked

    # 2) Stale original blackjack shared target $EC53.
    rules=load_bpe_rules(bpe_path)
    new=encode_ru_markup_bpe(LOSS_SHARED_TEXT,rules)+b'\xFF'
    if len(new)>len(LOSS_SHARED_OLD):
        raise ValueError(f'localized loss stream grew {len(new)}>{len(LOSS_SHARED_OLD)}')
    text_base=TEXT_BANK_FIRST*PRG_BANK_SIZE
    q=text_base+LOSS_SHARED_ADDR
    cur=bytes(prg[q:q+len(LOSS_SHARED_OLD)])
    # Idempotence: accept already-localized prefix ending in FF.  Keep trailing
    # bytes outside the new FF untouched; no live root/F2 starts inside them.
    if not cur.startswith(new):
        if cur!=LOSS_SHARED_OLD:
            raise ValueError(f'blackjack loss shared ${LOSS_SHARED_ADDR:04X}: unexpected {cur.hex(" ").upper()}')
        prg[q:q+len(new)]=new

    out[prg_off:prg_off+prg_size]=prg
    return bytes(out)


def main():
    ap=argparse.ArgumentParser(description='v0.8.21 -> v0.8.22: translate stale blackjack loss shared stream and install user digit-0 tile.')
    ap.add_argument('rom');ap.add_argument('-o','--out',required=True)
    ap.add_argument('--ru-bpe',default=str(ROOT/'project_template/ru_bpe.tsv'))
    a=ap.parse_args()
    raw=Path(a.rom).read_bytes();out=patch(raw,Path(a.ru_bpe));Path(a.out).write_bytes(out)
    print('Patched blackjack stale F2 $EC53 -> Russian loss continuation.')
    print('Installed user digit 0 into font tiles $22 and $74.')
    print('Wrote:',a.out)
if __name__=='__main__':main()
