#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the FINAL Russian Murder Club Famicom ROM.

This builder relocates the four sequential dialogue pools to new MMC3 PRG banks.
It does NOT force Russian text into the original Japanese byte capacities.
Main dialogue UI is word-wrapped to 26 columns x 4 lines.
Menu strings are limited to 10 visible characters.

The user's redrawn Russian main font is embedded automatically by default.
Use --no-font only when a text/UI-only build is needed.
"""
from __future__ import annotations
import argparse, csv, hashlib, re, unicodedata
from pathlib import Path

EXPECTED_SHA1='bb1fb4700ad1cf83bd32acb640747f2a9d337238'
OLD_PRG_SIZE=0x20000
NEW_PRG_SIZE=0x40000
BANK=0x2000
# group: original start, original terminal boundary, boundary inclusive?, new start bank
GROUPS=[
    (0x4000,0x6D60,True,0x10),
    (0x6D60,0x9A70,True,0x12),
    (0x9A70,0xC810,True,0x14),
    (0xC810,0xEF20,False,0x16),
]
BASE_TABLE_OFF=0x1C259
MENU_BASE=0x1C3BC
MENU_END=0x1C509
LOW_TEXT=set(range(0x05,0x0E))

def load_tbl(path):
    b2t={}; t2b={}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        if not raw or raw.lstrip().startswith('#') or '=' not in raw: continue
        left,right=raw.split('=',1); left=left.strip()
        if re.fullmatch(r'[0-9A-Fa-f]{2}',left):
            b=int(left,16); b2t[b]=right
            if right and right!='<END>': t2b.setdefault(right,b)
    return b2t,t2b

def decode_jp(data,b2t):
    s=''.join(b2t.get(b,f'<{b:02X}>') for b in data)
    return unicodedata.normalize('NFC',s.replace('゛','\u3099').replace('゜','\u309A'))

def make_encoder(t2b):
    toks=sorted(t2b,key=len,reverse=True)
    def enc(text):
        text=unicodedata.normalize('NFC',text).replace('…','...')
        out=bytearray(); i=0
        while i<len(text):
            m=re.match(r'<([0-9A-Fa-f]{2})>',text[i:])
            if m:
                out.append(int(m.group(1),16)); i+=len(m.group(0)); continue
            found=None
            for tok in toks:
                if text.startswith(tok,i): found=tok; break
            if found is None: raise ValueError(f'Cannot encode {text[i]!r}: {text!r}')
            out.append(t2b[found]); i+=len(found)
        return bytes(out)
    return enc

def dlen(text):
    n=0; i=0
    while i<len(text):
        if text.startswith('J.B.',i): n+=3; i+=4; continue
        m=re.match(r'<([0-9A-Fa-f]{2})>',text[i:])
        if m:
            c=int(m.group(1),16); n += 3 if c in (0x05,0x0D) else 1; i+=len(m.group(0)); continue
        n+=1; i+=1
    return n

def wrap26(text,width=26,max_lines=4):
    words=text.split(' '); lines=[]; cur=''
    for w in words:
        if not cur:
            if dlen(w)>width: raise ValueError(f'Word >{width}: {w!r}')
            cur=w
        elif dlen(cur+' '+w)<=width: cur+=' '+w
        else: lines.append(cur); cur=w
    if cur or not lines: lines.append(cur)
    if len(lines)>max_lines: raise ValueError(f'Text needs {len(lines)} lines: {text!r}')
    packed=''
    for i,line in enumerate(lines):
        packed+=line
        if i<len(lines)-1: packed+=' '*(width-dlen(line))
    return packed,lines

def read_translation(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f,delimiter='\t'))
    by_off={}; by_id={}
    for r in rows:
        if not r.get('translation'): continue
        by_id[r['id']]=r
        n=int(r['id'][1:])
        if n<=1650: by_off[int(r['prg_offset'],16)]=r
    for i in range(1,1688):
        if f'D{i:04d}' not in by_id: raise SystemExit(f'Missing translation D{i:04d}')
    return rows,by_off,by_id

def read_supp(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        return {r['original_japanese']:r['translation'] for r in csv.DictReader(f,delimiter='\t')}

def serialize_group(prg,start,end,inclusive,by_off,supp,jp_b2t,enc):
    end_ex=end+1 if inclusive else end
    pos=start; out=bytearray(); segs=0
    while pos<end_ex:
        z=prg.find(b'\x00',pos,end_ex)
        if z<0: raise RuntimeError(f'No terminator in group at {pos:05X}')
        raw=prg[pos:z]
        if pos in by_off:
            packed,_=wrap26(by_off[pos]['translation'])
            out += enc(packed)+b'\x00'
        elif raw and all((b>=0x80 or b in LOW_TEXT) for b in raw):
            jp=decode_jp(raw,jp_b2t)
            if jp not in supp: raise RuntimeError(f'Untranslated supplemental text at ${pos:05X}: {jp}')
            packed,_=wrap26(supp[jp])
            out += enc(packed)+b'\x00'
        else:
            out += raw+b'\x00'
        segs+=1; pos=z+1
    return bytes(out),segs


def read_direct_ending(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def patch_direct_ending(prg, rows, enc):
    patched=0
    for r in rows:
        off=int(r["prg_offset"],16)
        cap=int(r["capacity"])
        text=r["translation"]
        data=enc(text)

        if len(data)>cap:
            raise SystemExit(
                f"Direct ending {r['id']} too large: "
                f"{len(data)}>{cap} bytes: {text}"
            )

        # The ending routine uses these original addresses directly.
        # Keep the original terminator exactly where it was and fill unused
        # payload bytes with normal text spaces.
        if prg[off+cap] != 0x00:
            raise SystemExit(
                f"Direct ending terminator mismatch at ${off+cap:05X}"
            )

        prg[off:off+cap]=data+bytes([0xFF])*(cap-len(data))
        patched+=1

    print(f"direct ending: patched {patched} original-address records")
    return patched


def read_static_ui(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def patch_static_ui(prg, rows, enc):
    count=0
    framed=0
    fd_written=0

    for r in rows:
        off=int(r["prg_offset"],16)
        cap=int(r["capacity"])
        lim=int(r["display_limit"])
        text=r["translation"]
        data=enc(text)
        framed_row=(r.get("frame_mode") or "")=="after10_fd_if_room"

        if len(text)>lim:
            raise SystemExit(
                f"Static UI {r['prg_offset']} >{lim} chars: {text}"
            )

        if framed_row:
            # Critical structural rule:
            # DO NOT move the original 00 terminator. Menu option indexing
            # walks the original zero-terminated table sequentially.
            #
            # Visible geometry established by in-game testing:
            #   cells 1..10 = label
            #   cell 11     = right-frame tile
            #
            # Japanese records can have >10 BYTES because dakuten takes an
            # extra byte without taking an extra visible cell.
            #
            # So:
            #   - write exactly 10 visible label cells;
            #   - if the original record has byte room beyond those 10 cells,
            #     put $FD in byte/cell 11;
            #   - leave any still-extra bytes after $FD as blanks;
            #   - keep the ORIGINAL terminator at off+cap untouched.
            #
            # This combines v10's correct option indexing with the correctly
            # positioned frame edge.
            if cap < 10:
                raise SystemExit(
                    f"Framed record shorter than 10 bytes at ${off:05X}"
                )
            if len(data)>10:
                raise SystemExit(
                    f"Framed label encodes to {len(data)}>10 bytes "
                    f"at ${off:05X}: {text}"
                )

            field=data+bytes([0xFF])*(10-len(data))
            prg[off:off+10]=field

            # Clear only bytes that belong to the old string payload.
            # Never insert an early 00.
            if cap>10:
                prg[off+10:off+cap]=bytes([0xFF])*(cap-10)
                prg[off+10]=0xFD
                fd_written+=1

            if prg[off+cap] != 0x00:
                raise SystemExit(
                    f"Original UI terminator moved/corrupted at ${off+cap:05X}"
                )

            framed+=1
        else:
            if len(data)>cap:
                raise SystemExit(
                    f"Static UI {r['prg_offset']} "
                    f"{len(data)}>{cap} bytes: {text}"
                )

            prg[off:off+cap]=data+bytes([0xFF])*(cap-len(data))
            if prg[off+cap] != 0x00:
                raise SystemExit(
                    f"Static UI terminator mismatch at ${off+cap:05X}"
                )

        count+=1

    print(
        f"framed compact rows: {framed}; "
        f"$FD explicitly placed in cell 11 for {fd_written} variable-byte rows; "
        "all original 00 terminators preserved"
    )
    return count


def remove_ten_points_suffix(prg):
    expected={
        0x2562:0xA9,0x2563:0x92,
        0x2568:0xA9,0x2569:0xAD,
        0x256E:0xA9,0x256F:0x00,
    }
    for off,val in expected.items():
        if prg[off] != val:
            raise SystemExit(
                f"Unexpected score suffix code at ${off:05X}: "
                f"{prg[off]:02X}!={val:02X}"
            )

    prg[0x2563]=0x00
    prg[0x2569]=0x00
    print("score suffix: removed hardcoded てん")



def read_inline_ending(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f,delimiter="\t"))
    if len(rows)!=1:
        raise SystemExit(
            f"Expected exactly one inline-ending record, got {len(rows)}"
        )
    return rows[0]

def patch_inline_final_epilogue(prg, row, enc):
    # ACTUAL ending cutscene text: fixed inline block in PRG data.
    # It is separate from the normal relocated dialogue pool.
    off=int(row["prg_offset"],16)
    cap=int(row["capacity"])
    text=row["translation"]
    data=enc(text)

    if len(data)>cap:
        raise SystemExit(
            f"Inline final epilogue too large: {len(data)}>{cap}"
        )

    # Fixed-size block; no 00 separator between the two original paragraphs.
    prg[off:off+cap]=data+bytes([0xFF])*(cap-len(data))
    print(
        f"inline final epilogue: patched fixed block "
        f"${off:05X}, {len(data)}/{cap} bytes"
    )
    return len(data)


RGB_TO_VALUE={(255,255,255):0,(170,170,170):1,(85,85,85):2,(0,0,0):3}

def png_font_to_chr(path):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow required for --font: pip install pillow")
    img=Image.open(path).convert("RGB")
    if img.size!=(128,64):
        raise SystemExit(f"Russian font must be exactly 128x64, got {img.size}")
    bad=set()
    for y in range(img.height):
        for x in range(img.width):
            if img.getpixel((x,y)) not in RGB_TO_VALUE:
                bad.add(img.getpixel((x,y)))
    if bad:
        raise SystemExit(f"Russian font has unsupported colors: {sorted(bad)[:8]}")
    out=bytearray()
    for ty in range(8):
        for tx in range(16):
            p0s=[]; p1s=[]
            for y in range(8):
                p0=p1=0
                for x in range(8):
                    val=RGB_TO_VALUE[img.getpixel((tx*8+x,ty*8+y))]
                    bit=7-x
                    p0|=(val&1)<<bit
                    p1|=((val>>1)&1)<<bit
                p0s.append(p0); p1s.append(p1)
            out.extend(p0s); out.extend(p1s)
    return bytes(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('rom',type=Path)
    ap.add_argument('-t','--translation',type=Path,default=Path(__file__).with_name('translation_ru.tsv'))
    ap.add_argument('--supplemental',type=Path,default=Path(__file__).with_name('supplemental_text_ru.tsv'))
    ap.add_argument('--jp-table',type=Path,default=Path(__file__).with_name('murder_club_jp.tbl'))
    ap.add_argument('--ru-table',type=Path,default=Path(__file__).with_name('murder_club_ru.tbl'))
    ap.add_argument('--static-ui',type=Path,default=Path(__file__).with_name('static_ui_ru.tsv'))
    ap.add_argument('--direct-ending',type=Path,default=Path(__file__).with_name('direct_ending_ru.tsv'))
    ap.add_argument('--inline-ending',type=Path,default=Path(__file__).with_name('inline_ending_ru.tsv'))
    ap.add_argument('--font',type=Path,default=Path(__file__).with_name('font_direct_80_FF_RU.png'))
    ap.add_argument('--no-font',action='store_true',help='build translated text/UI but leave original CHR font')
    ap.add_argument('-o','--output',type=Path,required=True)
    ap.add_argument('--force-rom',action='store_true')
    args=ap.parse_args()

    src=args.rom.read_bytes()
    if len(src)<16 or src[:4]!=b'NES\x1a': raise SystemExit('Not an iNES ROM')
    sha=hashlib.sha1(src).hexdigest()
    if sha!=EXPECTED_SHA1 and not args.force_rom:
        raise SystemExit(f'Expected original ROM SHA1 {EXPECTED_SHA1}, got {sha}')
    old_prg_units=src[4]
    old_prg_size=old_prg_units*16384
    if old_prg_size!=OLD_PRG_SIZE: raise SystemExit(f'Expected 128 KiB PRG, got {old_prg_size}')
    chr_size=src[5]*8192
    prg=bytearray(src[16:16+old_prg_size])
    chr_data=src[16+old_prg_size:16+old_prg_size+chr_size]
    if len(chr_data)!=chr_size: raise SystemExit('Truncated CHR')

    jp_b2t,_=load_tbl(args.jp_table); _,ru_t2b=load_tbl(args.ru_table); enc=make_encoder(ru_t2b)
    rows,by_off,by_id=read_translation(args.translation); supp=read_supp(args.supplemental)
    static_rows=read_static_ui(args.static_ui)
    direct_rows=read_direct_ending(args.direct_ending)
    inline_row=read_inline_ending(args.inline_ending)
    static_count=patch_static_ui(prg,static_rows,enc)
    print(f'static UI: patched {static_count} records')
    direct_count=patch_direct_ending(prg,direct_rows,enc)
    inline_ending_size=patch_inline_final_epilogue(prg,inline_row,enc)
    remove_ten_points_suffix(prg)

    group_blobs=[]
    for gi,(start,end,inc,newbank) in enumerate(GROUPS):
        blob,segs=serialize_group(bytes(prg),start,end,inc,by_off,supp,jp_b2t,enc)
        if len(blob)>2*BANK: raise SystemExit(f'Group {gi} too large: {len(blob)} > 16384')
        group_blobs.append(blob)
        print(f'group {gi}: {len(blob)} bytes, {segs} records -> banks {newbank:02X}-{newbank+1:02X}')

    # Repack menu pool at the same fixed-bank base. Code indexes it by zero-terminated string number.
    menu=bytearray(b'\x00')
    for i in range(1651,1688):
        rid=f'D{i:04d}'; text=by_id[rid]['translation']
        if dlen(text)>10: raise SystemExit(f'{rid} menu label >10 cells: {text}')
        menu += enc(text)+b'\x00'
    menu_cap=MENU_END-MENU_BASE
    if len(menu)>menu_cap: raise SystemExit(f'Menu pool too large: {len(menu)} > {menu_cap}')
    prg[MENU_BASE:MENU_END]=menu+b'\x00'*(menu_cap-len(menu))

    # Patch four source-base triples in original bank 14.
    triples=bytearray()
    for _,_,_,bank in GROUPS: triples += bytes([bank,0x00,0x80])
    prg[BASE_TABLE_OFF:BASE_TABLE_OFF+12]=triples

    # 32 x 8K PRG banks = 256 KiB. Preserve original banks 0-15,
    # use 16-23 for relocated text, leave 24-29 empty,
    # duplicate modified fixed bank 14 to bank 30 and original fixed bank 15 to bank 31.
    newprg=bytearray(b'\x00'*NEW_PRG_SIZE)
    newprg[:OLD_PRG_SIZE]=prg
    for blob,(_,_,_,bank) in zip(group_blobs,GROUPS):
        off=bank*BANK; newprg[off:off+len(blob)]=blob
    bank14=bytes(prg[14*BANK:15*BANK]); bank15=bytes(prg[15*BANK:16*BANK])
    newprg[30*BANK:31*BANK]=bank14
    newprg[31*BANK:32*BANK]=bank15

    if not args.no_font:
        font_chr=png_font_to_chr(args.font)
        chr_data=bytearray(chr_data)
        chr_data[:0x800]=font_chr
        chr_data=bytes(chr_data)
        print(f'font: inserted {args.font.name} into main text tiles')

    hdr=bytearray(src[:16]); hdr[4]=16  # 16 x 16 KiB = 256 KiB PRG
    out=bytes(hdr)+bytes(newprg)+bytes(chr_data)
    args.output.write_bytes(out)
    print(f'menu pool: {len(menu)}/{menu_cap} bytes')
    print(f'output: {args.output}')
    print(f'PRG: {OLD_PRG_SIZE//1024} KiB -> {NEW_PRG_SIZE//1024} KiB; CHR unchanged')
    print('Russian main font is embedded unless --no-font was used')

if __name__=='__main__': main()
