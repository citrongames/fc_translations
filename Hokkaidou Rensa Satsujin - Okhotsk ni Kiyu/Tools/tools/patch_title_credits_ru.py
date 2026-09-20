#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import RU_UPPER_ENC

# The title/start-menu and ending staff roll share a compact 40-glyph Latin
# font resource.  The title screen addresses its tiles directly as $80..$A7;
# the staff-roll stream stores one-based glyph codes (raw font index + 1).
#
# Resource pointer table entry $0A points to CPU $B839 in PRG bank 0, i.e.
# PRG offset $03839.  The resource is 20 literal PackBits packets of 32 bytes
# (= 0x280 bytes / 40 NES tiles), terminated by $81.
TITLE_FONT_PRG = 0x03839
TITLE_FONT_RAW_SIZE = 0x0280
TITLE_FONT_PACKED_SIZE = 20 * 33 + 1  # [20 * (literal length byte + 32 bytes)] + $81
TITLE_FONT_END = TITLE_FONT_PRG + TITLE_FONT_PACKED_SIZE

# Preserve the glyphs actually still needed as numbers/copyright marker:
#   raw 1 = '1', raw 7 = '7', raw 8 = '8', raw 9 = '9', raw 10 = '@'.
# Everything else through original 'Z' is available for Russian letters.
# We intentionally keep all staff-roll text codes <= $25, because the original
# stream uses values above that range as layout/control bytes.
# Missing Russian letters Ч/Ъ are not needed by any localized title/credit
# string and therefore do not consume slots.
RU_CREDITS_ALPHABET = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦШЩЫЬЭЮЯ.'
_AVAILABLE_RAW = [i for i in range(0x25) if i not in {1, 7, 8, 9, 10}]
assert len(RU_CREDITS_ALPHABET) == len(_AVAILABLE_RAW) == 32
RU_TO_RAW = dict(zip(RU_CREDITS_ALPHABET, _AVAILABLE_RAW))
RAW_TO_RU = {v: k for k, v in RU_TO_RAW.items()}

# Title table. The original CONTINUE descriptor is only 8 tiles wide.
# v0.8.10 reallocates two tiles from the ARMOR copyright line so the menu can
# use the full 10-letter Russian word «ПРОДОЛЖИТЬ» without moving any code:
#   CONTINUE: 8 -> 10 tiles
#   ARMOR copyright: 20 -> 18 tiles (drop the blank after ©)
# The complete title-data slab therefore remains exactly the original size.
TITLE_DESC_PRG = 0x3CE00
TITLE_DATA_PRG = 0x3CE18
TITLE_DATA_SIZE = 54
TITLE_DESC_OLD = bytes.fromhex(
    '10 0C 01 0A 18 CE 12 0C 01 08 22 CE 17 06 01 14 2A CE 19 08 01 10 3E CE'
)
TITLE_DESC_NEW = bytes.fromhex(
    '10 0C 01 0A 18 CE 12 0C 01 0A 22 CE 17 06 01 12 2C CE 19 08 01 10 3E CE'
)

TITLE_FIELDS = [
    # label, PRG offset, width, original, Russian
    ('game start', 0x3CE18, 10, 'GAME START', 'НОВАЯ ИГРА'),
    ('continue',   0x3CE22, 10, 'CONTINUE',   'ПРОДОЛЖИТЬ'),
    ('copyright armor', 0x3CE2C, 18, '@ 1987 ARMOR PROJECT', '@1987 АРМОР ПРОЕКТ'),
    ('copyright loginsoft', 0x3CE3E, 16, '@ 1987 LOGINSOFT', '@ 1987 ЛОГИНСОФТ'),
]

# Two additional post-intro title cards use the same $80..$A4 glyph set.
# Runtime QA in v0.8.11 found that after remapping the shared font they still
# fed the original Latin tile codes, so they appeared as Cyrillic garbage.
#
# IMPORTANT v0.8.17 fix:
# Card 1 owns exactly 18 tiles at $EC8B.  v0.8.12 incorrectly relocated the
# 22-tile full translation into zero bytes at fixed-bank $D938.  Those bytes
# are NOT free: they are inside the 64-byte scene attribute table copied from
# $D913 to PPU $2007, which caused mixed gray/white dialogue text.
# Keep the original descriptor and payload location, and fit a safe 18-tile
# abbreviation in place.
INTRO_LOGIN_DESC_PRG = 0x3EC83
INTRO_LOGIN_DATA_PRG = 0x3EC8B
INTRO_LOGIN_WIDTH = 18
INTRO_LOGIN_DESC = bytes.fromhex('02 00 0D 07 01 12 8B EC')
INTRO_LOGIN_OLD = 'LOGINSOFT PRESENTS'
INTRO_LOGIN_RU = 'ЛОГИНСОФТ ПРЕДСТ.'
assert len(INTRO_LOGIN_OLD) == INTRO_LOGIN_WIDTH and len(INTRO_LOGIN_RU) <= INTRO_LOGIN_WIDTH

