#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import RU_UPPER_ENC
from rle_packbits import decode, encode_exact_length

# These strings do NOT use the normal scenario bytecode. They are raw font-tile
# arrays consumed by fixed-bank UI routines, so they must be patched separately.
NAME_PROMPT_PRG = 0x3CF69   # CPU $CF69, fixed bank F, 12 tiles
MEMO_PROMPT_PRG = 0x3CF75   # CPU $CF75, fixed bank F, 14 tiles
SPEED_TABLE_PRG = 0x3D5A3   # CPU $D5A3, fixed bank F, 3 x 3 tiles
NAV_TABLE_PRG = (0x23E3F, 0x33E3F)  # bank 8/12 duplicate, 9 tiles + FF + 3 tiles + FF
# The name/password screen descriptors separately draw dakuten tile $7E above
# the original Japanese 'だ' in ください.  After replacing the prompts with
# Russian text those overlays land on М / О, so blank those descriptor tiles.
NAME_DAKUTEN_PRG = 0x3CF3F
MEMO_DAKUTEN_PRG = 0x3CF57

# The character picker has its OWN glyph compositor at fixed-bank CPU $CB0A.
# Original JP semantics turn bytes $41-$54 into base kana + dakuten tile $7E
# and $55-$59 into base は-row kana + handakuten tile $7F.  The Russian text
# engine already repurposes $41-$5F as direct lowercase Cyrillic, therefore
# this special picker must do the same: keep A unchanged and leave Y=$00.
INPUT_COMPOSITOR_PRG = 0x3CB0A
INPUT_COMPOSITOR_JP = bytes.fromhex('C9 40 90 0B A0 7E E9 40 C9 15 90 03 C8 E9 05')
INPUT_COMPOSITOR_RU = b'\xEA' * len(INPUT_COMPOSITOR_JP)

# Two duplicated picker tables (bank 8 / bank 12) contain the non-voiced
# special kana positions.  Keep the password-valid code set $2C/$2D/$2E, but
# reorder it visually as э/ю/я (tile $2E is mirrored from lowercase э by
# prepare_ru_font_v08.py).  The final five cells are shown only on the name
# screen, so repurpose them from small-kana/long-vowel codes to the missing
# lowercase Russian letters ш/щ/ъ/ы/ь = $5A-$5E.
INPUT_TOP_TRIPLET_PRG = (0x23DF9, 0x33DF9)
INPUT_TOP_TRIPLET_JP = bytes.fromhex('2C 00 00 00 2D 00 00 00 2E')
INPUT_TOP_TRIPLET_RU = bytes.fromhex('2E 00 00 00 2C 00 00 00 2D')
INPUT_NAME_EXTRA_PRG = (0x23E35, 0x33E35)
INPUT_NAME_EXTRA_JP = bytes.fromhex('30 00 31 00 32 00 2F 00 33')
INPUT_NAME_EXTRA_RU = bytes.fromhex('5A 00 5B 00 5C 00 5D 00 5E')

# The "wrong investigation memo/password" popup is a small sprite bitmap loaded
# from a second PackBits stream immediately after the main text-font stream.
# PRG $04F3..$04F6 = 4-byte graphics header; payload $04F7..$062E decodes
# exactly 0x190 bytes (= tiles $00..$18 in sprite pattern table 0).
POPUP_HEADER_PRG = 0x04F3
POPUP_PAYLOAD_PRG = 0x04F7
POPUP_PAYLOAD_LEN = 0x0138
POPUP_OUT_SIZE = 0x0190
POPUP_HEADER = bytes.fromhex('82 01 00 00')
# OAM uses six text cells per row. Tile $0D is intentionally shared between
# line1 col6 and line2 col2 in the original Japanese popup, so Russian wording
# is selected to share the same glyph there too:
#   ОШИБКА
#   ПАРОЛЯ
# both positions contain 'А'.
POPUP_LINE1 = 'ОШИБКА'
POPUP_LINE2 = 'ПАРОЛЯ'
POPUP_LINE1_TILES = (0x08,0x09,0x0A,0x0B,0x0C,0x0D)
POPUP_LINE2_TILES = (0x11,0x0D,0x12,0x13,0x14,0x15)
# The popup's two original 'が' use dakuten pixels stored in the cell directly
# above each glyph: tile $05 above line1 col6 and tile $10 above line2 col2.
# They are not part of tile $0D itself.  Restore those cells to their clean
# border/background twins so Russian А has no stray dakuten.
POPUP_DAKUTEN_CLEANUP = ((0x05,0x04),(0x10,0x0F))

# Main font block, needed only as a source of the already-inserted Russian
# glyph bitmaps.  build_project runs this patch after font_insert.py.
FONT_PAYLOAD_PRG = 0x001C
FONT_ALLOC_END_PRG = 0x04F3
FONT_OUT_SIZE = 0x0800

JP_NAME = bytes.fromhex('1A 1F 18 2D 00 16 2A 0E 03 0B 06 16')
JP_MEMO = bytes.fromhex('0A 17 06 62 63 2D 00 16 2A 0E 03 0B 06 16')
JP_SPEED = bytes.fromhex('10 24 16 12 0D 17 19 0A 16')
JP_NAV = bytes.fromhex('23 4F 29 00 00 00 19 2C 29 FF 08 08 21 FF')


