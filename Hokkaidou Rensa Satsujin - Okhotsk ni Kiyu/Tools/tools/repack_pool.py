#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,struct
from pathlib import Path
from collections import defaultdict
from okhotsk_common import read_ines,text_region,read_pointer_table,TEXT_BANK_FIRST,PRG_BANK_SIZE
from stream_codec import parse_stream,collect_f2_graph,stream_refs_f2
from workfile import parse_work
from ru_bpe import load_bpe_rules,encode_ru_markup_bpe
from translation_codec import encode_ru_markup
from ru_dictionary import load_ru_dictionary, EXTRA_DICT_START
from shared_translations import load_shared_translations


# FC is NOT an ordinary inline text command. Handler $C9E1 always switches
# to PRG bank $0A before reading pointer-table IDs 15/16. Therefore those
# two pointers MUST address bank-A offsets $0000-$3FFF. A generic pool
# relocation to banks B-D is invalid even if the normal pointer-table reader
# can address it. v0.8.1 missed this bank restriction and could point ID15/16
# at e.g. $8859; FC then actually read bank-A $0859 and produced garbage.
#
# The two FC lookup tables overlap physically:
#   ID15 -> entry 0 (generic), entry 1 (generic), then the ID16 table
#   ID16 -> entry 0 Takano, 1 Tae, 2 Sakaguchi, 3 Makiko, 4 Megumi
# Current ROM text uses only FC args $07,$15,$4E,$5C,$63, so no FC path
# selects beyond those seven FF-delimited entries. Keep the slab at the
# original bank-A base $140E; ID16 consequently remains $1414.
FC_ROOT15 = 0x140E
FC_ROOT16 = 0x1414
FC_FIXED_BASE = 0x140E
FC_SPECIAL_ROOTS = {FC_ROOT15, FC_ROOT16}

def build_fc_slab(desired, bpe, phrase_to_token):
    def enc(txt):
        x=encode_ru_markup_bpe(txt,bpe) if bpe else encode_ru_markup(txt,phrase_to_token)
        return x+b'\xFF'
    missing=[x for x in FC_SPECIAL_ROOTS if x not in desired]
    if missing:
        raise SystemExit('FC slab requires translated roots: '+', '.join(f'${x:04X}' for x in sorted(missing)))
    entries=[
        desired[FC_ROOT15],         # generic *:
        desired[FC_ROOT15],         # second generic entry
        desired[FC_ROOT16],         # Takano:
        enc('Таэ:'),
        enc('Сакагути:'),
        enc('Макико:'),
        enc('Мэгуми:'),
    ]
    offsets=[]; pos=0
    for e in entries:
        offsets.append(pos);pos+=len(e)
    old_to_index={FC_ROOT15:0,FC_ROOT16:2}
    return entries,offsets,old_to_index

def fc_entry_index(arg:int,state_bit_set:bool):
    """Emulate the table/index part of FC handler $C9E1 for one FC argument."""
    arg &= 0xFF
    if state_bit_set:
        return 2 + ((arg >> 3) & 0x07)  # ID16 base is slab entry 2
    return (arg >> 6) & 0x07            # ID15 base is slab entry 0


def intervals_from_mask(mask:list[bool]):
    out=[];i=0;N=len(mask)
    while i<N:
        if not mask[i]:i+=1;continue
        j=i+1
        while j<N and mask[j]:j+=1
        out.append([i,j]);i=j
    return out


def merge_intervals(xs):
    out=[]
    for a,b in sorted(xs):
        if b<=a:continue
        if out and a<=out[-1][1]:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out


def mark_stream(mask,region,p):
    raw,_,_=parse_stream(region,p)
    for i in range(p,min(len(region),p+len(raw))):mask[i]=True


def collect_live_stopping_at_translated(region,roots,translated):
    """Traverse F2 graph from untranslated roots, but translated pointer starts are boundaries.

    Calls into a translated physical record will later be patched to that record's new address,
    so the old translated bytes do not have to remain live solely because of that F2 edge.
    """
    seen=set(); todo=list(dict.fromkeys(int(x) for x in roots if 0<=int(x)<len(region) and int(x) not in translated))
    refs_to_trans=[]
    while todo:
        p=todo.pop()
        if p in seen or p in translated:continue
        seen.add(p)
        _,ops,_=parse_stream(region,p)
        for op in ops:
            if op.code==0xF2 and len(op.args)==2:
                t=op.args[0]|(op.args[1]<<8)
                if t in translated:
                    refs_to_trans.append((p,op.offset,t))
                elif 0<=t<len(region) and t not in seen:
                    todo.append(t)
    return seen,refs_to_trans