# Original 64-byte attribute table source at CPU $D913 / PRG $3D913.
# Retained as a repair guard so an already-broken v0.8.12 ROM can be restored.
SCENE_ATTR_TABLE_PRG = 0x3D913
SCENE_ATTR_TABLE_ORIG = bytes.fromhex(
    'FF FF FF FF 33 00 00 00 FF FF FF FF 33 00 00 00 '
    'FF FF FF FF 33 00 00 00 FF FF FF FF 33 00 00 00 '
    '0F 0F 0F 0F 03 00 00 00 00 00 00 00 00 00 00 00 '
    '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00'
)
# Descriptor/string used only by the bad v0.8.12 relocation, recognized for repair.
INTRO_LOGIN_DESC_BAD_V0812 = bytes.fromhex('02 00 0D 05 01 16 38 D9')
INTRO_LOGIN_BAD_DATA_PRG = 0x3D938
INTRO_LOGIN_BAD_RU = 'ЛОГИНСОФТ ПРЕДСТАВЛЯЕТ'

# Card 2 already owns 22 tiles, enough for a centered Russian title.
INTRO_MYSTERY_DESC_PRG = 0x3ECE7
INTRO_MYSTERY_DATA_PRG = 0x3ECEF
INTRO_MYSTERY_WIDTH = 22
INTRO_MYSTERY_DESC = bytes.fromhex('02 D0 0D 05 01 16 EF EC')
INTRO_MYSTERY_OLD = 'THE YUJI HORII MYSTERY'
INTRO_MYSTERY_RU = 'ДЕТЕКТИВ ЮДЗИ ХОРИИ'
assert len(INTRO_MYSTERY_OLD) == INTRO_MYSTERY_WIDTH
assert len(INTRO_MYSTERY_RU) == 19

# Recognized title-data states. OLD is the untouched Japanese-release table;
# V089 is the first Russian layout with the 8-tile abbreviation.
TITLE_DATA_OLD = None
TITLE_DATA_V089 = None
TITLE_DATA_NEW = None

