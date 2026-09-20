#!/usr/bin/env python3
from __future__ import annotations
import argparse,re,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import read_ines,text_region,read_pointer_table,TEXT_BANK_FIRST,PRG_BANK_SIZE,encode_ru
from workfile import parse_work
from ru_bpe import load_bpe_rules,compress_visible_bytes,encode_ru_markup_bpe
from translation_codec import RAW_OLD_RE,MARKER_RE,_marker_bytes
from stream_codec import parse_stream
from patch_blackjack_ru import patch as patch_blackjack

OLD_BET_SUFFIX='-я карта.\n[F1:$02]Теперь тяну я.\n[F1:$0A][FE][F9]'
NEW_BET_SUFFIX=' фиш.\n[F1:$02]Теперь тяну я.\n[F1:$0A][FE][F9]'
CARD_BET_IDS=(1332,1333,1334,1335,1336,1571)

CARD_RESULT_REPLACEMENTS={
    1353:'Сюн:О,у вас кончились\n[F1:$02]фишки.\n[F1:$0A][FE][F9]Сюн:Эта партия моя!\n[F1:$02]Итог:[FD:$00] побед,[FD:$01] пораж.\n[F1:$0A][FE][F9][F2:$EC53]',
    1354:'Сюн:Ой,у меня кончились\n[F1:$02]фишки.\n[F1:$0A][FE][F9]Сюн:Итог:\n[F1:$02][FD:$01] побед,[FD:$00] пораж.\n[F1:$0A][FE][F9]',
}

def encode_legacy_numeric_glyphs(text:str,rules)->bytes:
    """v0.8.20 encoder semantics: GLYPH:D0..D9 incorrectly emitted raw Dn."""
    out=bytearray();i=0
    while i<len(text):
        if text[i]=='\n':out.append(0xF8);i+=1;continue
        m=RAW_OLD_RE.match(text,i)
        if m:out.append(int(m.group(1),16));i=m.end();continue
        m=MARKER_RE.match(text,i)
        if m:
            body=m.group(1);up=body.upper()
            if up.startswith('GLYPH:$D'):
                v=int(body.split('$',1)[1],16)
                if 0xD0<=v<=0xD9:out.append(v)
                else:out.extend(_marker_bytes(body))
            else:out.extend(_marker_bytes(body))
            i=m.end();continue
        j=i
        while j<len(text) and text[j]!='\n' and not RAW_OLD_RE.match(text,j) and not MARKER_RE.match(text,j):j+=1
        out.extend(compress_visible_bytes(encode_ru(text[i:j]),rules));i=j
    b=bytes(out)
    b=b.replace(b'\xF8\xF1\x0A\xFE\xF9',b'\x62')
    b=b.replace(b'\xF8\xF1\x02',b'\x60')
    return b

def patch_live_numeric_markers(raw:bytes,workfile:Path,bpe_path:Path)->tuple[bytes,int]:
    info=read_ines_bytes(raw)
    reg=text_region(info);ptrs=read_pointer_table(reg);rules=load_bpe_rules(bpe_path)
    out=bytearray(raw);base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    patches={}
    for r in parse_work(workfile):
        tr=r.get('tr','')
        if '[GLYPH:$D' not in tr:continue
        old=encode_legacy_numeric_glyphs(tr,rules)
        new=encode_ru_markup_bpe(tr,rules)
        if len(old)!=len(new):
            raise RuntimeError(f'ID {r["id"]}: numeric-glyph codec changed length {len(old)}->{len(new)}')
        p=ptrs[r['id']]
        for off,(a,b) in enumerate(zip(old,new)):
            if a==b:continue
            if not (0xD0<=a<=0xD9 and 0x22<=b<=0x2B):
                raise RuntimeError(f'ID {r["id"]}: unexpected codec difference at +{off}: {a:02X}->{b:02X}')
            addr=p+off
            actual=reg[addr]
            if actual==b:
                continue
            if actual!=a:
                raise RuntimeError(f'ID {r["id"]}: live byte mismatch at text ${addr:04X}: expected {a:02X}, got {actual:02X}')
            if addr in patches and patches[addr]!=b:
                raise RuntimeError(f'conflicting numeric hotfix at text ${addr:04X}')
            patches[addr]=b
    for addr,b in patches.items():out[base+addr]=b
    return bytes(out),len(patches)

