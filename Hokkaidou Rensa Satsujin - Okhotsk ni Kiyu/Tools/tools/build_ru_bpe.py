#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,heapq
from collections import Counter
from pathlib import Path
from okhotsk_common import read_ines,text_region,read_pointer_table,dictionary,encode_ru
from workfile import parse_work
from translation_codec import MARKER_RE,RAW_OLD_RE
from ru_dictionary import TOKEN_POOL,PRESERVE_TOKENS,EXTRA_DICT_TOKENS
from ru_bpe import BPERule,encode_ru_markup_bpe,rule_depths,expand_bpe_bytes,compress_visible_bytes
from shared_translations import load_shared_translations


def visible_segments(recs):
    for r in recs:
        s=r.get('tr',''); i=0
        if not s: continue
        while i<len(s):
            if s[i]=='\n': i+=1; continue
            m=RAW_OLD_RE.match(s,i) or MARKER_RE.match(s,i)
            if m: i=m.end(); continue
            j=i
            while j<len(s) and s[j]!='\n' and not RAW_OLD_RE.match(s,j) and not MARKER_RE.match(s,j): j+=1
            if j>i: yield encode_ru(s[i:j])
            i=j


def replace(seq:list[int], pat:tuple[int,...], tok:int):
    out=[];i=0;n=0;L=len(pat)
    while i<len(seq):
        if i+L<=len(seq) and tuple(seq[i:i+L])==pat:
            out.append(tok);i+=L;n+=1
        else: out.append(seq[i]);i+=1
    return out,n


def exact_occ(seqs,pat):
    L=len(pat);n=0
    for s in seqs:
        i=0
        while i+L<=len(s):
            if tuple(s[i:i+L])==pat:n+=1;i+=L
            else:i+=1
    return n