def patch_f2_payload(payload:bytes,mapping:dict[int,int]):
    if not mapping or b'\xF2' not in payload:return payload
    b=bytearray(payload);_,ops,_=parse_stream(bytes(b),0,max_len=max(1,len(b)))
    for op in ops:
        if op.code==0xF2 and len(op.args)==2:
            old=op.args[0]|(op.args[1]<<8)
            if old in mapping:
                new=mapping[old];b[op.offset+1]=new&255;b[op.offset+2]=(new>>8)&255
    return bytes(b)


def logical_dictionary_end(region,ptrs):
    pos=ptrs[0];seen=0
    while pos<ptrs[1] and seen<112:
        if region[pos]==0xFF:seen+=1
        pos+=1
    if seen!=112:raise ValueError('cannot locate the 112th dictionary terminator')
    return pos


def choose_suffix_roots(payloads:dict[bytes,list[int]]):
    """Return roots and payload->root mapping. Exact duplicates already share one key.

    Suffix sharing is restricted to streams with no explicit F2 command because an F2-address
    patch in a parent could otherwise mutate bytes that a child interprets differently.
    """
    uniq=list(payloads)
    parent={}
    safe={p:not any(op.code==0xF2 for op in parse_stream(p,0,max_len=max(1,len(p)))[1]) for p in uniq}
    for p in uniq:
        if not safe[p]:continue
        best=None
        for q in uniq:
            if p is q or not safe[q] or len(q)<=len(p):continue
            if q.endswith(p):
                if best is None or len(q)<len(best):best=q
        if best is not None:parent[p]=best
    def root(p):
        seen=set()
        while p in parent:
            if p in seen:raise ValueError('suffix cycle')
            seen.add(p);p=parent[p]
        return p
    rootmap={p:root(p) for p in uniq}
    roots=sorted(set(rootmap.values()),key=lambda x:(-len(x),x))
    return roots,rootmap,parent


def allocate_best_fit(items:list[bytes],holes:list[list[int]]):
    """Best-fit decreasing contiguous allocation. Returns payload->address and remaining holes."""
    hs=[h[:] for h in holes if h[1]>h[0]]; alloc={}
    for p in sorted(items,key=lambda x:(-len(x),x)):
        L=len(p); choices=[(b-a,i,a,b) for i,(a,b) in enumerate(hs) if b-a>=L]
        if not choices:
            return None,hs,p
        _,i,a,b=min(choices,key=lambda x:(x[0],x[2]))
        alloc[p]=a
        hs[i][0]=a+L
        if hs[i][0]==hs[i][1]:hs.pop(i)
    return alloc,hs,None



def extra_dictionary_blob_len(bpe_rules):
    extra=[r for r in bpe_rules if 0xD0 <= r.token <= 0xEF]
    if not extra:return 0
    high=max(r.token for r in extra)
    by={r.token:r.expansion for r in extra}
    return sum(len(by.get(tok,b''))+1 for tok in range(0xD0,high+1))

def subtract_interval(holes,a,b):
    out=[]
    for x,y in holes:
        if y<=a or x>=b:
            out.append([x,y]);continue
        if x<a:out.append([x,a])
        if y>b:out.append([b,y])
    return out

