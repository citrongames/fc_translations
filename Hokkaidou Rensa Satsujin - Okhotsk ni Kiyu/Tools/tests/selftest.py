#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from okhotsk_common import *
from stream_codec import parse_stream, decode_stream_symbolic, stream_refs_f2, collect_f2_graph
from translation_codec import encode_ru_markup
from rle_packbits import decode, encode, encode_exact_length
from shared_translations import load_shared_translations
from ru_bpe import load_bpe_rules, encode_ru_markup_bpe
from repack_pool import extra_dictionary_blob_len, fc_entry_index
from check_script import visible_len
from prepare_ru_font_v08 import apply as prepare_font_v08
from patch_ru_direct_lowercase import patch as patch_lower
from patch_ru_extended_dictionary import patch as patch_ext
from patch_static_ui_ru import (patch as patch_static, RU_NAME, RU_MEMO, RU_SPEED, RU_NAV,
    NAME_PROMPT_PRG, MEMO_PROMPT_PRG, SPEED_TABLE_PRG, NAV_TABLE_PRG,
    NAME_DAKUTEN_PRG, MEMO_DAKUTEN_PRG, POPUP_DAKUTEN_CLEANUP,
    INPUT_COMPOSITOR_PRG, INPUT_COMPOSITOR_RU, INPUT_TOP_TRIPLET_PRG, INPUT_TOP_TRIPLET_RU,
    INPUT_NAME_EXTRA_PRG, INPUT_NAME_EXTRA_RU,
    decode_popup_from_raw, POPUP_LINE1, POPUP_LINE2, POPUP_LINE1_TILES, POPUP_LINE2_TILES)
from font_extract import STREAM_PRG_OFF, OUT_SIZE, ALLOC_END_PRG_OFF
from patch_phone_names_ru import patch as patch_phone_names, JP_TABLE as PHONE_JP_TABLE, RU_TABLE as PHONE_RU_TABLE, PHONE_TABLE_PRG, RU_NAMES as PHONE_RU_NAMES
from patch_title_credits_ru import (patch as patch_title_credits, TITLE_FIELDS, CREDIT_FIELDS, TITLE_DESC_PRG, TITLE_DATA_PRG, TITLE_DESC_NEW,
    decode_localized_title_field, decode_localized_credit_field, _decode_font_resource, RU_TO_RAW,
    INTRO_LOGIN_DESC_PRG, INTRO_LOGIN_DESC, INTRO_LOGIN_DATA_PRG, INTRO_LOGIN_WIDTH, INTRO_LOGIN_RU,
    SCENE_ATTR_TABLE_PRG, SCENE_ATTR_TABLE_ORIG,
    INTRO_MYSTERY_DATA_PRG, INTRO_MYSTERY_WIDTH, INTRO_MYSTERY_RU)

EXPECTED_SHA256='d42f3bdea8af5c1303d567e07afdf89d72d014639e8f7b88fc7a10404bec33ba'
EXPECTED_FIRST=' とうきょうわん はるみふとうに おとこの\nしたいが あがったとの しらせをうけた あなたは\nブカのくろきをつれ げんばに かけつけたのだった。'
RU_TEST='Тест русского шрифта.\nЁжик съел хлеб.'
RU_TEST_BYTES=bytes.fromhex('14 46 53 54 00 52 55 53 53 4C 50 44 50 00 5A 52 4A 56 54 41 3F F8 07 48 4A 4C 00 53 5C 46 4D 00 57 4D 46 42 3F')


