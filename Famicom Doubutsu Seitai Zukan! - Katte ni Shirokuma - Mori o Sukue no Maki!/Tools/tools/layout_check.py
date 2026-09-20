#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
import re

from katte_codec import parse_script, TOKEN_RE

CYR_RE = re.compile(r'[А-ЯЁа-яё]')
DICT_RE = re.compile(r'^D(\d{1,2})(?::.*)?$', re.S)


def expand_dictionary(text: str, entries, seen=None) -> str:
    """Expand {Dxx:...} to the actual current D:xxx text for layout checks."""
    if seen is None:
        seen=set()
    out=[]
    pos=0
    for m in TOKEN_RE.finditer(text):
        out.append(text[pos:m.start()])
        tok=m.group(1)
        dm=DICT_RE.match(tok)
        if dm:
            idx=int(dm.group(1))
            key=('D',idx)
            if key in seen:
                out.append('{D%02d}' % idx)
            elif key in entries:
                out.append(expand_dictionary(entries[key]['text'], entries, seen | {key}))
            else:
                out.append('')
        else:
            out.append(m.group(0))
        pos=m.end()
    out.append(text[pos:])
    return ''.join(out)


def page_lines(text: str):
    """Return pages as lists of rendered cell counts and visible strings.

    {LN} starts a new row, {NEXT} starts a new page. Other control/raw tokens
    are zero-width for this conservative dialogue-window check.
    """
    pages=[['']]
    pos=0
    for m in TOKEN_RE.finditer(text):
        pages[-1][-1] += text[pos:m.start()]
        tok=m.group(1)
        if tok == 'LN':
            pages[-1].append('')
        elif tok == 'NEXT':
            pages.append([''])
        # all other tokens are control bytes and do not consume a text cell here
        pos=m.end()
    pages[-1][-1] += text[pos:]
    # Ignore a trailing empty row created by a final {LN}.
    for p in pages:
        while len(p) > 1 and p[-1] == '':
            p.pop()
    while len(pages) > 1 and pages[-1] == ['']:
        pages.pop()
    return pages


def check_layout(entries, width=16, rows=3, only_cyrillic=True):
    problems=[]
    for (block,idx), ent in sorted(entries.items()):
        if block != 'B1':
            continue
        if only_cyrillic and not CYR_RE.search(ent['text']):
            continue
        expanded=expand_dictionary(ent['text'], entries)
        pages=page_lines(expanded)
        for pno, page in enumerate(pages,1):
            if len(page) > rows:
                problems.append((block,idx,pno,'rows',len(page),page))
            for lno,line in enumerate(page,1):
                if len(line) > width:
                    problems.append((block,idx,pno,'width',lno,line))
    return problems


def format_problem(p):
    block,idx,pno,kind,a,b=p
    if kind == 'rows':
        return f'{block}:{idx:03d} page {pno}: {a} rows > 3: {b!r}'
    return f'{block}:{idx:03d} page {pno} line {a}: {len(b)} cells > 16: {b!r}'


def main():
    ap=argparse.ArgumentParser(description='Check translated B1 dialogue for 16x3 text-window overflow')
    ap.add_argument('script',type=Path)
    ap.add_argument('--width',type=int,default=16)
    ap.add_argument('--rows',type=int,default=3)
    ap.add_argument('--all',action='store_true',help='check Japanese/untranslated B1 entries too')
    a=ap.parse_args()
    entries=parse_script(a.script)
    problems=check_layout(entries,a.width,a.rows,only_cyrillic=not a.all)
    if problems:
        for p in problems:
            print(format_problem(p))
        raise SystemExit(f'FAIL: {len(problems)} layout problem(s)')
    print(f'PASS: translated B1 entries fit {a.width}x{a.rows} dialogue layout')

if __name__=='__main__':
    main()