def patch_bet_suffix(raw:bytes,bpe_path:Path)->bytes:
    info=read_ines_bytes(raw);reg=text_region(info);ptrs=read_pointer_table(reg);rules=load_bpe_rules(bpe_path)
    targets=[]
    for rid in CARD_BET_IDS:
        blob,ops,ok=parse_stream(reg,ptrs[rid]);
        if not ok:raise RuntimeError(f'ID {rid}: malformed card-bet stream')
        ts=[op.args[0]|(op.args[1]<<8) for op in ops if op.code==0xF2 and len(op.args)==2]
        if len(ts)!=1:raise RuntimeError(f'ID {rid}: expected exactly one F2, got {ts}')
        targets.append(ts[0])
    if len(set(targets))!=1:raise RuntimeError(f'card-bet roots no longer share one suffix: {targets}')
    p=targets[0]
    old=encode_ru_markup_bpe(OLD_BET_SUFFIX,rules)+b'\xFF'
    new=encode_ru_markup_bpe(NEW_BET_SUFFIX,rules)+b'\xFF'
    got,_,ok=parse_stream(reg,p,max_len=max(len(old),len(new))+8)
    if got==new:return raw
    if not ok or got!=old:
        raise RuntimeError(f'card-bet shared suffix at text ${p:04X} unexpected: {got.hex(" ")}')
    if len(new)>len(old):raise RuntimeError('new card-bet suffix does not fit in place')
    out=bytearray(raw);base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    out[base+p:base+p+len(new)]=new
    return bytes(out)


def patch_card_result_layout(raw:bytes,bpe_path:Path)->bytes:
    info=read_ines_bytes(raw);reg=text_region(info);ptrs=read_pointer_table(reg);rules=load_bpe_rules(bpe_path)
    out=bytearray(raw);base=info['prg_offset']+TEXT_BANK_FIRST*PRG_BANK_SIZE
    for rid,text in CARD_RESULT_REPLACEMENTS.items():
        p=ptrs[rid]; old,_,ok=parse_stream(reg,p)
        if not ok: raise RuntimeError(f'ID {rid}: malformed result stream')
        new=encode_ru_markup_bpe(text,rules)+b'\xFF'
        if old==new: continue
        if len(new)>len(old): raise RuntimeError(f'ID {rid}: compact result grew {len(old)}->{len(new)}')
        # No current root/F2 target is permitted inside these two streams; checked by verifier.
        out[base+p:base+p+len(new)]=new
    return bytes(out)

def read_ines_bytes(raw:bytes):
    # small in-memory equivalent of read_ines()
    if len(raw)<16 or raw[:4]!=b'NES\x1a':raise ValueError('Not an iNES ROM')
    trainer=bool(raw[6]&4);off=16+(512 if trainer else 0);prg_size=raw[4]*PRG_BANK_SIZE
    return {'raw':raw,'prg':raw[off:off+prg_size],'prg_offset':off,'prg_banks':raw[4],'chr_banks':raw[5],'mapper':(raw[6]>>4)|(raw[7]&0xF0),'trainer':trainer}

def main():
    ap=argparse.ArgumentParser(description='v0.8.20 -> v0.8.21 hotfix: blackjack RU UI/dynamic numbers + all live legacy D0..D9 glyph markers.')
    ap.add_argument('rom');ap.add_argument('-o','--out',required=True)
    ap.add_argument('--workfile',default=str(ROOT/'project_template/script_work.txt'))
    ap.add_argument('--ru-bpe',default=str(ROOT/'project_template/ru_bpe.tsv'))
    a=ap.parse_args()
    raw=Path(a.rom).read_bytes()
    raw=patch_blackjack(raw)
    raw,n=patch_live_numeric_markers(raw,Path(a.workfile),Path(a.ru_bpe))
    raw=patch_bet_suffix(raw,Path(a.ru_bpe))
    raw=patch_card_result_layout(raw,Path(a.ru_bpe))
    Path(a.out).write_bytes(raw)
    print(f'Patched {n} live legacy D0..D9 numeric marker bytes.')
    print('Patched shared blackjack bet response to "N фиш."')
    print('Compacted blackjack result counters for 3-digit FD safety.')
    print('Wrote:',a.out)
if __name__=='__main__':main()
