from __future__ import annotations
from pathlib import Path
import json,re,sys,shutil

MARK=re.compile(r'\[([^\[\]\n]+)\]')
FC={0x07:7,0x15:9,0x4E:4,0x5C:7,0x63:7}
SOFT='\n[F1:$02]'
PAGE='[F1:$0A][FE][F9]'
SAFE_X=30       # tiles 30-31 are reserved as right-side overscan safety margin
MAX_LINES=3     # fourth/bottom dialogue row is outside the reliable visible/cleared area

# These roots immediately hand control to the special BЫС/НОР/МЕД speed menu.
# A generic PAGE marker ([F1:$0A][FE][F9]) inside the prompt ends the message and
# makes the remaining text draw over the system menu, corrupting the screen.
SYSTEM_ROOT_OVERRIDES={
    5:'Куроки:[F3],верно?\n[F1:$02]Скорость текста?',
    6:'Куроки:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
    7:'Сюн:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
}

class State:
    def __init__(self,x=3,line=1,page=1): self.x=x;self.line=line;self.page=page

def _draw_overflow(st:State,width:int):
    if st.line>MAX_LINES:
        return 'line'
    if st.x+width>SAFE_X:
        return 'x'
    return None

def sim_once(s:str, shared:dict[int,str], st:State|None=None, stack=()):
    if st is None: st=State()
    candidates=[];i=0;line_start=0;line_break=None
    while i<len(s):
        if s[i]=='\n':
            st.x=3;st.line+=1;line_break=i;i+=1;line_start=i;candidates=[];continue
        m=MARK.match(s,i)
        if m:
            body=m.group(1); up=body.upper(); start=i
            if up.startswith('F1:$'):
                st.x += int(up.split('$')[1],16)
            elif up=='F9':
                st.x=3;st.line=1;st.page+=1;candidates=[];line_start=m.end();line_break=None
            elif up.startswith('FC:$'):
                n=FC.get(int(up.split('$')[1],16),9)
                why=_draw_overflow(st,n)
                if why:
                    return {'reason':why,'pos':start,'candidate':candidates[-1] if candidates else None,
                            'kind':'local','state':(st.x,st.line,st.page),'thing':m.group(),
                            'line_start':line_start,'line_break':line_break}
                st.x+=n
            elif up.startswith(('GLYPH:$','FB:$','FD:$')):
                width=3 if up.startswith('FD:$') else 1
                why=_draw_overflow(st,width)
                if why:
                    return {'reason':why,'pos':start,'candidate':candidates[-1] if candidates else None,
                            'kind':'local','state':(st.x,st.line,st.page),'thing':m.group(),
                            'line_start':line_start,'line_break':line_break}
                st.x+=width
            elif up.startswith('F2:$'):
                p=int(up.split('$')[1],16)
                if p in stack: raise RuntimeError(f'F2 cycle ${p:04X}')
                t=shared.get(p)
                if t is not None:
                    before=(st.line,st.page)
                    ov=sim_once(t,shared,st,stack+(p,))
                    if ov:
                        return {'reason':ov.get('reason'),'pos':start,'candidate':candidates[-1] if candidates else None,
                                'kind':'nested','target':p,'nested':ov,'state':ov.get('state'),
                                'thing':m.group(),'line_start':line_start,'line_break':line_break}
                    if (st.line,st.page)!=before:
                        candidates=[];line_start=m.end();line_break=None
            i=m.end();continue
        # literal visible glyph
        why=_draw_overflow(st,1)
        if why:
            return {'reason':why,'pos':i,'candidate':candidates[-1] if candidates else None,
                    'kind':'local','state':(st.x,st.line,st.page),'thing':repr(s[i]),
                    'line_start':line_start,'line_break':line_break}
        if s[i]==' ': candidates.append(i)
        st.x+=1;i+=1
    return None

