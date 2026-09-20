#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import read_ines,text_region,read_pointer_table
from stream_codec import parse_stream,collect_f2_graph,stream_refs_f2
from ru_bpe import load_bpe_rules,encode_ru_markup_bpe
from repack_pool import extra_dictionary_blob_len
from ru_dictionary import EXTRA_DICT_START
from font_extract import STREAM_PRG_OFF,ALLOC_END_PRG_OFF,OUT_SIZE
from rle_packbits import decode
from patch_static_ui_ru import (RU_NAME, RU_MEMO, RU_SPEED, RU_NAV,
    NAME_PROMPT_PRG, MEMO_PROMPT_PRG, SPEED_TABLE_PRG, NAV_TABLE_PRG,
    NAME_DAKUTEN_PRG, MEMO_DAKUTEN_PRG, POPUP_DAKUTEN_CLEANUP,
    INPUT_COMPOSITOR_PRG, INPUT_COMPOSITOR_RU, INPUT_TOP_TRIPLET_PRG, INPUT_TOP_TRIPLET_RU,
    INPUT_NAME_EXTRA_PRG, INPUT_NAME_EXTRA_RU,
    decode_popup_from_raw, POPUP_LINE1, POPUP_LINE2, POPUP_LINE1_TILES, POPUP_LINE2_TILES)
from patch_phone_names_ru import RU_TABLE as PHONE_RU_TABLE, PHONE_TABLE_PRG, RU_NAMES as PHONE_RU_NAMES
from patch_title_credits_ru import (TITLE_FIELDS, CREDIT_FIELDS, TITLE_DESC_PRG, TITLE_DATA_PRG, TITLE_DESC_NEW, decode_localized_title_field,
    decode_localized_credit_field, _decode_font_resource, RU_TO_RAW,
    INTRO_LOGIN_DESC_PRG, INTRO_LOGIN_DESC, INTRO_LOGIN_DATA_PRG, INTRO_LOGIN_WIDTH, INTRO_LOGIN_RU,
    SCENE_ATTR_TABLE_PRG, SCENE_ATTR_TABLE_ORIG,
    INTRO_MYSTERY_DATA_PRG, INTRO_MYSTERY_WIDTH, INTRO_MYSTERY_RU)
from patch_blackjack_ru import (BLACKJACK_OPPONENT_NAME_PRG, BLACKJACK_OPPONENT_NAME_RU,
    BLACKJACK_NAME_THRESHOLD_PRG, BLACKJACK_NAME_THRESHOLD_RU,
    BLACKJACK_DECIMAL_FORMATTER_PRG, BLACKJACK_DECIMAL_FORMATTER_RU)
from patch_v0821_numeric_hotfix import encode_legacy_numeric_glyphs, NEW_BET_SUFFIX, CARD_BET_IDS
from patch_v0822_cards_loss_zero import ZERO_TILE
from patch_ending_photo_ru import ROOT_ID as END_PHOTO_ROOT_ID, ENDING_RU as END_PHOTO_RU
from workfile import parse_work