def main():
    ap=argparse.ArgumentParser(description='Build nested RU BPE dictionary for Okhotsk FC (60..CF + v0.8 D0..EF extension).')
    ap.add_argument('rom');ap.add_argument('workfile');ap.add_argument('-o','--out',required=True)
    ap.add_argument('--pair-rules',type=int,default=79,help='high-frequency pair rules before direct n-gram rules (default 79)')
    ap.add_argument('--max-ngram',type=int,default=20)
    ap.add_argument('--extra-dict-max-bytes',type=int,default=384,
                    help='maximum PHYSICAL bytes for the D0..EF secondary dictionary including FF terminators')
    ap.add_argument('--shared-translations',default=None,help='include shared-stream RU text in the BPE training corpus')
    args=ap.parse_args()
    info=read_ines(args.rom);reg=text_region(info);ptrs=read_pointer_table(reg);orig=dictionary(reg,ptrs)
    cap=ptrs[1]-ptrs[0]
    fixed=112+sum(len(orig[t-0x60]) for t in PRESERVE_TOKENS)
    main_budget=cap-fixed
    recs=[r for r in parse_work(args.workfile) if r.get('tr','')]
    shared=load_shared_translations(args.shared_translations)
    corpus_recs=recs+[{'tr':tr,'ptr':ptr,'shared':True} for ptr,tr in shared.items()]
    raw_segments=[bytes(x) for x in visible_segments(corpus_recs)]
    seqs=[list(x) for x in raw_segments]
    pool=list(TOKEN_POOL);rules=[]
    main_used=0; extra_used=0; extra_entries=0

    def fit_cost(tok:int,L:int):
        nonlocal main_used,extra_used,extra_entries
        if tok < 0xD0:
            return (main_used+L<=main_budget, 0)
        entries=tok-0xD0+1
        physical=extra_used+L+entries
        added=L+(entries-extra_entries)
        return (physical<=args.extra_dict_max_bytes, added)

    def commit(tok:int,L:int):
        nonlocal main_used,extra_used,extra_entries
        if tok<0xD0: main_used+=L
        else:
            extra_used+=L
            extra_entries=max(extra_entries,tok-0xD0+1)

    pair_n=max(0,min(args.pair_rules,len(pool)))
    # Stage 1: RePair-style high-frequency adjacent pairs.
    for tok in pool[:pair_n]:
        ok,cost=fit_cost(tok,2)
        if not ok:
            continue
        cnt=Counter()
        for s in seqs: cnt.update(zip(s,s[1:]))
        best=None
        for pair,freq in cnt.most_common(96):
            if freq < 2: break
            n=exact_occ(seqs,pair)
            if n < 2: continue
            save=n # pair -> one byte, saving 1 each occurrence
            if tok>=0xD0 and save-cost<=0: continue
            best=(n,pair);break
        if not best: continue
        n,pat=best
        for k,s in enumerate(seqs): seqs[k],_=replace(s,pat,tok)
        rules.append(BPERule(tok,bytes(pat),'PAIR',n,n));commit(tok,2)

    assigned={r.token for r in rules}
    # Stage 2: direct longer n-grams. Main-dictionary bytes are already fixed
    # cartridge space, while extra D0..EF rules must repay their own table bytes.
    for tok in pool:
        if tok in assigned: continue
        cnt=Counter()
        for s in seqs:
            N=len(s)
            for L in range(3,min(args.max_ngram,N)+1):
                for i in range(N-L+1): cnt[tuple(s[i:i+L])]+=1
        tops=[]
        for pat,freq in cnt.items():
            L=len(pat); ok,cost=fit_cost(tok,L)
            if freq<2 or not ok: continue
            gross=freq*(L-1)
            net=gross-(cost if tok>=0xD0 else 0)
            if tok>=0xD0 and net<=0: continue
            item=(net,gross,L,freq,pat)
            if len(tops)<64: heapq.heappush(tops,item)
            elif item>tops[0]: heapq.heapreplace(tops,item)
        if not tops: continue
        tops.sort(reverse=True);best=None
        for _,gross,L,freq,pat in tops:
            n=exact_occ(seqs,pat);save=n*(L-1);ok,cost=fit_cost(tok,L)
            if n<2 or not ok: continue
            net=save-(cost if tok>=0xD0 else 0)
            if tok>=0xD0 and net<=0: continue
            score=(net,save/L,L,n)
            if best is None or score>best[0]: best=(score,pat,n,L,save)
        if not best: continue
        _,pat,n,L,save=best
        for k,s in enumerate(seqs):seqs[k],_=replace(s,pat,tok)
        rules.append(BPERule(tok,bytes(pat),'NGRAM',n,save));commit(tok,L)
        assigned.add(tok)

    # Rules must stay in numeric/dependency order. Generation already follows TOKEN_POOL order.
    for raw in raw_segments:
        c=compress_visible_bytes(raw,rules)
        if expand_bpe_bytes(c,rules)!=raw: raise SystemExit('internal BPE roundtrip failure')
    p=Path(args.out);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        f.write('# Nested RU byte-pair/n-gram dictionary. TSV order is dependency order.\n')
        f.write('# 60 and 62 preserve original control macros. D0..EF use the v0.8 secondary dictionary.\n')
        w=csv.writer(f,delimiter='\t');w.writerow(['TOKEN','EXPANSION_HEX','KIND','OCCURRENCES','CORPUS_SAVING'])
        for r in rules:w.writerow([f'{r.token:02X}',r.expansion.hex(' ').upper(),r.kind,r.occurrences,r.corpus_saving])
    depths=rule_depths(rules); maxdepth=max(depths.values(),default=0)
    total_payload=sum(len(encode_ru_markup_bpe(r['tr'],rules))+1 for r in corpus_recs)
    orig_payload=0
    for r in corpus_recs:
        ptr=r.get('ptr')
        if ptr is not None:
            from stream_codec import parse_stream
            orig_payload+=len(parse_stream(reg,ptr)[0])
    main_logical=fixed+main_used
    extra_physical=extra_used+extra_entries
    print(f'Translated roots: {len(recs)}; shared streams: {len(shared)}; corpus objects: {len(corpus_recs)}; original bytes: {orig_payload}; BPE bytes incl FF: {total_payload}; delta: {total_payload-orig_payload:+d}')
    print(f'Main dictionary: {main_logical}/{cap} bytes; tail slack: {cap-main_logical}; main rules payload: {main_used}/{main_budget}')
    print(f'Extra D0..EF dictionary: {extra_physical}/{args.extra_dict_max_bytes} bytes; entries through: {extra_entries}/32; payload: {extra_used}; total rules: {len(rules)}')
    print(f'Max nested RU dictionary depth: {maxdepth} (engine source slots before $6B allow indices 0..7; avoid deep F2+BPE combinations)')
    print(p)
if __name__=='__main__':main()