def wrap_overflowing(s:str,shared:dict[int,str],normalize_soft=True,max_iter=1000):
    if not sim_once(s,shared): return s,0,0
    if normalize_soft: s=s.replace(SOFT,' ')
    wraps=pages=0
    for _ in range(max_iter):
        ov=sim_once(s,shared)
        if not ov:return s,wraps,pages
        reason=ov.get('reason')
        pos=ov['pos'];ls=ov.get('line_start',0)
        if reason=='line':
            if ov['kind']=='nested':
                # Shared expansion would draw on the forbidden fourth row in this caller.
                # Start the shared fragment on a fresh page; shared streams are independently
                # normalized to <=3 rows when entered on a clean page.
                s=s[:pos]+PAGE+s[pos:];pages+=1;continue
            bp=ov.get('line_break')
            if bp is not None:
                s=s[:bp]+PAGE+s[bp+1:];pages+=1;continue
            raise RuntimeError(f"cannot page-split {ov}; near {s[max(0,pos-60):pos+100]!r}")
        # horizontal overflow
        bp=ov.get('candidate')
        if bp is not None:
            s=s[:bp]+SOFT+s[bp+1:];wraps+=1;continue
        if ov['kind']=='nested' and pos>ls:
            s=s[:pos]+SOFT+s[pos:];wraps+=1;continue
        # Rare very long unbroken token/word. Prefer a hard continuation to corrupting
        # the right overscan area; Russian text currently should almost never hit this.
        if ov['kind']=='local' and pos>ls:
            s=s[:pos]+SOFT+s[pos:];wraps+=1;continue
        raise RuntimeError(f"cannot wrap {ov}; near {s[max(0,pos-60):pos+100]!r}")
    raise RuntimeError('too many wrap iterations')

def compress_punctuation_spaces(s:str)->tuple[str,int]:
    # Engine typography rule for this translation: a blank after punctuation is optional
    # and costs one full 8px tile. Remove only literal spaces, never control-code spacing.
    ns,n=re.subn(r'([\.,:\?!]) +',r'\1',s)
    return ns,n

def reflow_source(s:str,shared:dict[int,str]):
    ns,n,p=wrap_overflowing(s,shared,normalize_soft=True)
    ns,removed=compress_punctuation_spaces(ns)
    # Compression cannot make a line wider, but shared context may have changed while
    # processing the graph; verify and repair once more without expanding soft lines.
    for _ in range(100):
        ov=sim_once(ns,shared)
        if not ov: break
        ns,n2,p2=wrap_overflowing(ns,shared,normalize_soft=False,max_iter=100)
        n+=n2;p+=p2
        ns,r2=compress_punctuation_spaces(ns);removed+=r2
    ov=sim_once(ns,shared)
    if ov: raise RuntimeError(f'overflow remains: {ov}')
    return ns,n,p,removed

def replace_tr_blocks(text:str,new_by_id:dict[int,str]):
    lines=text.splitlines();out=[];i=0;curid=None
    head_re=re.compile(r'^@@\s+.*?ID=(\d+)')
    while i<len(lines):
        m=head_re.match(lines[i])
        if m:curid=int(m.group(1))
        if lines[i]=='TR_BEGIN' and curid in new_by_id:
            out.append(lines[i]);out.extend(new_by_id[curid].split('\n'));i+=1
            while i<len(lines) and lines[i]!='TR_END':i+=1
            if i>=len(lines):raise RuntimeError('unterminated TR')
            out.append('TR_END');i+=1;continue
        out.append(lines[i]);i+=1
    return '\n'.join(out)+'\n'

def strict_verify(recs,shared):
    bad=[]
    for r in recs:
        tr=r.get('tr','')
        if not tr or 17<=r['id']<=226:continue
        ov=sim_once(tr,shared)
        if ov:bad.append((f'ID {r["id"]:04d}',ov))
    for p,s in sorted(shared.items()):
        ov=sim_once(s,shared,stack=(p,))
        if ov:bad.append((f'SHARED {p:04X}',ov))
    if bad: raise RuntimeError(f'strict layout failures {len(bad)} sample {bad[:10]}')

