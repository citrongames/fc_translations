#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from okhotsk_common import read_ines, PRG_BANK_SIZE
from ru_dictionary import EXTRA_DICT_CPU

# Fixed-bank dispatcher: high nibbles D and E originally point to $C79C and
# $C7AF. v0.8 routes both to a shared secondary-dictionary handler at $C79C.
PRG_BANK=15; BANK_CPU_BASE=0xC000
JUMP_D_ADDR=0xC65A
JUMP_E_ADDR=0xC65C
HANDLER_ADDR=0xC79C
ORIG_JUMP_D=bytes.fromhex('9C C7')
ORIG_JUMP_E=bytes.fromhex('AF C7')
PATCH_JUMP=bytes.fromhex('9C C7')
# C79C..C7B7 = old D handler (19 bytes) + old E handler (9 bytes) = 28 bytes.
ORIG_HANDLER=bytes.fromhex(
    'A9 00 85 6B 8A 29 0F 18 69 74 85 6C 20 A5 C6 20 9A C6 60 '
    '8A 29 0F 85 55 20 9A C6 60')


def make_handler():
    lo=EXTRA_DICT_CPU&0xFF; hi=(EXTRA_DICT_CPU>>8)&0xFF
    # Mirror the original dictionary prologue exactly: select bank A, advance
    # the caller source past the token, and push one source-stack level. Then
    # map D0..EF -> synthetic 60..7F, install the secondary table base, and
    # jump to C76E (LDY #0 + the original FF-delimited entry scanner).
    code=bytes([
        0xA9,0x0A,             # LDA #$0A
        0x20,0xF4,0xFE,        # JSR $FEF4 (select text bank A)
        0x20,0x9A,0xC6,        # JSR $C69A (advance caller source)
        0xE6,0x5A,             # INC $5A (push dictionary source level)
        0xA5,0x57,             # LDA $57
        0x38,                  # SEC
        0xE9,0x70,             # SBC #$70 : D0->60, EF->7F
        0x85,0x57,             # STA $57
        0xA9,lo, 0x85,0x14,    # secondary base low
        0xA9,hi, 0x85,0x15,    # secondary base high
        0x4C,0x6E,0xC7,        # JMP $C76E (LDY #0; scan entry; install source)
    ])
    if len(code)!=len(ORIG_HANDLER):
        raise AssertionError(f'extended dictionary handler must be exactly {len(ORIG_HANDLER)} bytes, got {len(code)}')
    return code

PATCH_HANDLER=make_handler()


def patch(data:bytes)->bytes:
    info=read_ines_bytes(data); out=bytearray(data)
    def off(cpu): return info['prg_offset']+PRG_BANK*PRG_BANK_SIZE+(cpu-BANK_CPU_BASE)
    od,oe,oh=off(JUMP_D_ADDR),off(JUMP_E_ADDR),off(HANDLER_ADDR)
    curd=bytes(out[od:od+2]); cure=bytes(out[oe:oe+2]); curh=bytes(out[oh:oh+len(ORIG_HANDLER)])
    already=(curd==PATCH_JUMP and cure==PATCH_JUMP and curh==PATCH_HANDLER)
    if already:return data
    if curd not in (ORIG_JUMP_D,PATCH_JUMP):raise ValueError(f'unexpected D dispatch bytes: {curd.hex(" ")}')
    if cure not in (ORIG_JUMP_E,PATCH_JUMP):raise ValueError(f'unexpected E dispatch bytes: {cure.hex(" ")}')
    if curh!=ORIG_HANDLER:raise ValueError(f'unexpected D/E handler bytes at ${HANDLER_ADDR:04X}: {curh.hex(" ").upper()}')
    out[od:od+2]=PATCH_JUMP;out[oe:oe+2]=PATCH_JUMP;out[oh:oh+len(PATCH_HANDLER)]=PATCH_HANDLER
    return bytes(out)


def read_ines_bytes(raw:bytes):
    if len(raw)<16 or raw[:4]!=b'NES\x1a':raise ValueError('Not an iNES ROM')
    return {'prg_offset':16+(512 if raw[6]&4 else 0)}


def main():
    ap=argparse.ArgumentParser(description='Repurpose text bytes D0..EF as 32 secondary Russian dictionary tokens.')
    ap.add_argument('rom');ap.add_argument('-o','--out',required=True);a=ap.parse_args()
    out=patch(Path(a.rom).read_bytes());Path(a.out).write_bytes(out)
    print(f'Patched D/E dispatch -> secondary dictionary at CPU ${EXTRA_DICT_CPU:04X}; D0..EF = 32 dictionary tokens')
    print('Wrote:',a.out)
if __name__=='__main__':main()