def main():
    if len(sys.argv)!=2:raise SystemExit('Usage: python verify_full_rom.py Okhotsk_RU.nes')
    info=read_ines(sys.argv[1]);reg=text_region(info);ptrs=read_pointer_table(reg)
    roots={p for p in ptrs[2:] if p!=0xffff and 0<=p<len(reg)}
    streams,_=collect_f2_graph(reg,roots)
    rules=load_bpe_rules(ROOT/'project_template/ru_bpe.tsv')
    L=extra_dictionary_blob_len(rules);a=EXTRA_DICT_START;b=a+L
    speed_prompts={
        5:'Куроки:[F3],верно?\n[F1:$02]Скорость текста?',
        6:'Куроки:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
        7:'Сюн:[F3],с возвращением.\n[F1:$02]Продолжим расследование.\n[F1:$02]Скорость текста?',
    }
    for rid,tr in speed_prompts.items():
        raw,_,ok=parse_stream(reg,ptrs[rid]); assert ok
        exp=encode_ru_markup_bpe(tr,rules)+b'\xFF'
        assert raw==exp,f'speed prompt ID {rid} mismatch/page break regression'
    # The last dialogue under the wedding/photo screen uses pattern table 1,
    # where ordinary lowercase RU tiles 41-5F are occupied by photo graphics.
    # Keep this one root uppercase-only and in its existing physical slot.
    end_raw,_,ok=parse_stream(reg,ptrs[END_PHOTO_ROOT_ID]); assert ok
    end_exp=encode_ru_markup_bpe(END_PHOTO_RU,rules)+b'\xFF'
    assert end_raw==end_exp,'final photo dialogue ID1291 mismatch'
    assert not any(0x41 <= b <= 0x5F for b in end_raw),'final photo dialogue contains lowercase glyph codes'
    assert not any(b>=0x60 and b not in {0x60,0x62,0xF1,0xF9,0xFE,0xFF} for b in end_raw),'final photo dialogue contains unsafe BPE/high glyph tokens'
    fc_args=set()
    for p in streams:
        raw,ops,ok=parse_stream(reg,p)
        assert ok,f'unterminated stream ${p:04X}'
        assert not (max(p,a)<min(p+len(raw),b)),f'text stream overlaps secondary dictionary: ${p:04X}'
        for op in ops:
            if op.code==0xFC and len(op.args)==1: fc_args.add(op.args[0])
        for t in stream_refs_f2(ops):
            assert 0<=t<len(reg),f'bad F2 ${p:04X}->${t:04X}'
            assert not a<=t<b,f'F2 points into secondary dictionary: ${p:04X}->${t:04X}'
    # FC handler $C9E1 hard-switches PRG bank $0A before loading pointer IDs
    # 15/16, so these two pointers MUST stay inside bank A ($0000-$3FFF).
    # The seven-entry slab is fixed at original $140E; ID16 starts at entry2.
    assert fc_args <= {0x07,0x15,0x4E,0x5C,0x63},fc_args
    fc0,fc1=ptrs[15],ptrs[16]
    assert fc0==0x140E,f'FC ID15 moved from required bank-A base: ${fc0:04X}'
    assert 0<=fc0<0x4000 and 0<=fc1<0x4000,(fc0,fc1)
    pos=fc0; starts=[]
    for i in range(7):
        starts.append(pos)
        raw,_,ok=parse_stream(reg,pos)
        assert ok,f'unterminated FC slab entry {i} at ${pos:04X}'
        pos+=len(raw)
    assert fc1==starts[2],f'FC base ID16 ${fc1:04X} != slab entry2 ${starts[2]:04X}'
    def fc_idx(arg,state):
        return 2+((arg>>3)&7) if state else ((arg>>6)&7)
    for arg in sorted(fc_args):
        for state in (False,True):
            idx=fc_idx(arg,state)
            assert idx<len(starts),(arg,state,idx)
            q=fc1 if state else fc0
            skip=((arg>>3)&7) if state else ((arg>>6)&7)
            for _ in range(skip):
                q=reg.index(0xFF,q)+1
            assert q==starts[idx],f'FC ${arg:02X} state={int(state)} -> ${q:04X}, expected ${starts[idx]:04X}'
    fb=info['prg'][15*0x4000:16*0x4000]
    assert fb[0x65A:0x65E]==bytes.fromhex('9C C7 9C C7')
    assert fb[0x79C:0x7B8].startswith(bytes.fromhex('A9 0A 20 F4 FE 20 9A C6 E6 5A'))
    prg=info['prg']
    assert prg[BLACKJACK_OPPONENT_NAME_PRG:BLACKJACK_OPPONENT_NAME_PRG+3]==BLACKJACK_OPPONENT_NAME_RU, 'blackjack top opponent name is not СЮН'
    assert prg[BLACKJACK_NAME_THRESHOLD_PRG:BLACKJACK_NAME_THRESHOLD_PRG+1]==BLACKJACK_NAME_THRESHOLD_RU, 'blackjack player-name compositor still applies JP dakuten to RU lowercase'
    assert prg[BLACKJACK_DECIMAL_FORMATTER_PRG:BLACKJACK_DECIMAL_FORMATTER_PRG+len(BLACKJACK_DECIMAL_FORMATTER_RU)]==BLACKJACK_DECIMAL_FORMATTER_RU, 'dynamic decimal formatter still writes D0..D9 dictionary tokens'
    # Every translated GLYPH:D0..D9 marker must now be a direct RU digit (22..2B)
    # at its live relocated root. This also guards non-blackjack prices/ages/photo numbers.
    for rec in parse_work(ROOT/'project_template/script_work.txt'):
        tr=rec.get('tr','')
        if '[GLYPH:$D' not in tr: continue
        old=encode_legacy_numeric_glyphs(tr,rules); new=encode_ru_markup_bpe(tr,rules)
        assert len(old)==len(new)
        basep=ptrs[rec['id']]
        for off,(a0,b0) in enumerate(zip(old,new)):
            if a0!=b0:
                assert reg[basep+off]==b0,f'ID {rec["id"]} legacy numeric glyph remains at text ${basep+off:04X}: {reg[basep+off]:02X}!={b0:02X}'
    # All six blackjack bet acknowledgements must call one localized shared suffix.
    bet_targets=[]
    for rid in CARD_BET_IDS:
        _,ops,ok=parse_stream(reg,ptrs[rid]); assert ok
        ts=[x for x in stream_refs_f2(ops)]
        assert len(ts)==1,f'blackjack bet ID {rid} F2 count {ts}'
        bet_targets.append(ts[0])
    assert len(set(bet_targets))==1,bet_targets
    bet_raw,_,ok=parse_stream(reg,bet_targets[0]); assert ok
    assert bet_raw==encode_ru_markup_bpe(NEW_BET_SUFFIX,rules)+b'\xFF','blackjack bet suffix is not "N фиш."'
    # Runtime F2 audit for the blackjack outcome branches.  v0.8.21 accidentally
    # reintroduced the original JP $EC53 target in ID1353, while the other shared
    # streams had already been relocated by the repacker.  Verify the LIVE target
    # contents rather than assuming old addresses.
    import json
    shared_ru=json.load(open(ROOT/'project_template/shared_translations_full.json',encoding='utf-8-sig'))
    card_shared_expect={1337:['ECFF','ED1A'],1338:['ECF0','ED1A'],1353:['EC53']}
    for rid,keys in card_shared_expect.items():
        _,ops,ok=parse_stream(reg,ptrs[rid]); assert ok
        ts=stream_refs_f2(ops)
        assert len(ts)==len(keys),f'blackjack outcome ID{rid} F2 targets {ts}'
        for target,key in zip(ts,keys):
            got,_,ok=parse_stream(reg,target); assert ok
            exp=encode_ru_markup_bpe(shared_ru[key],rules)+b'\xFF'
            assert got==exp,f'blackjack outcome ID{rid} shared {key} at ${target:04X} is not localized'
    assert prg[PHONE_TABLE_PRG:PHONE_TABLE_PRG+len(PHONE_RU_TABLE)]==PHONE_RU_TABLE, 'wrong-number surname table not translated'
    assert len(PHONE_RU_NAMES)==10 and all(len(n)<=4 for n in PHONE_RU_NAMES)
    assert prg[TITLE_DESC_PRG:TITLE_DATA_PRG] == TITLE_DESC_NEW, 'title descriptors not updated for full ПРОДОЛЖИТЬ'
    for label,poff,width,old,new in TITLE_FIELDS:
        assert decode_localized_title_field(prg,poff,width)==new,f'title field {label} not translated'
    assert prg[INTRO_LOGIN_DESC_PRG:INTRO_LOGIN_DESC_PRG+8] == INTRO_LOGIN_DESC, 'post-intro LOGINSOFT descriptor must stay at original 18-tile layout'
    got_intro1 = decode_localized_title_field(prg,INTRO_LOGIN_DATA_PRG,INTRO_LOGIN_WIDTH)
    assert got_intro1 == INTRO_LOGIN_RU.center(INTRO_LOGIN_WIDTH), f'post-intro LOGINSOFT card mismatch: {got_intro1!r}'
    assert prg[SCENE_ATTR_TABLE_PRG:SCENE_ATTR_TABLE_PRG+64] == SCENE_ATTR_TABLE_ORIG, 'scene attribute source table $D913 was corrupted'
    got_intro2 = decode_localized_title_field(prg,INTRO_MYSTERY_DATA_PRG,INTRO_MYSTERY_WIDTH)
    assert got_intro2 == INTRO_MYSTERY_RU.center(INTRO_MYSTERY_WIDTH), f'post-intro Yuji Horii card mismatch: {got_intro2!r}'
    for poff,width,old,new in CREDIT_FIELDS:
        got=decode_localized_credit_field(prg,poff,width)
        exp=(new.rjust(width) if old.startswith(' ') else new.ljust(width))
        assert got==exp,f'credit field ${poff:05X} mismatch: {got!r} != {exp!r}'
    assert prg[NAME_PROMPT_PRG:NAME_PROMPT_PRG+len(RU_NAME)]==RU_NAME, 'name prompt not translated'
    assert prg[MEMO_PROMPT_PRG:MEMO_PROMPT_PRG+len(RU_MEMO)]==RU_MEMO, 'password prompt not translated'
    assert prg[SPEED_TABLE_PRG:SPEED_TABLE_PRG+len(RU_SPEED)]==RU_SPEED, 'speed labels not translated'
    assert prg[NAME_DAKUTEN_PRG]==0, 'name prompt dakuten overlay not cleared'
    assert prg[MEMO_DAKUTEN_PRG]==0, 'password prompt dakuten overlay not cleared'
    for q in NAV_TABLE_PRG:
        assert prg[q:q+len(RU_NAV)]==RU_NAV, f'nav table not translated at PRG ${q:05X}'
    assert RU_NAV[3:6]==b'\x00\x00\x00', 'input nav lost fixed 3-tile cursor gap'
    assert prg[INPUT_COMPOSITOR_PRG:INPUT_COMPOSITOR_PRG+len(INPUT_COMPOSITOR_RU)]==INPUT_COMPOSITOR_RU, 'input picker still uses JP dakuten compositor'
    for q in INPUT_TOP_TRIPLET_PRG:
        assert prg[q:q+len(INPUT_TOP_TRIPLET_RU)]==INPUT_TOP_TRIPLET_RU, f'input э/ю/я row wrong at PRG ${q:05X}'
    for q in INPUT_NAME_EXTRA_PRG:
        assert prg[q:q+len(INPUT_NAME_EXTRA_RU)]==INPUT_NAME_EXTRA_RU, f'name lowercase tail wrong at PRG ${q:05X}'
    font,_=decode(info['prg'][STREAM_PRG_OFF:ALLOC_END_PRG_OFF],OUT_SIZE)
    for i in range(10):assert font[(0x22+i)*16:(0x23+i)*16]==font[(0x74+i)*16:(0x75+i)*16]
    assert font[0x22*16:0x23*16]==ZERO_TILE, 'direct digit 0 tile $22 is not the user replacement'
    assert font[0x74*16:0x75*16]==ZERO_TILE, 'legacy/password digit 0 tile $74 is not the user replacement'
    legacy=(ROOT/'assets/font_ru_legacy.bin').read_bytes()
    assert font[0x40*16:0x41*16]==legacy[0x40*16:0x41*16], 'right-arrow tile 40 overwritten'
    assert font[0x3B*16:0x3C*16]==legacy[0x3B*16:0x3C*16], 'down-arrow tile 3B overwritten'
    assert font[0x2C*16:0x2D*16]==legacy[0x60*16:0x61*16], 'ю mirror tile 2C wrong'
    assert font[0x2D*16:0x2E*16]==legacy[0x61*16:0x62*16], 'я mirror tile 2D wrong'
    assert font[0x2E*16:0x2F*16]==legacy[0x5F*16:0x60*16], 'э input/password mirror tile 2E wrong'
    shared_font,_=_decode_font_resource(prg)
    from okhotsk_common import RU_UPPER_ENC
    for ch,raw_idx in RU_TO_RAW.items():
        code=0x3F if ch=='.' else RU_UPPER_ENC[ch]
        assert shared_font[raw_idx*16:raw_idx*16+8]==font[code*16:code*16+8],f'shared title/credit glyph {ch} wrong'
        assert shared_font[raw_idx*16+8:(raw_idx+1)*16]==b'\x00'*8,f'shared title/credit plane1 {ch} dirty'
    popup=decode_popup_from_raw(info['raw'])
    assigned={}
    for t,ch in zip(POPUP_LINE1_TILES,POPUP_LINE1): assigned[t]=ch
    for t,ch in zip(POPUP_LINE2_TILES,POPUP_LINE2):
        assert t not in assigned or assigned[t]==ch
        assigned[t]=ch
    from okhotsk_common import RU_UPPER_ENC
    for t,ch in assigned.items():
        code=RU_UPPER_ENC[ch]; p0=font[code*16:code*16+8]
        exp=p0+bytes((~b)&0xFF for b in p0)
        assert popup[t*16:(t+1)*16]==exp,f'wrong-password popup glyph {ch} at tile {t:02X}'
    for dst,src in POPUP_DAKUTEN_CLEANUP:
        assert popup[dst*16:(dst+1)*16]==popup[src*16:(src+1)*16], f'popup dakuten overlay tile {dst:02X} not cleared'
    print('SHA256',info['sha256'])
    print('Roots:',len(roots),'reachable streams:',len(streams),'secondary dictionary bytes:',L)
    print('FC args:',','.join(f'{x:02X}' for x in sorted(fc_args)),'FC bank-A slab:',f'${fc0:04X}-${pos-1:04X}')
    print('OK: full RU structure + FC/input/phone/title/credits + intact scene attributes + blackjack RU names/digits/dynamic counters + localized blackjack loss continuation + distinct password zero + live numeric glyphs + final-photo uppercase CHR-safe text verified.')
if __name__=='__main__':main()