def main(srcroot:Path,outroot:Path):
    shutil.copytree(srcroot,outroot,dirs_exist_ok=True)
    sys.path.insert(0,str(outroot/'tools'))
    from workfile import parse_work

    wf=outroot/'project_template/script_work.txt'
    recs=parse_work(wf)
    shfile=outroot/'project_template/shared_translations_full.json'
    allfile=outroot/'project_template/shared_translations_all.json'
    shared_raw=json.loads(shfile.read_text(encoding='utf-8-sig'))
    shared_all=json.loads(allfile.read_text(encoding='utf-8-sig'))

    # Promote every F2 target referenced by Russian payload. Missing translations are fatal.
    need=set()
    for r in recs:
        rid=r['id'];tr=r.get('tr','')
        if not tr or 17<=rid<=226:continue
        need.update(x.upper() for x in re.findall(r'\[F2:\$([0-9A-Fa-f]{4})\]',tr))
    queue=list(need)
    while queue:
        key=queue.pop()
        if key not in shared_raw:
            if key not in shared_all:raise RuntimeError(f'Russian TR references untranslated shared F2 ${key}')
            shared_raw[key]=shared_all[key]
        for child in re.findall(r'\[F2:\$([0-9A-Fa-f]{4})\]',shared_raw[key]):
            child=child.upper()
            if child not in need:need.add(child);queue.append(child)

    shared={int(k,16):v for k,v in shared_raw.items()}
    sh_changes={};wraps=pages=punct=0

    # Iterate shared graph to a fixed point because caller/context-sensitive limits can
    # expose a nested stream only after its child has been repaged.
    for _pass in range(20):
        changed=False
        for p in sorted(shared):
            old=shared[p]
            # For a standalone stream, recursive nested calls are meaningful too.
            ctx=dict(shared)
            # Avoid treating a direct self entry as legal recursion.
            try:
                new,n,k,r=reflow_source(old,ctx)
            except RuntimeError as e:
                if 'F2 cycle' in str(e):
                    # The game's real graph is acyclic for translated reachable streams;
                    # re-raise any unexpected cycle rather than hiding it.
                    raise
                raise
            if new!=old:
                sh_changes.setdefault(p,(old,new));shared[p]=new;wraps+=n;pages+=k;punct+=r;changed=True
        if not changed:break
    else:raise RuntimeError('shared reflow did not converge')

    new_by_id={};root_stats=[]
    # Root reflow can affect shared context only through page placement, not shared bytes,
    # so one pass plus exact verification is sufficient.
    for r in recs:
        rid=r['id'];tr=r.get('tr','')
        if not tr or 17<=rid<=226:continue
        if rid in SYSTEM_ROOT_OVERRIDES:
            ns=SYSTEM_ROOT_OVERRIDES[rid]; n=k=rm=0
            ov=sim_once(ns,shared)
            if ov: raise RuntimeError(f'system speed prompt ID {rid} is not layout-safe: {ov}')
        else:
            ns,n,k,rm=reflow_source(tr,shared)
        if ns!=tr:
            new_by_id[rid]=ns;root_stats.append((rid,n,k,rm,tr,ns));wraps+=n;pages+=k;punct+=rm
    wf.write_text(replace_tr_blocks(wf.read_text(encoding='utf-8-sig'),new_by_id),encoding='utf-8-sig')

    # Write translated shared maps.
    def write_shared(path):
        d=json.loads(path.read_text(encoding='utf-8-sig'))
        for p,v in shared.items():d[f'{p:04X}']=v
        path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8-sig')
    write_shared(shfile);write_shared(allfile)

    recs2=parse_work(wf)
    strict_verify(recs2,shared)

    report=outroot/'docs/TEXT_REFLOW_V0819_RU.txt'
    with report.open('w',encoding='utf-8-sig') as f:
        f.write('Okhotsk RU v0.8.19 — безопасная зона диалогового окна\n')
        f.write('='*72+'\n\n')
        f.write('Правила QA после проверки save-state:\n')
        f.write('- максимум 3 видимые строки на одной странице; 4-я/нижняя не используется;\n')
        f.write('- любой рисуемый глиф должен завершаться до X=30 (X=30..31 оставлены запасом);\n')
        f.write('- пробелы после . , : ? ! удаляются для экономии одного тайла;\n')
        f.write('- F2-потоки проверяются рекурсивно в контексте вызывающей реплики.\n\n')
        f.write(f'Изменено корневых записей относительно v0.8.18: {len(root_stats)}\n')
        f.write(f'Изменено shared-потоков: {len(sh_changes)}\n')
        f.write(f'Добавлено мягких переносов: {wraps}\n')
        f.write(f'Добавлено новых страниц: {pages}\n')
        f.write(f'Удалено пробелов после пунктуации: {punct}\n')
        f.write(f'Итог: X < {SAFE_X}, максимум {MAX_LINES} строки, ошибок 0.\n\n')
        for rid,n,k,rm,old,new in root_stats:
            f.write(f'--- ID {rid:04d} (wrap {n}, pages {k}, punctuation spaces {rm}) ---\n')
            f.write('БЫЛО:\n'+old+'\n\nСТАЛО:\n'+new+'\n\n')
        if sh_changes:
            f.write('\nSHARED STREAMS\n'+'-'*72+'\n')
            for p,(old,new) in sorted(sh_changes.items()):
                f.write(f'${p:04X}\nБЫЛО:\n{old}\nСТАЛО:\n{new}\n\n')
    print('SAFE_X',SAFE_X,'MAX_LINES',MAX_LINES)
    print('root changed',len(root_stats),'shared changed',len(sh_changes),'wraps',wraps,'pages',pages,'punct spaces removed',punct)
    print('report',report)

if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('usage: reflow_dialogue_ru.py srcroot outroot')
    main(Path(sys.argv[1]),Path(sys.argv[2]))
