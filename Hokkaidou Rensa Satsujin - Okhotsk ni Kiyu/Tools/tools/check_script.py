#!/usr/bin/env python3
from __future__ import annotations
import argparse, re
from collections import Counter
from workfile import parse_work
from translation_codec import encode_ru_markup
from ru_dictionary import load_ru_dictionary
from ru_bpe import load_bpe_rules, encode_ru_markup_bpe
from shared_translations import load_shared_translations

MARKER = re.compile(r'\[[^\[\]\n]+\]|<\$[0-9A-Fa-f]{2}>')


FC_PREFIX_WIDTH = {
    0x07: 7,  # max('*:', 'Такано:')
    0x15: 9,  # max('*:', 'Сакагути:')
    0x4E: 4,  # max('*:', 'Таэ:')
    0x5C: 7,  # max('*:', 'Макико:')
    0x63: 7,  # max('*:', 'Мэгуми:')
}
FC_AT_LINE_START = re.compile(r'^\[FC:\$([0-9A-Fa-f]{2})\]')

def visible_len(line: str) -> int:
    # Most controls are zero-width. FC is special: it injects a speaker prefix
    # on the SAME screen line, so include the maximum prefix width possible
    # for that argument/state combination. Unknown FC args conservatively use 9.
    extra = 0
    m = FC_AT_LINE_START.match(line)
    if m:
        extra = FC_PREFIX_WIDTH.get(int(m.group(1), 16), 9)
    return len(MARKER.sub('', line)) + extra


def markers(s: str):
    return re.findall(r'\[[^\[\]\n]+\]', s)


def main():
    ap=argparse.ArgumentParser(description='QA checker for Okhotsk RU script work file.')
    ap.add_argument('workfile')
    ap.add_argument('--text-width',type=int,default=27,help='warning limit; original JP dump reaches 27 visible chars on a line')
    ap.add_argument('--menu-width',type=int,default=10,help='warning/error limit for command-menu labels')
    ap.add_argument('--max-lines',type=int,default=4,help='warning limit for a text page')
    ap.add_argument('--strict',action='store_true',help='treat layout warnings as errors')
    ap.add_argument('--ru-dict',default=None,help='legacy Russian phrase dictionary TSV for encoded-size checks')
    ap.add_argument('--ru-bpe',default=None,help='nested RU BPE TSV for encoded-size checks')
    ap.add_argument('--shared-translations',default=None,help='also QA JSON translated shared F2 streams')
    args=ap.parse_args()

    recs=parse_work(args.workfile)
    _,text_to_token=load_ru_dictionary(args.ru_dict)
    bpe_rules=load_bpe_rules(args.ru_bpe)
    errors=[]; warnings=[]; translated=0; total_bytes=0
    menu_ids=set(range(17,227))
    for r in recs:
        tr=r.get('tr','')
        if tr=='': continue
        translated += 1
        try:
            enc=(encode_ru_markup_bpe(tr,bpe_rules) if bpe_rules else encode_ru_markup(tr,text_to_token))+b'\xff'
            total_bytes += len(enc)
        except Exception as e:
            errors.append(f"ID {r.get('id','?'):04d} PTR ${r.get('ptr',0):04X}: encode: {e}")
            continue
        rid=r.get('id',-1)
        pages=tr.split('[F9]')
        if rid in menu_ids:
            lines=tr.split('\n')
            for n,line in enumerate(lines,1):
                w=visible_len(line)
                if w>args.menu_width:
                    (errors if args.strict else warnings).append(f'ID {rid:04d}: menu line {n} width {w}>{args.menu_width}: {line!r}')
        else:
            for pg,page in enumerate(pages,1):
                lines=page.split('\n')
                for n,line in enumerate(lines,1):
                    w=visible_len(line)
                    if w>args.text_width:
                        (errors if args.strict else warnings).append(f'ID {rid:04d}: page {pg} line {n} width {w}>{args.text_width}: {line!r}')
                if len(lines)>args.max_lines:
                    (errors if args.strict else warnings).append(f'ID {rid:04d}: page {pg} has {len(lines)} lines>{args.max_lines}')
        # Dynamic/special controls present in JP but absent from translation are suspicious.
        # F2 may deliberately be flattened, so it is only a warning. F8 is represented as newline.
        jpmarks=[m for m in markers(r.get('jp','')) if m.startswith('[F')]
        trmarks=markers(tr)
        missing=[]
        tc=Counter(trmarks)
        for m in jpmarks:
            if tc[m]: tc[m]-=1
            else: missing.append(m)
        if missing:
            warnings.append(f'ID {rid:04d}: translation omits original controls: {", ".join(missing)}')

    print(f'Translated records: {translated}; encoded bytes incl. FF: {total_bytes}')
    if warnings:
        print(f'WARNINGS ({len(warnings)}):')
        for x in warnings[:100]: print('  '+x)
        if len(warnings)>100: print(f'  ... {len(warnings)-100} more')
    shared=load_shared_translations(args.shared_translations)
    shared_bytes=0
    for ptr,tr in sorted(shared.items()):
        try:
            enc=(encode_ru_markup_bpe(tr,bpe_rules) if bpe_rules else encode_ru_markup(tr,text_to_token))+b'\xff'
            shared_bytes += len(enc)
        except Exception as e:
            errors.append(f'SHARED ${ptr:04X}: encode: {e}')
            continue
        for pg,page in enumerate(tr.split('[F9]'),1):
            for n,line in enumerate(page.split('\n'),1):
                w=visible_len(line)
                if w>args.text_width:
                    (errors if args.strict else warnings).append(f'SHARED ${ptr:04X}: page {pg} line {n} width {w}>{args.text_width}: {line!r}')
    if shared:
        print(f'Shared translations: {len(shared)}; encoded bytes incl. FF: {shared_bytes}')
    if errors:
        print(f'ERRORS ({len(errors)}):')
        for x in errors: print('  '+x)
        raise SystemExit(2)
    print('QA: OK' if not warnings else 'QA: OK with warnings')

if __name__=='__main__': main()
