#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, struct
from pathlib import Path
from collections import defaultdict, Counter
from okhotsk_common import read_ines, text_region, read_pointer_table, dictionary, TEXT_BANK_FIRST, PRG_BANK_SIZE
from stream_codec import parse_stream, collect_f2_graph, stream_refs_f2
from translation_codec import encode_ru_markup
from ru_dictionary import load_ru_dictionary
from workfile import parse_work


def patch_f2_payload(payload: bytes, mapping: dict[int,int]) -> bytes:
    if not mapping or b'\xF2' not in payload:
        return payload
    b=bytearray(payload)
    raw,ops,ok=parse_stream(bytes(b),0,max_len=max(len(b),1))
    for op in ops:
        if op.code==0xF2 and len(op.args)==2:
            old=op.args[0] | (op.args[1]<<8)
            if old in mapping:
                new=mapping[old]
                b[op.offset+1]=new & 0xFF
                b[op.offset+2]=(new>>8)&0xFF
    return bytes(b)


def main():
    ap=argparse.ArgumentParser(description='Conservative stream-aware script repacker for Okhotsk FC.')
    ap.add_argument('rom')
    ap.add_argument('workfile')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--report',default=None)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--ru-dict',default=None,help='Russian dictionary TSV used while encoding TR blocks')
    ap.add_argument('--use-dictionary-slack',action='store_true',help='allow relocation into unused tail after the 112th dictionary entry')
    args=ap.parse_args()

    info=read_ines(args.rom); region=text_region(info); ptrs=read_pointer_table(region); _=dictionary(region,ptrs)
    _,text_to_token=load_ru_dictionary(args.ru_dict)
    dict_slack=None
    if args.use_dictionary_slack:
        ds,de=ptrs[0],ptrs[1]
        pos=ds; seen=0
        while pos<de and seen<112:
            if region[pos]==0xFF: seen+=1
            pos+=1
        if seen!=112:
            raise SystemExit(f'Cannot locate 112 dictionary terminators before ${de:04X}')
        dict_slack=[pos,de]
    work=parse_work(args.workfile)
    work_by_ptr={r['ptr']:r for r in work if 'ptr' in r}

    byptr=defaultdict(list)
    for i,p in enumerate(ptrs[2:],2):
        if p!=0xFFFF and 0<=p<len(region): byptr[p].append(i)
    starts=sorted(byptr)

    # Parse original physical records.
    recs={}
    for p in starts:
        raw,ops,complete=parse_stream(region,p)
        recs[p]={'start':p,'end':p+len(raw),'raw':raw,'ops':ops,'complete':complete,'ids':byptr[p]}

    allstreams,graph=collect_f2_graph(region,starts)
    f2_targets={r for rr in graph.values() for r in rr}
    startset=set(starts)

    # Conservative relocation eligibility: no stream/pointer entry starts in the middle.
    # Start-address F2 references are OK because we patch them after the new layout is known.
    for p,r in recs.items():
        interior_ptr=any(p<x<r['end'] for x in startset)
        interior_f2=any(p<x<r['end'] for x in f2_targets)
        r['reloc_ok']=r['complete'] and not interior_ptr and not interior_f2
        r['reason']='' if r['reloc_ok'] else ('PTR_INTERIOR' if interior_ptr else 'F2_INTERIOR' if interior_f2 else 'TRUNCATED')

    # Validate workfile and create desired payloads. Empty TR means exact original bytes.
    translated=set(); desired={}
    for p,r in recs.items():
        w=work_by_ptr.get(p)
        if w and w.get('tr','')!='':
            # Verify all aliases still point here.
            for rid in w.get('ids',[]):
                if rid>=len(ptrs) or ptrs[rid]!=p:
                    raise SystemExit(f'Workfile mismatch: ID {rid} no longer points to ${p:04X}')
            try:
                payload=encode_ru_markup(w['tr'],text_to_token)+b'\xFF'
            except ValueError as e:
                raise SystemExit(f'PTR ${p:04X} / ID {w.get("id","?")}: {e}')
            desired[p]=payload; translated.add(p)
        else:
            desired[p]=r['raw']

    # Records that fit stay where they are. Only overflows request relocation.
    overflows={p for p in translated if len(desired[p])>len(recs[p]['raw'])}

    # Build maximal contiguous runs consisting ONLY of translated, relocation-safe records.
    # This deliberately refuses to move untranslated JP records: safer for partial patches.
    # If one translation grows, translate/shrink its physically adjacent records as well.
    runs=[]; cur=[]
    for p in starts:
        r=recs[p]
        if not r['reloc_ok'] or p not in translated:
            if cur: runs.append(cur); cur=[]
            continue
        if not cur:
            cur=[p]
        else:
            prev=cur[-1]
            if recs[prev]['end']==p:
                cur.append(p)
            else:
                runs.append(cur); cur=[p]
    if cur:runs.append(cur)

    run_for={p:run for run in runs for p in run}
    selected_runs=[]; impossible=[]
    for p in sorted(overflows):
        run=run_for.get(p)
        if not run:
            impossible.append((p,'not relocation-safe'))
            continue
        key=(run[0],run[-1])
        if key not in [(x[0],x[-1]) for x in selected_runs]: selected_runs.append(run)

    # Calculate complete new layout for selected runs.
    mapping={}
    run_stats=[]
    for run in selected_runs:
        capacity=recs[run[-1]]['end']-recs[run[0]]['start']
        need=sum(len(desired[p]) for p in run)
        if need>capacity:
            impossible.append((run[0],f'contiguous run needs {need} > capacity {capacity}'))
            continue
        pos=recs[run[0]]['start']
        for p in run:
            mapping[p]=pos; pos += len(desired[p])
        run_stats.append((run,capacity,need,pos))

    # Fallback: dictionary compression may leave a provably unreachable tail inside
    # the fixed dictionary region. Relocate individual safe overflow records there.
    slack_alloc=[]
    if impossible and dict_slack:
        pos,end=dict_slack
        still=[]
        for p,why in impossible:
            # A failed selected-run item may be the run start. Allocate every actual
            # overflow in that run individually instead of moving the whole run.
            candidates=[p]
            run=run_for.get(p)
            if run and why.startswith('contiguous run needs'):
                candidates=[q for q in run if q in overflows]
            okall=True
            for q in candidates:
                if q in mapping:
                    continue
                if not recs[q]['reloc_ok']:
                    okall=False; break
                need=len(desired[q])
                if pos+need>end:
                    okall=False; break
                mapping[q]=pos; slack_alloc.append((q,pos,need)); pos+=need
            if not okall:
                still.append((p,why+f'; dictionary slack exhausted ({end-pos} bytes left)'))
        impossible=still
        dict_slack=[pos,end]
    if impossible:
        msg=['Repack cannot place all overflows conservatively:']
        for p,why in impossible: msg.append(f'  ${p:04X}: {why}')
        if dict_slack: msg.append(f'  dictionary slack remaining: {dict_slack[1]-dict_slack[0]} bytes')
        msg.append('Translate/shrink adjacent records, improve RU dictionary compression, or reduce the batch.')
        raise SystemExit('\n'.join(msg))

    # Add identity mapping for everything else for simple pointer/ref patching.
    fullmap={p:mapping.get(p,p) for p in starts}
    moved={p:new for p,new in mapping.items() if p!=new}

    out_raw=bytearray(info['raw'])
    base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE

    # First apply ordinary translated records that are not in a repacked run.
    selected_members={p for run,_,_,_ in run_stats for p in run}
    slack_members={p for p,_,_ in slack_alloc}
    report_rows=[]
    for p in sorted(translated-selected_members-slack_members):
        payload=patch_f2_payload(desired[p],fullmap)
        oldlen=len(recs[p]['raw'])
        if len(payload)>oldlen:
            raise SystemExit(f'Internal error: overflow ${p:04X} was not repacked')
        if not args.dry_run:
            out_raw[base+p:base+p+len(payload)]=payload
        report_rows.append([p,p,oldlen,len(payload),'INPLACE',','.join(map(str,recs[p]['ids']))])

    # Write records relocated into dictionary slack. Their old bytes are left intact.
    for p,new,need in slack_alloc:
        payload=patch_f2_payload(desired[p],fullmap)
        if not args.dry_run:
            out_raw[base+new:base+new+len(payload)]=payload
        report_rows.append([p,new,len(recs[p]['raw']),len(payload),'DICTSLACK',','.join(map(str,recs[p]['ids']))])

    # Then rebuild each selected contiguous run from its start and clear any remaining tail.
    for run,capacity,need,endpos in run_stats:
        start=recs[run[0]]['start']; blob=bytearray()
        for p in run:
            payload=patch_f2_payload(desired[p],fullmap)
            assert fullmap[p]==start+len(blob)
            blob.extend(payload)
            report_rows.append([p,fullmap[p],len(recs[p]['raw']),len(payload),'REPACK',','.join(map(str,recs[p]['ids']))])
        if not args.dry_run:
            out_raw[base+start:base+start+capacity]=blob + bytes(capacity-len(blob))

    # Rewrite pointer table entries for every moved record (all aliases).
    for old,new in moved.items():
        for rid in byptr[old]:
            if not args.dry_run:
                struct.pack_into('<H',out_raw,base+rid*2,new)

    # Patch F2 references in every stream reachable from the ORIGINAL pointer roots, including
    # F2-only shared streams that were not themselves moved. For sources inside a selected run,
    # their payload was already patched above; skip old locations that were overwritten.
    moved_old_intervals=[(recs[run[0]]['start'],recs[run[-1]]['end']) for run,_,_,_ in run_stats]
    def old_overwritten(addr): return any(a<=addr<b for a,b in moved_old_intervals)
    external_patches=0
    for src in sorted(allstreams):
        if old_overwritten(src):
            continue
        raw_s,ops,ok=parse_stream(region,src)
        for op in ops:
            if op.code==0xF2 and len(op.args)==2:
                old=op.args[0]|(op.args[1]<<8)
                if old in moved:
                    new=moved[old]
                    off=base+op.offset+1
                    if not args.dry_run:
                        out_raw[off]=new&0xff; out_raw[off+1]=(new>>8)&0xff
                    external_patches+=1

    # Verify no pointer-table corruption and every translated pointer resolves to the expected bytes.
    if not args.dry_run:
        Path(args.out).write_bytes(out_raw)
        chk=read_ines(args.out); reg2=text_region(chk); p2=read_pointer_table(reg2)
        for old in translated:
            expected=fullmap[old]
            for rid in byptr[old]:
                if p2[rid]!=expected:
                    raise SystemExit(f'Post-build pointer verification failed for ID {rid}')
            raw2,_,ok=parse_stream(reg2,expected)
            expected_payload=patch_f2_payload(desired[old],fullmap)
            if raw2!=expected_payload:
                raise SystemExit(f'Post-build payload verification failed for ${old:04X} -> ${expected:04X}')

    report=Path(args.report) if args.report else Path(args.out).with_suffix('.repack.tsv')
    with report.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t'); w.writerow(['old_ptr','new_ptr','old_len','new_len','mode','ids'])
        for row in sorted(report_rows):
            row2=row.copy(); row2[0]=f'{row2[0]:04X}'; row2[1]=f'{row2[1]:04X}'; w.writerow(row2)

    print(f'Translated physical records: {len(translated)}')
    print(f'Overflow records: {len(overflows)}; repacked runs: {len(run_stats)}; dictionary-slack relocations: {len(slack_alloc)}; moved starts: {len(moved)}')
    if args.use_dictionary_slack and dict_slack:
        print(f'Dictionary slack remaining after allocations: {dict_slack[1]-dict_slack[0]} bytes')
    print(f'External F2 address patches: {external_patches}')
    print(f'Report: {report}')
    if args.dry_run: print('Dry-run only; ROM not written.')
    else: print(f'Wrote: {args.out}')

if __name__=='__main__': main()