def main():
    ap=argparse.ArgumentParser(description='Safe translated-pool repacker for Okhotsk FC. Reclaims only text bytes no longer reachable from untranslated roots.')
    ap.add_argument('rom',help='ROM after font/dictionary patch, or clean ROM if no RU dictionary is used')
    ap.add_argument('workfile')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--ru-bpe',default=None,help='nested RU BPE TSV')
    ap.add_argument('--ru-dict',default=None,help='legacy phrase dictionary TSV')
    ap.add_argument('--report',default=None)
    ap.add_argument('--shared-translations',default=None,help='JSON mapping original F2 stream addresses to Russian markup')
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--use-known-padding',action='store_true',help='use verified all-zero bank-A padding $3FBA-$3FD7 (no pointer/F2 or absolute $BFBA reference in supported ROM)')
    args=ap.parse_args()
    info=read_ines(args.rom);region=text_region(info);ptrs=read_pointer_table(region)
    bpe=load_bpe_rules(args.ru_bpe)
    _,phrase_to_token=load_ru_dictionary(args.ru_dict)
    work=parse_work(args.workfile)
    shared_tr=load_shared_translations(args.shared_translations)
    work_by_ptr={r['ptr']:r for r in work if r.get('ptr') is not None}
    byptr=defaultdict(list)
    for rid,p in enumerate(ptrs[2:],2):
        if p!=0xFFFF and 0<=p<len(region):byptr[p].append(rid)
    roots=set(byptr)
    root_translated={p for p,r in work_by_ptr.items() if r.get('tr','')!='' and p in roots}
    allstreams,_=collect_f2_graph(region,roots)
    bad_shared=sorted(p for p in shared_tr if p not in allstreams)
    if bad_shared:
        raise SystemExit('Shared translation target(s) are not reachable original text streams: '+', '.join(f'${p:04X}' for p in bad_shared[:20]))
    if not root_translated:raise SystemExit('No translated root streams found.')
    # Desired ROOT payloads first. Shared translations are selected lazily: a translated
    # root that inlines its former F2 text no longer needs that shared object in ROM.
    desired={}
    desired_kind={}
    for p in root_translated:
        r=work_by_ptr[p]
        for rid in r.get('ids',[]):
            if rid>=len(ptrs) or ptrs[rid]!=p:raise SystemExit(f'workfile mismatch at ID {rid}')
        enc=encode_ru_markup_bpe(r['tr'],bpe) if bpe else encode_ru_markup(r['tr'],phrase_to_token)
        desired[p]=enc+b'\xFF'; desired_kind[p]='ROOT'

    fc_entries,fc_offsets,fc_old_to_index=build_fc_slab(desired,bpe,phrase_to_token)
    fc_slab_unpatched=b''.join(fc_entries)

    selected_shared=set(); required_old_shared=set(); todo=[]
    for blob in desired.values():
        todo.extend(stream_refs_f2(parse_stream(blob,0,max_len=max(1,len(blob)))[1]))
    while todo:
        p=todo.pop()
        if p in root_translated or p in selected_shared: continue
        if p in shared_tr:
            selected_shared.add(p)
            enc=encode_ru_markup_bpe(shared_tr[p],bpe) if bpe else encode_ru_markup(shared_tr[p],phrase_to_token)
            blob=enc+b'\xFF'
            desired[p]=blob; desired_kind[p]='SHARED'
            todo.extend(stream_refs_f2(parse_stream(blob,0,max_len=max(1,len(blob)))[1]))
        else:
            # A translated payload still calls this original stream and no RU replacement
            # was supplied. Keep the old stream graph live instead of reclaiming it.
            required_old_shared.add(p)
    translated=set(root_translated)|selected_shared
    # All original reachable text streams, and the subset that must remain at old addresses.
    live_roots=(roots-root_translated)|required_old_shared
    live,live_refs_to_trans=collect_live_stopping_at_translated(region,live_roots,translated)
    allmask=[False]*len(region);livemask=[False]*len(region)
    for p in allstreams:mark_stream(allmask,region,p)
    for p in live:mark_stream(livemask,region,p)
    reclaim=[a and not l for a,l in zip(allmask,livemask)]
    holes=intervals_from_mask(reclaim)
    stream_reclaim=sum(b-a for a,b in holes)
    # Tail after the 112th dictionary terminator is provably unreachable by 60..CF lookup.
    dend=logical_dictionary_end(region,ptrs)
    dict_slack=max(0,ptrs[1]-dend)
    if dict_slack:holes.append([dend,ptrs[1]])
    known_padding=0
    if args.use_known_padding:
        a,b=0x3FBA,0x3FD8
        if any(region[a:b]):
            raise SystemExit('Known padding $3FBA-$3FD7 is not all zero in this ROM; refusing to use it.')
        if any(livemask[a:b]):
            raise SystemExit('Known padding unexpectedly overlaps a live text stream; refusing to use it.')
        holes.append([a,b]); known_padding=b-a
    holes=merge_intervals(holes)
    # v0.8 D0..EF secondary dictionary is written AFTER repacking into a known
    # bank-A text hole. Reserve exactly its logical bytes now so translated
    # payload allocation can never overwrite it.
    extra_dict_len=extra_dictionary_blob_len(bpe)
    if extra_dict_len:
        a=EXTRA_DICT_START;b=a+extra_dict_len
        if b>0x4000:
            raise SystemExit(f'Extra dictionary ${a:04X}-${b-1:04X} crosses bank A.')
        if not all(reclaim[i] for i in range(a,b)):
            raise SystemExit(f'Extra dictionary ${a:04X}-${b-1:04X} is not fully reclaimable in this build; full-RU relocation is required.')
        holes=subtract_interval(holes,a,b)
    # Exact duplicate + byte-suffix sharing among translated streams.
    payload_to_old=defaultdict(list)
    for old,p in desired.items():
        if old in FC_SPECIAL_ROOTS: continue
        payload_to_old[p].append(old)
    store_roots,rootmap,parent=choose_suffix_roots(payload_to_old)
    # FC slab has a hard bank-A addressing constraint and is fixed at $140E.
    # Remove its bytes from the generic allocator (including reclaimable pieces);
    # the hidden name entries between ID15 and ID16 are FC-only and were never
    # part of the ordinary F2/root reachability graph.
    fc_base=FC_FIXED_BASE
    fc_end=fc_base+len(fc_slab_unpatched)
    if fc_end>0x4000:
        raise SystemExit('FC slab crosses bank A; handler $C9E1 cannot address it.')
    holes=subtract_interval(holes,fc_base,fc_end)
    allocation_items=store_roots
    alloc,remain,failed=allocate_best_fit(allocation_items,holes)
    if alloc is None:
        cap=sum(b-a for a,b in holes);need=sum(len(x) for x in allocation_items)
        msg=[f'Pool allocation failed: need {need} bytes, pool has {cap} bytes.']
        if failed is not None:msg.append(f'First unplaced payload: {len(failed)} bytes.')
        msg.append(f'Translated={len(translated)}, unique payloads={len(payload_to_old)}, stored roots after suffix sharing={len(store_roots)}; fixed FC slab {len(fc_slab_unpatched)} bytes at ${fc_base:04X}.')
        raise SystemExit('\n'.join(msg))
    # Map each old translated pointer to root allocation + suffix offset.
    mapping={}
    for payload,olds in payload_to_old.items():
        root=rootmap[payload];addr=alloc[root]+len(root)-len(payload)
        for old in olds:mapping[old]=addr
    for old,idx in fc_old_to_index.items():
        mapping[old]=fc_base+fc_offsets[idx]
    # Ensure patched payloads keep all suffix relationships valid.
    patched_roots={p:patch_f2_payload(p,mapping) for p in store_roots}
    patched_fc_entries=[patch_f2_payload(e,mapping) for e in fc_entries]
    if any(len(a)!=len(b) for a,b in zip(fc_entries,patched_fc_entries)):
        raise SystemExit('FC slab F2 patch changed entry length unexpectedly.')
    patched_fc_slab=b''.join(patched_fc_entries)
    for payload,root in rootmap.items():
        pp=patch_f2_payload(payload,mapping);pr=patched_roots[root]
        if not pr.endswith(pp):raise SystemExit('F2 patch invalidated a suffix-share relation; disable that share or inline the F2 call.')
    out=bytearray(info['raw']);base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    # Write generic allocated payloads and the fixed bank-A FC lookup slab.
    for p,addr in alloc.items():
        blob=patched_roots[p]
        if not args.dry_run:out[base+addr:base+addr+len(blob)]=blob
    if not args.dry_run:
        out[base+fc_base:base+fc_end]=patched_fc_slab
    # Rewrite every pointer-table alias for translated ROOT records. Shared-only streams have no pointer-table entry.
    for old in root_translated:
        new=mapping[old]
        for rid in byptr[old]:
            if not args.dry_run:struct.pack_into('<H',out,base+rid*2,new)
    # Patch F2 calls in live old streams that intentionally stop at translated targets.
    live_f2_patches=0
    for src in sorted(live):
        raw,ops,_=parse_stream(region,src)
        for op in ops:
            if op.code==0xF2 and len(op.args)==2:
                old=op.args[0]|(op.args[1]<<8)
                if old in mapping:
                    new=mapping[old];off=base+op.offset+1
                    if not args.dry_run:out[off]=new&255;out[off+1]=(new>>8)&255
                    live_f2_patches+=1
    # Report rows: one per translated root/shared stream.
    rows=[]
    for old in sorted(translated):
        p=desired[old]
        if old in FC_SPECIAL_ROOTS:
            mode=['FC_SLAB']
        else:
            root=rootmap[p];mode=[]
            if len(payload_to_old[p])>1:mode.append('DEDUP')
            if p!=root:mode.append('SUFFIX')
            if not mode:mode.append('POOL')
        rows.append([desired_kind.get(old,'SHARED'),old,mapping[old],len(parse_stream(region,old)[0]),len(p),'+'.join(mode),','.join(map(str,byptr.get(old,[])))])
    used_store=sum(len(x) for x in store_roots)+len(fc_slab_unpatched)
    pool_cap=sum(b-a for a,b in holes)
    suffix_saved=sum(len(p) for p in payload_to_old if p in parent)
    dedup_saved=sum((len(v)-1)*len(p) for p,v in payload_to_old.items())
    if not args.dry_run:
        Path(args.out).write_bytes(out)
        # Strong post-build verification of translated pointers and payloads.
        chk=read_ines(args.out);reg2=text_region(chk);p2=read_pointer_table(reg2)
        for old in translated:
            exp=mapping[old]
            if old in root_translated:
                for rid in byptr[old]:
                    if p2[rid]!=exp:raise SystemExit(f'post-build pointer mismatch ID {rid}: {p2[rid]:04X}!={exp:04X}')
            got,_,ok=parse_stream(reg2,exp,max_len=0x4000)
            want=patch_f2_payload(desired[old],mapping)
            if not ok or got!=want:raise SystemExit(f'post-build payload mismatch ${old:04X} -> ${exp:04X}')
        # FC $C9E1 hard-switches bank $0A and ORs pointer high-byte with $80.
        # Thus ID15/16 must remain bank-A offsets, not global A-D pool offsets.
        if p2[15] != fc_base or p2[16] != fc_base+fc_offsets[2]:
            raise SystemExit('post-build FC base pointer mismatch')
        if not (0 <= p2[15] < 0x4000 and 0 <= p2[16] < 0x4000):
            raise SystemExit('post-build FC pointer escaped bank A')
        pos=fc_base
        for i,want0 in enumerate(patched_fc_entries):
            got,_,ok=parse_stream(reg2,pos,max_len=max(1,len(want0)))
            if not ok or got!=want0:
                raise SystemExit(f'post-build FC slab entry {i} mismatch at ${pos:04X}')
            pos+=len(want0)
        # Verify every FC argument present in the original reachable text graph
        # resolves to one of the seven rebuilt entries for both tested-bit states.
        fc_args=set()
        for sp in allstreams:
            _,ops,_=parse_stream(region,sp)
            for op in ops:
                if op.code==0xFC and len(op.args)==1:
                    fc_args.add(op.args[0])
        for arg in sorted(fc_args):
            for state in (False,True):
                idx=fc_entry_index(arg,state)
                if idx>=len(patched_fc_entries):
                    raise SystemExit(f'FC ${arg:02X} state={int(state)} selects unsupported slab entry {idx}')
                table_base=p2[16] if state else p2[15]
                skip=((arg>>3)&7) if state else ((arg>>6)&7)
                q=table_base
                for _ in range(skip):
                    q=reg2.index(0xFF,q)+1
                want_addr=fc_base+fc_offsets[idx]
                if q!=want_addr:
                    raise SystemExit(f'FC ${arg:02X} state={int(state)} scan ${q:04X} != expected ${want_addr:04X}')
    report=Path(args.report) if args.report else Path(args.out).with_suffix('.pool.tsv')
    with report.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['kind','old_ptr','new_ptr','old_len','new_len','mode','ids'])
        for row in rows:
            row=row[:];row[1]=f'{row[1]:04X}';row[2]=f'{row[2]:04X}';w.writerow(row)
    print(f'Translated pointer roots: {len(root_translated)}; shared supplied/selected/pruned: {len(shared_tr)}/{len(selected_shared)}/{len(shared_tr)-len(selected_shared)}; relocation objects: {len(translated)}')
    print(f'Unique encoded payloads: {len(payload_to_old)} + fixed FC slab; stored roots after sharing: {len(store_roots)} + FC slab')
    print(f'Reclaimable stream bytes: {stream_reclaim}; dictionary-tail slack: {dict_slack}; known zero padding: {known_padding}; extra-dict reserve: {extra_dict_len}; total pool: {pool_cap}')
    print(f'Encoded bytes before sharing: {sum(len(x)*len(v) for x,v in payload_to_old.items()) + sum(len(desired[x]) for x in FC_SPECIAL_ROOTS)}; physical stored bytes: {used_store}; FC slab: {len(fc_slab_unpatched)} at bank-A ${fc_base:04X}')
    print(f'Exact-dedup saved: {dedup_saved}; suffix-sharing saved: {suffix_saved}')
    print(f'Live F2 calls redirected to translated records: {live_f2_patches}')
    print(f'Pool bytes remaining: {sum(b-a for a,b in remain)}; holes remaining: {len(remain)}')
    print(f'Report: {report}')
    if args.dry_run:print('Dry-run only; ROM not written.')
    else:print(f'Wrote: {args.out}')
if __name__=='__main__':main()
