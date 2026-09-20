#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate FINAL Murder Club Russian translation data."""
from __future__ import annotations
import csv, re, unicodedata
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def load_tbl(path):
    t2b={}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        a,b=raw.split("=",1)
        a=a.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{2}",a) and b and b!="<END>":
            t2b.setdefault(b,int(a,16))
    return t2b

T2B=load_tbl(ROOT/"murder_club_ru.tbl")
TOKENS=sorted(T2B,key=len,reverse=True)

def encode(text):
    text=unicodedata.normalize("NFC",text).replace("…","...")
    out=bytearray(); i=0
    while i<len(text):
        m=re.match(r"<([0-9A-Fa-f]{2})>",text[i:])
        if m:
            out.append(int(m.group(1),16)); i+=len(m.group(0)); continue
        found=None
        for tok in TOKENS:
            if text.startswith(tok,i):
                found=tok; break
        if found is None:
            raise ValueError(f"cannot encode {text[i]!r}: {text!r}")
        out.append(T2B[found]); i+=len(found)
    return bytes(out)

def dlen(text):
    # Match the proven final builder's wrapping rules.
    n=0; i=0
    while i<len(text):
        if text.startswith("J.B.",i):
            n+=3; i+=4; continue
        m=re.match(r"<([0-9A-Fa-f]{2})>",text[i:])
        if m:
            c=int(m.group(1),16)
            n+=3 if c in (0x05,0x0D) else 1
            i+=len(m.group(0)); continue
        n+=1; i+=1
    return n

def wrap26(text):
    lines=[]; cur=""
    for word in text.split(" "):
        if not cur:
            cur=word
        elif dlen(cur+" "+word)<=26:
            cur+=" "+word
        else:
            lines.append(cur); cur=word
    if cur: lines.append(cur)
    return lines

errors=[]

# Main 1687 rows.
with (ROOT/"translation_ru.tsv").open("r",encoding="utf-8-sig",newline="") as f:
    rows=list(csv.DictReader(f,delimiter="\t"))
if len(rows)!=1687:
    errors.append(f"translation rows={len(rows)}, expected 1687")

for r in rows:
    rid=r["id"]
    try:
        encode(r["translation"])
    except Exception as e:
        errors.append(f"{rid}: {e}")
        continue
    n=int(rid[1:])
    if n<=1650:
        lines=wrap26(r["translation"])
        if len(lines)>4 or any(dlen(x)>26 for x in lines):
            errors.append(f"{rid}: exceeds 26x4 -> {lines}")
    elif dlen(r["translation"])>10:
        errors.append(f"{rid}: menu label >10 cells")

# Supplemental.
with (ROOT/"supplemental_text_ru.tsv").open("r",encoding="utf-8-sig",newline="") as f:
    supp=list(csv.DictReader(f,delimiter="\t"))
for i,r in enumerate(supp,1):
    try:
        encode(r["translation"])
    except Exception as e:
        errors.append(f"supp#{i}: {e}")

# Static UI.
with (ROOT/"static_ui_ru.tsv").open("r",encoding="utf-8-sig",newline="") as f:
    static=list(csv.DictReader(f,delimiter="\t"))
for i,r in enumerate(static,1):
    try:
        b=encode(r["translation"])
    except Exception as e:
        errors.append(f"static#{i}: {e}")
        continue
    lim=int(r["display_limit"])
    if len(r["translation"])>lim:
        errors.append(f"static#{i}: >{lim} chars")
    if (r.get("frame_mode") or "")=="after10_fd_if_room" and len(b)>10:
        errors.append(f"static#{i}: framed label >10 bytes")

# Direct ending copies.
with (ROOT/"direct_ending_ru.tsv").open("r",encoding="utf-8-sig",newline="") as f:
    direct=list(csv.DictReader(f,delimiter="\t"))
for r in direct:
    b=encode(r["translation"])
    if len(b)>int(r["capacity"]):
        errors.append(f"direct ending {r['id']}: overflow")

# Actual fixed inline epilogue.
with (ROOT/"inline_ending_ru.tsv").open("r",encoding="utf-8-sig",newline="") as f:
    inline=list(csv.DictReader(f,delimiter="\t"))
if len(inline)!=1:
    errors.append(f"inline ending records={len(inline)}, expected 1")
else:
    b=encode(inline[0]["translation"])
    if len(b)>int(inline[0]["capacity"]):
        errors.append("inline ending overflow")

print(f"main rows: {len(rows)}")
print(f"supplemental rows: {len(supp)}")
print(f"static UI rows: {len(static)}")
print(f"errors: {len(errors)}")
for e in errors:
    print(" -",e)
raise SystemExit(1 if errors else 0)
