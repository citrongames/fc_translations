#!/usr/bin/env python3
from pathlib import Path
import argparse
from okhotsk_common import read_ines, text_region, read_pointer_table, get_record, encode_ru, TEXT_BANK_FIRST, PRG_BANK_SIZE
from rle_packbits import encode_exact_length
from font_extract import STREAM_PRG_OFF, OUT_SIZE, ALLOC_END_PRG_OFF

TEST_ID=237
TEST_PTR=0x142D
TEST_TEXT='Тест русского шрифта.\nЁжик съел хлеб.'


def main():
    ap=argparse.ArgumentParser(description='Build the v0.4 Russian font/text smoke-test ROM from the studied original ROM.')
    ap.add_argument('rom'); ap.add_argument('-o','--out',default='Okhotsk_RU_v0.4_TEST.nes')
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    info=read_ines(a.rom); raw=bytearray(info['raw'])

    # Font patch.
    font=(root/'assets/font_ru.bin').read_bytes()
    if len(font)!=OUT_SIZE: raise SystemExit('assets/font_ru.bin has wrong size')
    stream_len=ALLOC_END_PRG_OFF-STREAM_PRG_OFF
    try:
        packed=encode_exact_length(font,stream_len)
    except ValueError as e:
        raise SystemExit(str(e))
    foff=info['prg_offset']+STREAM_PRG_OFF
    raw[foff:foff+stream_len]=packed

    # First message patch.
    region=text_region(info); ptrs=read_pointer_table(region)
    if ptrs[TEST_ID]!=TEST_PTR: raise SystemExit(f'Unexpected ID {TEST_ID} ptr: {ptrs[TEST_ID]:04X}')
    old=get_record(region,TEST_PTR)
    payload=encode_ru(TEST_TEXT)+b'\xFF'
    if len(payload)>len(old): raise SystemExit(f'Test text too long: {len(payload)} > {len(old)}')
    toff=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE+TEST_PTR
    raw[toff:toff+len(payload)]=payload

    Path(a.out).write_bytes(raw)
    print(f'Built {a.out}')
    print(f'Font: exact {len(packed)} compressed bytes; text ID {TEST_ID}: {len(payload)}/{len(old)} bytes')

if __name__=='__main__': main()
