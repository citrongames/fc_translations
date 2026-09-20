#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, re
from collections import Counter
from pathlib import Path
from workfile import parse_work
from translation_codec import encode_ru_markup
from ru_dictionary import TOKEN_POOL, PRESERVE_TOKENS
from okhotsk_common import read_ines, text_region, read_pointer_table, dictionary

MARKER_RE=re.compile(r'\[[^\[\]\n]+\]|<\$[0-9A-Fa-f]{2}>')
WORD_RE=re.compile(r'[А-ЯЁа-яё0-9]+(?::)?')


def visible_segments(s: str):
    for line in s.splitlines():
        pos=0
        for m in MARKER_RE.finditer(line):
            if m.start()>pos: yield line[pos:m.start()]
            pos=m.end()
        if pos<len(line): yield line[pos:]


def candidates(recs):
    c=Counter()
    allsegs=[]
    for r in recs:
        tr=r.get('tr','')
        if not tr: continue
        for seg in visible_segments(tr):
            if not seg: continue
            allsegs.append(seg)
            words=list(WORD_RE.finditer(seg))
            for m in words:
                w=m.group(0)
                if len(w)>=2: c[w]+=1
                if m.end()<len(seg) and seg[m.end()]==' ' and len(w)>=2: c[w+' ']+=1
            for n in (2,3):
                for i in range(len(words)-n+1):
                    a=words[i].start(); b=words[i+n-1].end()
                    phrase=seg[a:b]
                    if len(phrase)<=24: c[phrase]+=1
                    if b<len(seg) and seg[b]==' ' and len(phrase)<=23: c[phrase+' ']+=1
    # Recount exact occurrences across segments so repeats within a line are captured.
    out={}
    for ph in c:
        cnt=sum(seg.count(ph) for seg in allsegs)
        if cnt<2: continue
        try: L=len(encode_ru_markup(ph,None))
        except Exception: continue
        if L<2: continue
        net=cnt*(L-1)-L
        if net>0: out[ph]=(cnt,L,net)
    return out


def main():
    ap=argparse.ArgumentParser(description='Build a deterministic provisional Russian compression dictionary from translated TR blocks.')
    ap.add_argument('rom',help='clean supported JP ROM, used only to calculate dictionary capacity')
    ap.add_argument('workfile')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--max-tokens',type=int,default=len(TOKEN_POOL))
    args=ap.parse_args()
    info=read_ines(args.rom); reg=text_region(info); ptrs=read_pointer_table(reg); orig=dictionary(reg,ptrs)
    capacity=ptrs[1]-ptrs[0]
    base=112 + sum(len(orig[t-0x60]) for t in PRESERVE_TOKENS)
    budget=capacity-base
    cand=candidates(parse_work(args.workfile))
    # Greedy by net savings per dictionary byte, then total net, then longer phrase.
    ranked=sorted(cand.items(),key=lambda kv:(-(kv[1][2]/kv[1][1]),-kv[1][2],-len(kv[0]),kv[0]))
    chosen=[]; used=0
    for ph,(cnt,L,net) in ranked:
        if len(chosen)>=min(args.max_tokens,len(TOKEN_POOL)): break
        if used+L>budget: continue
        # Avoid selecting a phrase wholly contained in an already selected phrase
        # unless its independent score is substantially useful. This limits overlap.
        if any(ph in old and old!=ph for old,_,_,_ in chosen) and net < 4:
            continue
        chosen.append((ph,cnt,L,net)); used+=L
    p=Path(args.out); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        f.write('# Russian dictionary for Okhotsk FC. 60 and 62 remain original control macros.\n')
        f.write('# Unlisted safe tokens are emptied by patch_ru_dictionary.py.\n')
        w=csv.writer(f,delimiter='\t'); w.writerow(['TOKEN','TEXT','COUNT','RAW_BYTES','EST_NET_SAVING'])
        for tok,(ph,cnt,L,net) in zip(TOKEN_POOL,chosen):
            w.writerow([f'{tok:02X}',ph,cnt,L,net])
    print(f'Capacity: {capacity}; fixed base incl. terminators/preserved controls: {base}; RU expansion budget: {budget}')
    print(f'Chosen: {len(chosen)} tokens, {used}/{budget} expansion bytes; estimated independent savings: {sum(x[3] for x in chosen)} bytes')
    print(p)

if __name__=='__main__': main()