# Staff-roll strings.  Every field stays at its original byte width; shorter
# Russian text is padded with spaces.  Original fields with leading spaces were
# right-aligned by the game, so their replacements are right-aligned too.
CREDIT_FIELDS = [
    (0x23002, 4,  'CAST',                    'РОЛИ'),
    (0x23009, 19, 'SARUWATARI SYUNSUKE',     'САРУВАТАРИ СЮНСУКЭ'),
    (0x2301F, 13, 'NOMURA MAKIKO',            'НОМУРА МАКИКО'),
    (0x2302F, 15, 'NAKAYAMA MEGUMI',          'НАКАЯМА МЭГУМИ'),
    (0x23041, 15, 'MASUDA BUNKICHI',           'МАСУДА БУНКИТИ'),
    (0x23052, 13, ' IIJIMA YUKIO',             'ИИДЗИМА ЮКИО'),
    (0x23061, 15, 'SHIRAKI YUKUROU',           'СИРАКИ ЮКУРО'),
    (0x23073, 14, 'OKUMURA KISUKE',            'ОКУМУРА КИСУКЭ'),
    (0x23083, 12, 'AKUTSU HIDEO',              'АКУЦУ ХИДЭО'),
    (0x23092, 20, 'MONBETSU NO HITOBITO',      'ЖИТЕЛИ МОМБЭЦУ'),
    (0x230A8, 13, '   HOKURYUKAI',             'ХОКУРЮКАЙ'),
    (0x230B8, 12, 'NOMURA GENJI',              'Н. ГЭНДЗИ'),

    (0x230C7, 5,  'STORY',                     'СЮЖЕТ'),
    (0x230CE, 10, 'HORII YUJI',                'ХОРИИ Ю.'),
    (0x230DB, 13, '     GRAPHICS',             'ГРАФИКА'),
    (0x230EA, 13, 'ARAI KIYOKAZU',             'АРАИ КИЁКАДЗУ'),
    (0x230FA, 5,  'MUSIC',                     'МУЗ.'),
    (0x23101, 14, 'UENO TOSHIYUKI',            'УЭНО ТОСИЮКИ'),
    (0x23112, 13, '      PROGRAM',             'ПРОГРАММА'),
    (0x23121, 16, 'NAKASHIMA NARUMI',          'НАКАСИМА НАРУМИ'),
    (0x23134, 15, 'SCENARIO ASSIST',           'ПОМОЩЬ СЦЕН.'),
    (0x23145, 18, 'YANAGISAWA KENICHI',        'ЯНАГИСАВА КЭНИТИ'),
    (0x2315A, 17, 'GRAPHICS DIGITIZE',         'ОЦИФРОВКА ГРАФ.'),
    (0x2316D, 15, 'HONTANI HIROAKI',           'ХОНТАНИ ХИРОАКИ'),
    (0x2317F, 17, 'SATSUJIN NO THEME',         'ТЕМА УБИЙСТВА'),
    (0x23192, 12, 'YABU AKIHIKO',              'ЯБУ АКИХИКО'),
    (0x231A1, 13, 'SOUND EFFECTS',             'ЗВУК. ЭФФЕКТЫ'),
    (0x231B0, 20, 'HASHISHITA TOMOSHIGE',      'ХАСИСИТА ТОМОСИГЭ'),
    (0x231C7, 13, 'MUSIC PROGRAM',             'МУЗ. ПРОГРАМ.'),
    (0x231D6, 17, 'OGIWARA MITSUNORI',         'ОГИВАРА МИЦУНОРИ'),
    (0x231E9, 15, 'WATANABE TAKUYA',           'ВАТАНАБЭ ТАКУЯ'),
    (0x231FB, 14, 'PROGRAM ASSIST',            'ПОМОЩЬ ПРОГР.'),
    (0x2320B, 14, 'YONEZUKA MASAE',            'ЁНЭДЗУКА МАСАЭ'),
    (0x2321C, 6,  'ASSIST',                    'ПОМОЩЬ'),
    (0x23224, 12, 'TAMURA YUKIO',              'ТАМУРА ЮКИО'),
    (0x23232, 16, 'KITAHARA YASUSHI',          'КИТАХАРА ЯСУСИ'),
    (0x23244, 12, 'TSUBOI RYOKO',              'ЦУБОИ РЁКО'),
    (0x23253, 18, 'PROGRAM COORDINATE',        'КООРД. ПРОГРАМ.'),
    (0x23267, 13, ' SAIDA EIICHI',             'САИДА ЭЙИТИ'),
    (0x23277, 11, 'LOGO DESIGN',               'ДИЗАЙН ЛОГО'),
    (0x23284, 11, 'SATO HIDETO',               'САТО ХИДЭТО'),
    (0x23292, 13, '  FONT DESIGN',             'ДИЗАЙН ШРИФ.'),
    (0x232A1, 15, 'FUTATSUGI YASUO',           'ФУТАЦУГИ ЯСУО'),
    (0x232B3, 9,  'TEST GAME',                 'ТЕСТ ИГРЫ'),
    (0x232BE, 14, 'SUZUKI HIROAKI',            'СУЗУКИ ХИРОАКИ'),
    (0x232CE, 15, 'KAWAJIRI KAKUEI',           'КАВАДЗИРИ К.'),
    (0x232E0, 13, '      PROMOTE',             'РЕКЛАМА'),
    (0x232EF, 15, 'HORII TOSHIYUKI',           'ХОРИИ ТОСИЮКИ'),
    (0x23300, 13, 'AKIMOTO SYUJI',             'АКИМОТО СЮДЗИ'),
    (0x23310, 7,  'PRODUCE',                   'ПРОДЮС.'),
    (0x23319, 13, 'SHIOZAKI GOZO',             'СИОДЗАКИ Г.'),
    (0x23329, 21, 'AND SPECIAL THANKS TO',     'ОСОБАЯ БЛАГОДАРНОСТЬ'),
    (0x23340, 15, 'KOJIMA FUMITAKA',           'КОДЗИМА ФУМИТ.'),
    (0x23353, 20, '@ 1987 ARMOR PROJECT',      '@ 1987 АРМОР ПРОЕКТ'),
    (0x23369, 16, '@ 1987 LOGINSOFT',          '@ 1987 ЛОГИНСОФТ'),
]


