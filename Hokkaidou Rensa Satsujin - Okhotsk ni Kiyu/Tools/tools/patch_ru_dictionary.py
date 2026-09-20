#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv
from pathlib import Path
from okhotsk_common import read_ines, text_region, read_pointer_table, dictionary, TEXT_BANK_FIRST, PRG_BANK_SIZE
from translation_codec import encode_ru_markup
from ru_dictionary import (load_ru_dictionary, PRESERVE_TOKENS, TOKEN_POOL,
                           MAIN_DICT_TOKENS, EXTRA_DICT_TOKENS, EXTRA_DICT_START,
                           is_dict_token)
from ru_bpe import load_bpe_rules


def build_dictionary_regions(original_entries: list[bytes], token_to_text: dict[int,str], main_capacity: int, bpe_rules=None):
    if len(original_entries) < 112:
        raise ValueError(f'expected at least 112 original dictionary entries, got {len(original_entries)}')
    bpe_map={r.token:r.expansion for r in (bpe_rules or [])}
    available=set(PRESERVE_TOKENS)
    main_entries=[]
    for tok in MAIN_DICT_TOKENS:
        idx=tok-0x60
        if tok in PRESERVE_TOKENS:
            ent=original_entries[idx]
        elif tok in bpe_map:
            ent=bpe_map[tok]
            for b in ent:
                if is_dict_token(b) and b not in available:
                    raise ValueError(f'token {tok:02X}: nested reference to future/unassigned token {b:02X}')
        elif tok in token_to_text and token_to_text[tok]:
            ent=encode_ru_markup(token_to_text[tok], None)
            if any(is_dict_token(b) for b in ent):
                raise ValueError(f'token {tok:02X}: phrase entry unexpectedly contains a dictionary token')
        else:
            ent=b''
        main_entries.append(ent)
        available.add(tok)
    main_blob=b''.join(e+b'\xFF' for e in main_entries)
    if len(main_blob)>main_capacity:
        raise ValueError(f'RU main dictionary needs {len(main_blob)} bytes, capacity is {main_capacity} (over by {len(main_blob)-main_capacity})')
    main_logical=len(main_blob)
    main_blob += bytes(main_capacity-len(main_blob))

    used_extra=[t for t in EXTRA_DICT_TOKENS if t in bpe_map or (t in token_to_text and token_to_text[t])]
    extra_entries=[]; extra_blob=b''
    if used_extra:
        high=max(used_extra)
        for tok in range(0xD0,high+1):
            if tok in bpe_map:
                ent=bpe_map[tok]
                for b in ent:
                    if is_dict_token(b) and b not in available:
                        raise ValueError(f'token {tok:02X}: nested reference to future/unassigned token {b:02X}')
            elif tok in token_to_text and token_to_text[tok]:
                ent=encode_ru_markup(token_to_text[tok],None)
                if any(is_dict_token(b) for b in ent):
                    raise ValueError(f'token {tok:02X}: phrase entry unexpectedly contains a dictionary token')
            else:
                ent=b''
            extra_entries.append(ent); available.add(tok)
        extra_blob=b''.join(e+b'\xFF' for e in extra_entries)
    return main_blob,main_entries,main_logical,extra_blob,extra_entries


def main():
    ap=argparse.ArgumentParser(description='Patch Okhotsk Russian dictionaries: original 60..CF table plus v0.8 D0..EF secondary table.')
    ap.add_argument('rom')
    ap.add_argument('ru_dictionary_tsv',help='phrase TSV or nested BPE TSV')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--report',default=None)
    args=ap.parse_args()
    info=read_ines(args.rom); region=text_region(info); ptrs=read_pointer_table(region)
    orig=dictionary(region,ptrs)
    start,end=ptrs[0],ptrs[1]; cap=end-start

    txt=Path(args.ru_dictionary_tsv).read_text(encoding='utf-8-sig')
    is_bpe='\tEXPANSION_HEX' in txt or any('EXPANSION_HEX' in x for x in txt.splitlines()[:5])
    bpe_rules=load_bpe_rules(args.ru_dictionary_tsv) if is_bpe else []
    token_to_text={}
    if not bpe_rules:
        token_to_text,_=load_ru_dictionary(args.ru_dictionary_tsv)
    main_blob,main_entries,main_logical,extra_blob,extra_entries=build_dictionary_regions(orig,token_to_text,cap,bpe_rules)

    out=bytearray(info['raw'])
    base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    out[base+start:base+end]=main_blob
    if extra_blob:
        x0=EXTRA_DICT_START; x1=x0+len(extra_blob)
        if x1>0x4000:
            raise ValueError(f'extra dictionary crosses bank A: ${x0:04X}-${x1-1:04X}')
        out[base+x0:base+x1]=extra_blob
    Path(args.out).write_bytes(out)

    print(f'Main dictionary physical region: ${start:04X}-${end-1:04X} ({cap} bytes)')
    print(f'Main logical 112 entries: {main_logical} bytes; unreachable padding: {cap-main_logical} bytes')
    if extra_blob:
        print(f'Extra dictionary: ${EXTRA_DICT_START:04X}-${EXTRA_DICT_START+len(extra_blob)-1:04X} ({len(extra_blob)} bytes, {len(extra_entries)} entries D0..{0xD0+len(extra_entries)-1:02X})')
    else:
        print('Extra dictionary: not used')
    print(f'Russian assigned BPE tokens: {len(bpe_rules)}')
    print(f'Preserved control tokens: {", ".join(f"{t:02X}" for t in sorted(PRESERVE_TOKENS))}')
    print(f'Wrote: {args.out}')
    if args.report:
        with Path(args.report).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f,delimiter='\t'); w.writerow(['TOKEN','REGION','BYTES','TEXT'])
            for tok,e in zip(MAIN_DICT_TOKENS,main_entries):
                if tok in PRESERVE_TOKENS: label='(PRESERVED ORIGINAL CONTROL)'
                elif bpe_rules and e: label='BPE '+e.hex(' ').upper()
                else: label=token_to_text.get(tok,'')
                w.writerow([f'{tok:02X}','MAIN',e.hex(' ').upper(),label])
            for i,e in enumerate(extra_entries):
                tok=0xD0+i
                label=('BPE '+e.hex(' ').upper()) if bpe_rules and e else token_to_text.get(tok,'')
                w.writerow([f'{tok:02X}','EXTRA',e.hex(' ').upper(),label])

if __name__=='__main__': main()
