#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from workfile import parse_work
MARK=re.compile(r'\[([^\[\]\n]+)\]')
SYSTEM_SPEED_IDS={5,6,7}
SYSTEM_PAGE='[F1:$0A][FE][F9]'
FC={0x07:7,0x15:9,0x4E:4,0x5C:7,0x63:7}
class S:
 def __init__(self,x=3,line=1,page=1):self.x=x;self.line=line;self.page=page

def sim(text,shared,st=None,stack=(),label='',max_x=30,max_lines=3):
 st=st or S();bad=[];i=0
 def draw(width,item):
  if st.line>max_lines:bad.append((label,st.page,st.line,st.x,width,item,'BOTTOM_ROW'))
  if st.x+width>max_x:bad.append((label,st.page,st.line,st.x,width,item,'RIGHT_OVERSCAN'))
  st.x+=width
 while i<len(text):
  if text[i]=='\n':st.x=3;st.line+=1;i+=1;continue
  m=MARK.match(text,i)
  if m:
   u=m.group(1).upper()
   if u.startswith('F1:$'):st.x+=int(u.split('$')[1],16)
   elif u=='F9':st.x=3;st.line=1;st.page+=1
   elif u.startswith('FC:$'):draw(FC.get(int(u.split('$')[1],16),9),m.group())
   elif u.startswith(('GLYPH:$','FB:$')):draw(1,m.group())
   elif u.startswith('FD:$'):draw(3,m.group())
   elif u.startswith('F2:$'):
    p=int(u.split('$')[1],16)
    if p in stack:raise ValueError(f'F2 cycle ${p:04X}')
    if p not in shared:bad.append((label,st.page,st.line,st.x,0,f'MISSING [F2:${p:04X}]','MISSING_F2'))
    else:bad.extend(sim(shared[p],shared,st,stack+(p,),f'SHARED ${p:04X} via {label}',max_x,max_lines))
   i=m.end();continue
  draw(1,repr(text[i]));i+=1
 return bad

def main():
 ap=argparse.ArgumentParser(description='Strict Okhotsk dialogue safe-area verifier.')
 ap.add_argument('workfile');ap.add_argument('--shared-translations',required=True)
 ap.add_argument('--max-x',type=int,default=30,help='exclusive right edge; default 30 leaves tiles 30-31 unused')
 ap.add_argument('--max-lines',type=int,default=3,help='maximum drawable rows per page')
 a=ap.parse_args()
 d=json.loads(Path(a.shared_translations).read_text(encoding='utf-8-sig'));shared={int(k,16):v for k,v in d.items()}
 bad=[];n=0
 for r in parse_work(a.workfile):
  tr=r.get('tr','')
  if not tr or 17<=r['id']<=226:continue
  n+=1
  if r['id'] in SYSTEM_SPEED_IDS:
   if SYSTEM_PAGE in tr:
    bad.append((f'ID {r["id"]:04d}',1,1,0,0,'PAGE inside speed prompt','SYSTEM_PROMPT_PAGEBREAK'))
   if 'Скорость текста?' not in tr:
    bad.append((f'ID {r["id"]:04d}',1,1,0,0,'missing compact speed prompt','SYSTEM_PROMPT_TEXT'))
  bad+=sim(tr,shared,label=f'ID {r["id"]:04d}',max_x=a.max_x,max_lines=a.max_lines)
 # Standalone check from a clean page catches shared streams not reached in current root paths too.
 for p,tr in sorted(shared.items()):bad+=sim(tr,shared,stack=(p,),label=f'SHARED ${p:04X}',max_x=a.max_x,max_lines=a.max_lines)
 if bad:
  print(f'Layout FAIL: {len(bad)} safe-area/missing-F2 issues (X < {a.max_x}, rows <= {a.max_lines}).')
  for x in bad[:150]:print(f'  {x[0]} page {x[1]} line {x[2]} X={x[3]} width={x[4]} item={x[5]} reason={x[6]}')
  raise SystemExit(2)
 print(f'Layout OK: {n} dialogue roots + {len(shared)} shared streams; X < {a.max_x}; max {a.max_lines} drawable rows; 0 issues.')
if __name__=='__main__':main()