def tile_text(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch == ' ':
            out.append(0)
        else:
            try:
                out.append(RU_UPPER_ENC[ch])
            except KeyError:
                raise ValueError(f'Unsupported static UI character: {ch!r}') from None
    return bytes(out)

# Keep the ORIGINAL three-cell placement of both choices.  The runtime cursor
# has fixed X positions, therefore a 5-letter "ВЫХОД" overlapped the cursor.
# "КОН" is a compact "КОНЕЦ" and preserves the exact 3+3+3 layout.
RU_NAME = tile_text('ВВЕДИТЕ ИМЯ ')
RU_MEMO = tile_text('ВВЕДИТЕ ПАРОЛЬ')
RU_SPEED = tile_text('БЫСНОРМЕД')  # БЫС / НОР / МЕД
RU_NAV = tile_text('НАЗ   КОН') + b'\xFF' + tile_text('ДАЛ') + b'\xFF'
OLD_RU_NAV = tile_text('НАЗ ВЫХОД') + b'\xFF' + tile_text('ДАЛ') + b'\xFF'  # v0.8.5 upgrade path

assert len(RU_NAME) == len(JP_NAME) == 12
assert len(RU_MEMO) == len(JP_MEMO) == 14
assert len(RU_SPEED) == len(JP_SPEED) == 9
assert len(RU_NAV) == len(JP_NAV) == 14

PATCHES = [
    ('name prompt', NAME_PROMPT_PRG, JP_NAME, RU_NAME),
    ('password/memo prompt', MEMO_PROMPT_PRG, JP_MEMO, RU_MEMO),
    ('text speed', SPEED_TABLE_PRG, JP_SPEED, RU_SPEED),
    ('name/password nav bank8', NAV_TABLE_PRG[0], JP_NAV, RU_NAV),
    ('name/password nav bank12', NAV_TABLE_PRG[1], JP_NAV, RU_NAV),
]


def _popup_glyph(font: bytes, ch: str) -> bytes:
    """Convert a normal RU font tile into the popup's opaque sprite style.

    The popup uses plane0 = glyph and plane1 = bitwise NOT(glyph), making each
    8x8 cell opaque while preserving the same letter shape.
    """
    code = RU_UPPER_ENC[ch]
    tile = font[code*16:(code+1)*16]
    if len(tile) != 16:
        raise ValueError(f'Bad font tile for {ch!r}')
    p0 = tile[:8]
    return p0 + bytes((~b)&0xFF for b in p0)


def _patch_wrong_memo_popup(prg: bytearray) -> None:
    if bytes(prg[POPUP_HEADER_PRG:POPUP_HEADER_PRG+4]) != POPUP_HEADER:
        raise ValueError('wrong-password popup: unexpected graphics header at PRG $04F3')

    # Decode the main font as it exists in the current intermediate ROM.  At
    # this point in build_project it is already the Russian font.
    font, font_used = decode(bytes(prg[FONT_PAYLOAD_PRG:FONT_ALLOC_END_PRG]), FONT_OUT_SIZE)
    if font_used != FONT_ALLOC_END_PRG - FONT_PAYLOAD_PRG:
        raise ValueError(f'wrong-password popup: font stream consumed {font_used}, expected {FONT_ALLOC_END_PRG-FONT_PAYLOAD_PRG}')

    src = bytes(prg[POPUP_PAYLOAD_PRG:POPUP_PAYLOAD_PRG+POPUP_PAYLOAD_LEN])
    popup, used = decode(src, POPUP_OUT_SIZE)
    if used != POPUP_PAYLOAD_LEN:
        raise ValueError(f'wrong-password popup: stream consumed {used}, expected {POPUP_PAYLOAD_LEN}')
    buf = bytearray(popup)

    # Patch six cells on each row.  Tile $0D is shared; the chosen strings make
    # it 'А' in both locations, matching the original OAM reuse.
    assigned = {}
    for tile_id, ch in zip(POPUP_LINE1_TILES, POPUP_LINE1):
        assigned.setdefault(tile_id, ch)
        if assigned[tile_id] != ch:
            raise AssertionError((tile_id, assigned[tile_id], ch))
    for tile_id, ch in zip(POPUP_LINE2_TILES, POPUP_LINE2):
        assigned.setdefault(tile_id, ch)
        if assigned[tile_id] != ch:
            raise AssertionError((tile_id, assigned[tile_id], ch))
    for tile_id, ch in assigned.items():
        buf[tile_id*16:(tile_id+1)*16] = _popup_glyph(font, ch)

    # Remove the two original dakuten overlays for が.  $05 is the same top
    # border cell as $04 plus dakuten pixels; $10 is the same blank middle
    # cell as $0F plus dakuten pixels.
    for dst, src_tile in POPUP_DAKUTEN_CLEANUP:
        buf[dst*16:(dst+1)*16] = buf[src_tile*16:(src_tile+1)*16]

    packed = encode_exact_length(bytes(buf), POPUP_PAYLOAD_LEN)
    # Exact-length replacement is mandatory: the next graphics stream follows
    # immediately in bank 0.
    prg[POPUP_PAYLOAD_PRG:POPUP_PAYLOAD_PRG+POPUP_PAYLOAD_LEN] = packed


def decode_popup_from_raw(raw: bytes) -> bytes:
    """Test/helper: return the 0x190-byte popup graphics from a ROM."""
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    prg_off = 16 + (512 if raw[6] & 4 else 0)
    prg = raw[prg_off:prg_off + raw[4]*0x4000]
    out, used = decode(prg[POPUP_PAYLOAD_PRG:POPUP_PAYLOAD_PRG+POPUP_PAYLOAD_LEN], POPUP_OUT_SIZE)
    if used != POPUP_PAYLOAD_LEN:
        raise ValueError((used, POPUP_PAYLOAD_LEN))
    return out


def patch(raw: bytes, *, allow_already_patched: bool = True) -> bytes:
    # Validate ROM layout and find PRG start (trainer-safe).
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    prg_banks = raw[4]
    if prg_banks != 16:
        raise ValueError(f'Expected 16 PRG banks, got {prg_banks}')
    prg_off = 16 + (512 if raw[6] & 4 else 0)
    out = bytearray(raw)
    prg = bytearray(out[prg_off:prg_off + prg_banks*0x4000])

    # Russian input picker: bypass the JP dakuten/handakuten compositor.
    a = INPUT_COMPOSITOR_PRG; b = a + len(INPUT_COMPOSITOR_JP)
    cur = bytes(prg[a:b])
    if cur == INPUT_COMPOSITOR_RU and allow_already_patched:
        pass
    elif cur == INPUT_COMPOSITOR_JP:
        prg[a:b] = INPUT_COMPOSITOR_RU
    else:
        raise ValueError(f'input glyph compositor: unexpected bytes at PRG ${a:05X}: {cur.hex(" ")}')

    # Make every visible picker cell Cyrillic.  The top triplet remains the
    # same three password codes, only reordered.  The bottom five are name-only.
    for label, offsets, old, new in (
        ('input top э/ю/я', INPUT_TOP_TRIPLET_PRG, INPUT_TOP_TRIPLET_JP, INPUT_TOP_TRIPLET_RU),
        ('name extra ш/щ/ъ/ы/ь', INPUT_NAME_EXTRA_PRG, INPUT_NAME_EXTRA_JP, INPUT_NAME_EXTRA_RU),
    ):
        for poff in offsets:
            cur = bytes(prg[poff:poff+len(old)])
            if cur == new and allow_already_patched:
                continue
            if cur != old:
                raise ValueError(f'{label}: unexpected bytes at PRG ${poff:05X}: {cur.hex(" ")}')
            prg[poff:poff+len(new)] = new

    # Clear the two hard-coded dakuten overlays used by the original ください.
    for label, poff in (('name prompt dakuten', NAME_DAKUTEN_PRG),
                        ('password prompt dakuten', MEMO_DAKUTEN_PRG)):
        cur = prg[poff]
        if cur == 0x00 and allow_already_patched:
            pass
        elif cur == 0x7E:
            prg[poff] = 0x00
        else:
            raise ValueError(f'{label}: unexpected byte at PRG ${poff:05X}: ${cur:02X}')

    for name, poff, old, new in PATCHES:
        a = poff; b = a + len(old)
        cur = bytes(prg[a:b])
        if cur == new and allow_already_patched:
            continue
        if name.startswith('name/password nav') and cur == OLD_RU_NAV:
            prg[a:b] = new
            continue
        if cur != old:
            raise ValueError(f'{name}: unexpected bytes at PRG ${poff:05X}: {cur.hex(" ")}')
        prg[a:b] = new

    # This patch is intentionally idempotent: decoding the already-patched
    # popup and writing the same Russian glyphs again produces the same output.
    _patch_wrong_memo_popup(prg)
    out[prg_off:prg_off + len(prg)] = prg
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description='Patch raw-tile name/password/speed UI and wrong-password popup to Russian.')
    ap.add_argument('rom')
    ap.add_argument('-o','--out',required=True)
    args = ap.parse_args()
    raw = Path(args.rom).read_bytes()
    out = patch(raw)
    Path(args.out).write_bytes(out)
    print('Patched static UI:')
    print('  name prompt:      ВВЕДИТЕ ИМЯ (dakuten overlay cleared)')
    print('  password prompt:  ВВЕДИТЕ ПАРОЛЬ (dakuten overlay cleared)')
    print('  nav:              НАЗ   КОН / ДАЛ')
    print('  text speed:       БЫС / НОР / МЕД')
    print('  input keyboard:   direct RU glyphs 41..5F; no dakuten/handakuten composition')
    print('  input extras:     э/ю/я + ш/щ/ъ/ы/ь instead of leftover JP special kana')
    print('  wrong password:   ОШИБКА / ПАРОЛЯ (both が dakuten overlays cleared)')
    print('Wrote:', args.out)

if __name__ == '__main__':
    main()
