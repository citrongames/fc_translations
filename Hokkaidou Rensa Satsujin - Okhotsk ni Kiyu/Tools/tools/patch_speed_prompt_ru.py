#!/usr/bin/env python3
from __future__ import annotations
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import read_ines,text_region,read_pointer_table,TEXT_BANK_FIRST,PRG_BANK_SIZE
from stream_codec import parse_stream
from ru_bpe import load_bpe_rules,encode_ru_markup_bpe

REPLACEMENTS={
    5:'Куроки:[F3],верно?\n[F1:$02]Скорость текста?',
    6:'Куроки:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
    7:'Сюн:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
}
# v0.8.19 reflow bug signature: IDs 6/7 contain a page break in the middle of the
# speed-selection prompt. ID5 is compacted too for consistency and extra safety.
BUG_PAGE=bytes.fromhex('F1 0A FE F9 F1 02')

def patch(inrom:Path,outrom:Path,bpe_path:Path)->None:
    info=read_ines(inrom)
    reg=text_region(info)
    ptrs=read_pointer_table(reg)
    rules=load_bpe_rules(bpe_path)
    raw=bytearray(info['raw'])
    region_file_off=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    for rid,text in REPLACEMENTS.items():
        p=ptrs[rid]
        old,ops,ok=parse_stream(reg,p)
        if not ok: raise RuntimeError(f'ID {rid}: malformed current stream at ${p:04X}')
        new=encode_ru_markup_bpe(text,rules)+b'\xFF'
        # Idempotent path.
        if old==new:
            print(f'ID {rid}: already patched')
            continue
        if rid in (6,7) and BUG_PAGE not in old:
            raise RuntimeError(f'ID {rid}: expected v0.8.19 broken speed-prompt signature not found')
        if len(new)>len(old):
            raise RuntimeError(f'ID {rid}: replacement grew {len(old)} -> {len(new)} bytes; in-place patch unsafe')
        q=region_file_off+p
        raw[q:q+len(new)]=new
        # Leave any bytes after the new FF untouched; they are unreachable. This avoids
        # overwriting a possible suffix-shared object placed immediately after the record.
        print(f'ID {rid}: ${p:04X} {len(old)} -> {len(new)} bytes')
    outrom.write_bytes(raw)
    print('Wrote:',outrom)

def main():
    ap=argparse.ArgumentParser(description='Fix v0.8.19 speed-selection prompt split after password/continue.')
    ap.add_argument('rom');ap.add_argument('-o','--out',required=True)
    ap.add_argument('--ru-bpe',default=str(ROOT/'project_template/ru_bpe.tsv'))
    a=ap.parse_args();patch(Path(a.rom),Path(a.out),Path(a.ru_bpe))
if __name__=='__main__':main()