def main():
    if len(sys.argv)!=2:
        raise SystemExit('Usage: python selftest.py game.nes')
    info=read_ines(sys.argv[1]); print('SHA256',info['sha256'])
    assert info['prg_banks']==16 and info['chr_banks']==0 and info['mapper']==1
    if info['sha256']!=EXPECTED_SHA256: print('WARNING: ROM hash differs from studied revision; structural tests continue.')
    region=text_region(info);ptrs=read_pointer_table(region);d=dictionary(region,ptrs)
    assert region[0x0E4E:0x0E80]==PHONE_JP_TABLE
    assert len(ptrs)==1573 and len(d)==112 and ptrs[0]==0x0C4A and ptrs[1]==0x0E4E
    assert decode_bytes(d[0x73-0x60],d,stop_at_ff=False)[0]=='に '
    assert ptrs[237]==0x142D
    raw237,ops237,ok237=parse_stream(region,ptrs[237]); assert ok237 and len(raw237)==57
    assert decode_stream_symbolic(region,ptrs[237],d)==EXPECTED_FIRST
    assert decode_stream_symbolic(region,ptrs[5],d).splitlines()[1].startswith('[F1:$02]メッセージ')
    raw6,ops6,ok6=parse_stream(region,ptrs[6]); assert ok6 and stream_refs_f2(ops6)==[0x1309]
    exp6=decode_stream_symbolic(region,ptrs[6],d,expand_f2=True)
    assert '[F2:' not in exp6 and 'あなたの おかえりを' in exp6
    roots={p for p in ptrs[2:] if p!=0xffff and p<len(region)}
    allstreams,_=collect_f2_graph(region,roots); assert len(allstreams)==1746

    src=info['prg'][STREAM_PRG_OFF:ALLOC_END_PRG_OFF];font,used=decode(src,OUT_SIZE)
    assert used==len(src)==1239 and encode(font)==src

    # v0.8 Russian byte layout: lowercase is direct (no E prefix), D/E are BPE,
    # and digits moved to direct codes/tiles 22..2B.
    assert encode_ru(RU_TEST)==RU_TEST_BYTES
    assert encode_ru_markup(RU_TEST)==RU_TEST_BYTES
    assert encode_ru_markup('А[F3]а[F1:$02]')==bytes([1,0xF3,0x41,0xF1,2])
    assert encode_ru('0123456789')==bytes(range(0x22,0x2C))
    assert decode_ru_bytes(RU_TEST_BYTES+b'\xFF')==RU_TEST
    tiles=ru_render_tile_indices(encode_ru('АаЁёЯя0123456789')+b'\xFF')
    assert tiles==[0x01,0x41,0x07,0x47,0x21,0x2D,*range(0x22,0x2C)],tiles

    legacy=(ROOT/'assets/font_ru_legacy.bin').read_bytes();ru_font=(ROOT/'assets/font_ru.bin').read_bytes()
    assert len(legacy)==len(ru_font)==0x800 and prepare_font_v08(legacy)==ru_font
    for i in range(10): assert ru_font[(0x22+i)*16:(0x23+i)*16]==ru_font[(0x74+i)*16:(0x75+i)*16]
    # v0.8.3: preserve original UI arrows at tiles 40/3B; mirror ю/я to 2C/2D.
    assert ru_font[0x40*16:0x41*16]==legacy[0x40*16:0x41*16]
    assert ru_font[0x3B*16:0x3C*16]==legacy[0x3B*16:0x3C*16]
    assert ru_font[0x2C*16:0x2D*16]==legacy[0x60*16:0x61*16]
    assert ru_font[0x2D*16:0x2E*16]==legacy[0x61*16:0x62*16]
    assert ru_font[0x2E*16:0x2F*16]==legacy[0x5F*16:0x60*16]  # э mirror for input/password
    assert ru_font[0x60*16:0x61*16]==legacy[0x60*16:0x61*16]
    assert ru_font[0x61*16:0x62*16]==legacy[0x61*16:0x62*16]
    changed=[i for i in range(128) if font[i*16:(i+1)*16]!=ru_font[i*16:(i+1)*16]]
    expected=list(range(1,47))+[58,62,63]+list(range(65,98))
    assert changed==expected,(changed,expected)
    assert len(encode(ru_font))>0
    exact_ru=encode_exact_length(ru_font,ALLOC_END_PRG_OFF-STREAM_PRG_OFF)
    dec_ru,used_ru=decode(exact_ru,OUT_SIZE); assert len(exact_ru)==1239 and used_ru==1239 and dec_ru==ru_font

    # Current full-RU BPE: 110 old text tokens minus two preserved macros +
    # 32 secondary D0..EF tokens = 142 compression rules.
    rules=load_bpe_rules(ROOT/'project_template/ru_bpe.tsv')
    assert len(rules)==142 and max(r.token for r in rules)==0xEF
    assert extra_dictionary_blob_len(rules)>0
    shared=load_shared_translations(ROOT/'project_template/shared_translations_full.json')
    assert len(shared)==125 and encode_ru_markup_bpe(next(iter(shared.values())),rules)
    # v0.8.4: FC is a visible dynamic prefix on the same line. The two Takano
    # lines that overflowed at runtime must stay within the 27-tile text width,
    # and every FC-prefixed shared line must pass the same effective-width check.
    assert shared[0x18A7].splitlines()[0]=='[FC:$07]Сперва - мусор.'
    assert shared[0x18DF].splitlines()[0]=='[FC:$07]Позвонил в полицию.'
    assert visible_len(shared[0x18A7].splitlines()[0])==22
    assert visible_len(shared[0x18DF].splitlines()[0])==26
    for tr in shared.values():
        for line in tr.splitlines():
            if line.startswith('[FC:$'):
                assert visible_len(line)<=27,(visible_len(line),line)

    # Engine patches apply cleanly and extended D/E handler keeps the original
    # dictionary source-stack prologue before scanning the secondary table.
    raw_with_ru_font=bytearray(info['raw'])
    raw_with_ru_font[info['prg_offset']+STREAM_PRG_OFF:info['prg_offset']+ALLOC_END_PRG_OFF]=exact_ru
    static_patched=patch_static(bytes(raw_with_ru_font))
    phone_patched=patch_phone_names(static_patched)
    title_patched=patch_title_credits(phone_patched)
    ppi=read_ines_bytes_for_test(title_patched); pprg=title_patched[ppi:ppi+16*0x4000]
    assert pprg[PHONE_TABLE_PRG:PHONE_TABLE_PRG+50]==PHONE_RU_TABLE
    assert len(PHONE_RU_NAMES)==10 and all(len(n)<=4 for n in PHONE_RU_NAMES)
    # v0.8.10 shared title/staff font + resized CONTINUE/ARMOR title descriptors.
    assert pprg[TITLE_DESC_PRG:TITLE_DATA_PRG] == TITLE_DESC_NEW
    for label,poff,width,old,new in TITLE_FIELDS:
        assert decode_localized_title_field(pprg,poff,width)==new,(label,decode_localized_title_field(pprg,poff,width),new)
    assert pprg[INTRO_LOGIN_DESC_PRG:INTRO_LOGIN_DESC_PRG+8] == INTRO_LOGIN_DESC
    assert decode_localized_title_field(pprg,INTRO_LOGIN_DATA_PRG,INTRO_LOGIN_WIDTH) == INTRO_LOGIN_RU.center(INTRO_LOGIN_WIDTH)
    assert pprg[SCENE_ATTR_TABLE_PRG:SCENE_ATTR_TABLE_PRG+64] == SCENE_ATTR_TABLE_ORIG
    assert decode_localized_title_field(pprg,INTRO_MYSTERY_DATA_PRG,INTRO_MYSTERY_WIDTH) == INTRO_MYSTERY_RU.center(INTRO_MYSTERY_WIDTH)
    for poff,width,old,new in CREDIT_FIELDS:
        got=decode_localized_credit_field(pprg,poff,width)
        exp=(new.rjust(width) if old.startswith(' ') else new.ljust(width))
        assert got==exp,(poff,got,exp)
    shared_font,_=_decode_font_resource(pprg)
    for ch,raw_idx in RU_TO_RAW.items():
        code=0x3F if ch=='.' else RU_UPPER_ENC[ch]
        assert shared_font[raw_idx*16:raw_idx*16+8]==ru_font[code*16:code*16+8],(ch,raw_idx)
        assert shared_font[raw_idx*16+8:(raw_idx+1)*16]==b'\x00'*8,(ch,raw_idx)
    spi=read_ines_bytes_for_test(static_patched); sprg=static_patched[spi:spi+16*0x4000]
    assert sprg[NAME_PROMPT_PRG:NAME_PROMPT_PRG+len(RU_NAME)]==RU_NAME
    assert sprg[MEMO_PROMPT_PRG:MEMO_PROMPT_PRG+len(RU_MEMO)]==RU_MEMO
    assert sprg[SPEED_TABLE_PRG:SPEED_TABLE_PRG+len(RU_SPEED)]==RU_SPEED
    assert sprg[NAME_DAKUTEN_PRG]==0
    assert sprg[MEMO_DAKUTEN_PRG]==0
    for q in NAV_TABLE_PRG: assert sprg[q:q+len(RU_NAV)]==RU_NAV
    assert RU_NAV[3:6]==b'\x00\x00\x00'  # fixed cursor-safe gap between 3-tile choices
    assert sprg[INPUT_COMPOSITOR_PRG:INPUT_COMPOSITOR_PRG+len(INPUT_COMPOSITOR_RU)]==INPUT_COMPOSITOR_RU
    for q in INPUT_TOP_TRIPLET_PRG: assert sprg[q:q+len(INPUT_TOP_TRIPLET_RU)]==INPUT_TOP_TRIPLET_RU
    for q in INPUT_NAME_EXTRA_PRG: assert sprg[q:q+len(INPUT_NAME_EXTRA_RU)]==INPUT_NAME_EXTRA_RU
    popup=decode_popup_from_raw(static_patched)
    assigned={}
    for t,ch in zip(POPUP_LINE1_TILES,POPUP_LINE1): assigned[t]=ch
    for t,ch in zip(POPUP_LINE2_TILES,POPUP_LINE2):
        assert t not in assigned or assigned[t]==ch
        assigned[t]=ch
    for t,ch in assigned.items():
        code=RU_UPPER_ENC[ch]; p0=ru_font[code*16:code*16+8]
        exp=p0+bytes((~b)&0xFF for b in p0)
        assert popup[t*16:(t+1)*16]==exp,(t,ch)
    for dst,src in POPUP_DAKUTEN_CLEANUP:
        assert popup[dst*16:(dst+1)*16]==popup[src*16:(src+1)*16],(dst,src)
    patched=patch_ext(patch_title_credits(patch_phone_names(patch_static(patch_lower(bytes(raw_with_ru_font))))))
    pi=read_ines_bytes_for_test(patched);fb=patched[pi+15*0x4000:pi+16*0x4000]
    assert fb[0x65A:0x65E]==bytes.fromhex('9C C7 9C C7')
    assert fb[0x79C:0x7B8].startswith(bytes.fromhex('A9 0A 20 F4 FE 20 9A C6 E6 5A'))
    # FC handler $C9E1: after argument/state decoding it hard-switches bank $0A
    # at $CA05, then loads pointer-table words $801E/$8020 (IDs 15/16).
    assert fb[0x9E1:0x9E7]==bytes.fromhex('20 9A C6 20 60 C6')
    assert fb[0xA05:0xA16]==bytes.fromhex('A9 0A 20 F4 FE BD 1E 80 85 14 BD 1F 80 09 80 85 15')
    expected_fc={0x07:(0,2),0x15:(0,4),0x4E:(1,3),0x5C:(1,5),0x63:(1,6)}
    assert {a:(fc_entry_index(a,False),fc_entry_index(a,True)) for a in expected_fc}==expected_fc
    print('OK: clean ROM structure, F2 graph, exact font RLE, direct RU layout, static UI/direct input alphabet, wrong-number phone surnames, title/post-intro cards/credits + scene-attribute regression guard, BPE/engine patches and FC bank-A handler verified.')


def read_ines_bytes_for_test(raw:bytes):
    assert raw[:4]==b'NES\x1a'
    return 16+(512 if raw[6]&4 else 0)

if __name__=='__main__': main()
