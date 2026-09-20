#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import *
from stream_codec import parse_stream
from translation_codec import encode_ru_markup
from workfile import parse_work


def main():
    ap=argparse.ArgumentParser(description='Safe IN-PLACE text patcher. For overflow/relocation use repack_script.py.')
    ap.add_argument('rom'); ap.add_argument('workfile')
    ap.add_argument('--codec',choices=['table','ru'],default='ru')
    ap.add_argument('--table',help='HEX=character table for --codec table')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    info=read_ines(args.rom); raw=bytearray(info['raw']); region=text_region(info); ptrs=read_pointer_table(region)
    enc=None
    if args.codec=='table':
        if not args.table: ap.error('--table is required for --codec table')
        enc,_=load_table(args.table)
    patches=[]
    for rec in parse_work(args.workfile):
        if rec.get('tr','')=='': continue
        p=rec.get('ptr')
        if p is None: raise SystemExit('workfile block has no PTR')
        for rid in rec.get('ids',[]):
            if rid>=len(ptrs) or ptrs[rid]!=p:
                raise SystemExit(f'Pointer mismatch: ID {rid}, work ${p:04X}, ROM ${ptrs[rid] if rid<len(ptrs) else -1:04X}')
        old,ops,ok=parse_stream(region,p)
        if not ok: raise SystemExit(f'PTR ${p:04X}: original stream is truncated')
        try:
            encoded=encode_ru_markup(rec['tr']) if args.codec=='ru' else encode_with_table(rec['tr'],enc)
        except ValueError as e:
            raise SystemExit(f'PTR ${p:04X}: {e}')
        payload=encoded+b'\xFF'
        if len(payload)>len(old):
            raise SystemExit(f'PTR ${p:04X} too long for in-place mode: {len(payload)} > {len(old)}; use repack_script.py')
        file_off=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE+p
        patches.append((p,file_off,payload,len(old),rec.get('ids',[])))
    print(f'Patches ready: {len(patches)}; codec={args.codec}')
    for p,off,payload,oldlen,ids in patches:
        print(f' PTR ${p:04X} IDs={ids}: {len(payload)}/{oldlen} bytes @ file 0x{off:X}')
        if not args.dry_run: raw[off:off+len(payload)]=payload
    if not args.dry_run:
        Path(args.out).write_bytes(raw); print('Wrote',args.out)

if __name__=='__main__': main()