def _decode_font_resource(prg: bytes) -> tuple[bytes, int]:
    out = bytearray(); i = TITLE_FONT_PRG
    while i < len(prg):
        c = prg[i]; i += 1
        if c == 0x81:
            break
        if c == 0 or c == 0x82:
            raise ValueError(f'title font: invalid/reserved packet ${c:02X} at PRG ${i-1:05X}')
        if c & 0x80:
            n = c & 0x7F
            if n < 3 or i >= len(prg):
                raise ValueError('title font: malformed RLE packet')
            out.extend([prg[i]] * n); i += 1
        else:
            n = c
            if i + n > len(prg):
                raise ValueError('title font: truncated literal packet')
            out.extend(prg[i:i+n]); i += n
    else:
        raise ValueError('title font: missing $81 terminator')
    if len(out) != TITLE_FONT_RAW_SIZE:
        raise ValueError(f'title font: decoded {len(out):#x}, expected {TITLE_FONT_RAW_SIZE:#x}')
    if i != TITLE_FONT_END:
        raise ValueError(f'title font: source ended at PRG ${i:05X}, expected ${TITLE_FONT_END:05X}')
    return bytes(out), i


def _encode_font_resource(font: bytes) -> bytes:
    if len(font) != TITLE_FONT_RAW_SIZE:
        raise ValueError('bad title font size')
    out = bytearray()
    for i in range(0, len(font), 32):
        out.append(32)
        out.extend(font[i:i+32])
    out.append(0x81)
    assert len(out) == TITLE_FONT_PACKED_SIZE
    return bytes(out)


def _glyph_from_main_font(main_font: bytes, ch: str) -> bytes:
    if ch == '.':
        code = 0x3F
    else:
        try:
            code = RU_UPPER_ENC[ch]
        except KeyError:
            raise ValueError(f'No main-font glyph for {ch!r}') from None
    tile = main_font[code*16:(code+1)*16]
    if len(tile) != 16:
        raise ValueError(f'Bad main-font tile for {ch!r}')
    # Shared title/staff font is 1bpp-looking data in NES 2bpp tile format:
    # glyph in plane 0, plane 1 clear.
    return tile[:8] + b'\x00' * 8


def _encode_title(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch == ' ':
            out.append(0)
        elif ch.isdigit():
            d = int(ch)
            if d not in (1, 7, 8, 9):
                raise ValueError(f'title digit {ch} was repurposed by Cyrillic font')
            out.append(0x80 + d)
        elif ch == '@':
            out.append(0x8A)
        elif ch in RU_TO_RAW:
            out.append(0x80 + RU_TO_RAW[ch])
        else:
            raise ValueError(f'Unsupported title character: {ch!r}')
    return bytes(out)


def _encode_title_old(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch == ' ': out.append(0)
        elif ch.isdigit(): out.append(0x80 + int(ch))
        elif ch == '@': out.append(0x8A)
        elif 'A' <= ch <= 'Z': out.append(0x8B + ord(ch) - ord('A'))
        else: raise ValueError(ch)
    return bytes(out)


def _title_data_states() -> tuple[bytes, bytes, bytes]:
    old = b''.join((
        _encode_title_old('GAME START'),
        _encode_title_old('CONTINUE'),
        _encode_title_old('@ 1987 ARMOR PROJECT'),
        _encode_title_old('@ 1987 LOGINSOFT'),
    ))
    v089 = b''.join((
        _encode_title('НОВАЯ ИГРА'),
        _encode_title('ПРОДОЛЖ.'),
        _encode_title('@ 1987 АРМОР ПРОЕКТ '),
        _encode_title('@ 1987 ЛОГИНСОФТ'),
    ))
    new = b''.join(_encode_title(x[4]) for x in TITLE_FIELDS)
    assert len(old) == len(v089) == len(new) == TITLE_DATA_SIZE
    return old, v089, new


def _encode_credit(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch == ' ':
            out.append(0)
        elif ch.isdigit():
            d = int(ch)
            if d not in (1, 7, 8, 9):
                raise ValueError(f'credit digit {ch} was repurposed by Cyrillic font')
            out.append(d + 1)
        elif ch == '@':
            out.append(0x0B)
        elif ch in RU_TO_RAW:
            out.append(RU_TO_RAW[ch] + 1)
        else:
            raise ValueError(f'Unsupported credit character: {ch!r}')
    if any(x > 0x25 for x in out):
        raise AssertionError('localized staff text escaped the original printable code range')
    return bytes(out)


def _encode_credit_old(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch == ' ': out.append(0)
        elif ch.isdigit(): out.append(int(ch)+1)
        elif ch == '@': out.append(0x0B)
        elif 'A' <= ch <= 'Z': out.append(0x0C + ord(ch)-ord('A'))
        else: raise ValueError(ch)
    return bytes(out)


def _fit(original: str, target: str, width: int) -> str:
    if len(target) > width:
        raise ValueError(f'{target!r} is {len(target)} chars, field width is {width}')
    # Original leading blanks are intentional right-alignment.
    return target.rjust(width) if original.startswith(' ') else target.ljust(width)


def patch(raw: bytes, *, font_path: str | Path | None = None, allow_already_patched: bool = True) -> bytes:
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    if raw[4] != 16:
        raise ValueError(f'Expected 16 PRG banks, got {raw[4]}')
    prg_off = 16 + (512 if raw[6] & 4 else 0)
    out = bytearray(raw)
    prg = bytearray(out[prg_off:prg_off + 16*0x4000])

    if font_path is None:
        font_path = Path(__file__).resolve().parents[1] / 'assets' / 'font_ru.bin'
    main_font = Path(font_path).read_bytes()
    if len(main_font) < 0x800:
        raise ValueError(f'Russian main font is too short: {len(main_font)}')

    # 1) Shared title/staff Latin font -> Cyrillic glyph set.
    font, _ = _decode_font_resource(bytes(prg))
    fbuf = bytearray(font)
    for ch, raw_idx in RU_TO_RAW.items():
        fbuf[raw_idx*16:(raw_idx+1)*16] = _glyph_from_main_font(main_font, ch)
    packed = _encode_font_resource(bytes(fbuf))
    prg[TITLE_FONT_PRG:TITLE_FONT_END] = packed

    # 2) Title/start-menu strings + descriptors. Keep the whole slab the same
    # size, but give CONTINUE two extra tiles by shortening the ARMOR line.
    old_data, v089_data, new_data = _title_data_states()
    cur_desc = bytes(prg[TITLE_DESC_PRG:TITLE_DATA_PRG])
    cur_data = bytes(prg[TITLE_DATA_PRG:TITLE_DATA_PRG + TITLE_DATA_SIZE])
    if cur_desc == TITLE_DESC_NEW and cur_data == new_data and allow_already_patched:
        pass
    elif cur_desc == TITLE_DESC_OLD and cur_data in (old_data, v089_data):
        prg[TITLE_DESC_PRG:TITLE_DATA_PRG] = TITLE_DESC_NEW
        prg[TITLE_DATA_PRG:TITLE_DATA_PRG + TITLE_DATA_SIZE] = new_data
    else:
        raise ValueError(
            'title table: unexpected descriptor/data state at PRG '
            f'${TITLE_DESC_PRG:05X}-${TITLE_DATA_PRG + TITLE_DATA_SIZE - 1:05X}'
        )

    # 3) Post-intro cards. They use the same tile codes as the title font.
    old_login = _encode_title_old(INTRO_LOGIN_OLD)
    new_login_text = INTRO_LOGIN_RU.center(INTRO_LOGIN_WIDTH)
    new_login = _encode_title(new_login_text)
    cur_desc = bytes(prg[INTRO_LOGIN_DESC_PRG:INTRO_LOGIN_DESC_PRG+8])
    a = INTRO_LOGIN_DATA_PRG
    b = a + INTRO_LOGIN_WIDTH
    cur_login = bytes(prg[a:b])

    if cur_desc == INTRO_LOGIN_DESC and cur_login == new_login and allow_already_patched:
        pass
    elif cur_desc == INTRO_LOGIN_DESC and cur_login == old_login:
        prg[a:b] = new_login
    elif cur_desc == INTRO_LOGIN_DESC_BAD_V0812:
        # Repair the bad v0.8.12 relocation before returning to the original
        # 18-tile descriptor/data field.  The 64 bytes are a proven original
        # scene-attribute source table, not free space.
        bad = _encode_title(INTRO_LOGIN_BAD_RU)
        q = INTRO_LOGIN_BAD_DATA_PRG
        if bytes(prg[q:q+len(bad)]) != bad:
            raise ValueError('v0.8.12 repair: relocated LOGINSOFT payload does not match expected bytes')
        prg[SCENE_ATTR_TABLE_PRG:SCENE_ATTR_TABLE_PRG+len(SCENE_ATTR_TABLE_ORIG)] = SCENE_ATTR_TABLE_ORIG
        prg[INTRO_LOGIN_DESC_PRG:INTRO_LOGIN_DESC_PRG+8] = INTRO_LOGIN_DESC
        prg[a:b] = new_login
    else:
        raise ValueError(
            f'intro LOGINSOFT card: unexpected descriptor/data state at PRG ${INTRO_LOGIN_DESC_PRG:05X}'
        )

    if bytes(prg[INTRO_MYSTERY_DESC_PRG:INTRO_MYSTERY_DESC_PRG+8]) != INTRO_MYSTERY_DESC:
        raise ValueError(f'intro Yuji Horii card: unexpected descriptor at PRG ${INTRO_MYSTERY_DESC_PRG:05X}')
    old_mystery = _encode_title_old(INTRO_MYSTERY_OLD)
    new_mystery_text = INTRO_MYSTERY_RU.center(INTRO_MYSTERY_WIDTH)
    new_mystery = _encode_title(new_mystery_text)
    a, b = INTRO_MYSTERY_DATA_PRG, INTRO_MYSTERY_DATA_PRG + INTRO_MYSTERY_WIDTH
    cur = bytes(prg[a:b])
    if cur == new_mystery and allow_already_patched:
        pass
    elif cur == old_mystery:
        prg[a:b] = new_mystery
    else:
        raise ValueError(f'intro Yuji Horii card: unexpected data at PRG ${a:05X}: {cur.hex(" ")}')

    # 4) Ending staff-roll fields, preserving every original field/control offset.
    for poff, width, old, new in CREDIT_FIELDS:
        fitted = _fit(old, new, width)
        a, b = poff, poff + width
        cur = bytes(prg[a:b])
        oldb, newb = _encode_credit_old(old), _encode_credit(fitted)
        if len(oldb) != width or len(newb) != width:
            raise AssertionError((poff, width, old, fitted))
        if cur == newb and allow_already_patched:
            continue
        if cur != oldb:
            raise ValueError(f'credits {old!r}: unexpected bytes at PRG ${poff:05X}: {cur.hex(" ")}')
        prg[a:b] = newb

    out[prg_off:prg_off + len(prg)] = prg
    return bytes(out)


def decode_localized_title_field(prg: bytes, poff: int, width: int) -> str:
    inv = {0x80 + v: k for k, v in RU_TO_RAW.items()}
    res=[]
    for b in prg[poff:poff+width]:
        if b == 0: res.append(' ')
        elif b in inv: res.append(inv[b])
        elif 0x80 <= b <= 0x89: res.append(str(b-0x80))
        elif b == 0x8A: res.append('@')
        else: res.append(f'<{b:02X}>')
    return ''.join(res)


def decode_localized_credit_field(prg: bytes, poff: int, width: int) -> str:
    inv = {v+1:k for k,v in RU_TO_RAW.items()}
    res=[]
    for b in prg[poff:poff+width]:
        if b == 0: res.append(' ')
        elif b in inv: res.append(inv[b])
        elif 1 <= b <= 10: res.append(str(b-1))
        elif b == 0x0B: res.append('@')
        else: res.append(f'<{b:02X}>')
    return ''.join(res)


def main():
    ap = argparse.ArgumentParser(description='Patch Okhotsk title/start menu and ending staff roll to Russian.')
    ap.add_argument('rom')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--font',default=None,help='Russian main font .bin (default: package assets/font_ru.bin)')
    args = ap.parse_args()
    raw = Path(args.rom).read_bytes()
    out = patch(raw, font_path=args.font)
    Path(args.out).write_bytes(out)
    print('Patched title: НОВАЯ ИГРА / ПРОДОЛЖИТЬ / copyright')
    print('Patched post-intro cards: ЛОГИНСОФТ ПРЕДСТ. / ДЕТЕКТИВ ЮДЗИ ХОРИИ')
    print('Patched ending: cast, staff roles, names and copyright')
    print('Wrote:', args.out)

if __name__ == '__main__':
    main()
