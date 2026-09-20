#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse, sys, zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import katte_codec as kc

H = 16
BANK = 0x4000
EXT = 0x54

# Final-RU direct-render map. Control opcodes take precedence over glyphs.
RU_INV = {}
for ch, b in kc.RU_CHAR_TO_BYTE.items():
    if ch not in ('-', '—'):
        RU_INV[b] = ch
RU_INV.update({0xB2:'「', 0xB4:'-', 0xB6:'!', 0xB7:'?', 0xBB:'.', 0xFF:' '})
RU_INV.update({0xF2+i:str(i) for i in range(10)})


def cstr(rom: bytes, off: int, limit: int) -> bytes:
    end = rom.find(b'\0', off, limit)
    if end < 0:
        raise ValueError(f'No NUL terminator at file ${off:X}')
    return rom[off:end]


def final_b1_raw(rom: bytes, idx: int):
    block = kc.BLOCKS['B1']
    po = block.pointer_table + idx*2
    ptr = rom[po] | (rom[po+1] << 8)
    stub = ptr + block.pointer_delta
    if stub + 4 > len(rom) or rom[stub] != EXT:
        raise ValueError(f'B1:{idx:03d}: expected far-text stub at file ${stub:X}')
    bank = rom[stub+1]
    cpu = rom[stub+2] | (rom[stub+3] << 8)
    if not (8 <= bank <= 14 and 0x8000 <= cpu < 0xC000):
        raise ValueError(f'B1:{idx:03d}: invalid far target bank={bank} cpu=${cpu:04X}')
    off = H + bank*BANK + (cpu-0x8000)
    raw = cstr(rom, off, H+(bank+1)*BANK)
    return po, off, raw, bank, cpu


def decode_ru_direct(raw: bytes) -> str:
    out=[]
    for b in raw:
        if b in kc.BYTE_TO_CONTROL:
            out.append('{'+kc.BYTE_TO_CONTROL[b]+'}')
        elif b in RU_INV:
            out.append(RU_INV[b])
        else:
            out.append(f'{{{b:02X}}}')
    return ''.join(out)


def decode_ru_b1(raw: bytes, idx: int, d_raw: list[bytes]) -> str:
    out=[]
    special = {0x0D,0x1E,0x47,0x11,0x45}
    if 813 <= idx <= 889:
        special |= set(range(0x5B,0x60))
    for b in raw:
        if b in kc.BYTE_TO_CONTROL:
            out.append('{'+kc.BYTE_TO_CONTROL[b]+'}')
        elif b in special:
            out.append(f'{{{b:02X}}}')
        elif 0x05 <= b <= 0x5F:
            di = b-5
            if di < len(d_raw):
                ann = decode_ru_direct(d_raw[di]).replace('{','<').replace('}','>')
                out.append(f'{{D{di:02d}:{ann}}}')
            else:
                out.append(f'{{{b:02X}}}')
        elif b in RU_INV:
            out.append(RU_INV[b])
        else:
            out.append(f'{{{b:02X}}}')
    return ''.join(out)


def main():
    ap=argparse.ArgumentParser(description='Extract Katte ni Shirokuma text from original JP or FINAL expanded RU ROM')
    ap.add_argument('rom',type=Path)
    ap.add_argument('-o','--output',type=Path,default=Path('script_extracted.txt'))
    ap.add_argument('--mode',choices=['auto','jp','ru'],default='auto')
    a=ap.parse_args()

    rom=a.rom.read_bytes()
    if len(rom)<16 or rom[:4] != b'NES\x1a':
        raise SystemExit('Not an iNES ROM')
    prg=rom[4]
    mode=a.mode
    if mode=='auto':
        mode='ru' if prg >= 16 else 'jp'

    out=[]
    out.append('# Katte ni Shirokuma - editable text dump')
    out.append(f'# Source: {a.rom.name}')
    out.append(f'# Mode: {mode}; PRG banks: {prg}; CHR banks: {rom[5]}')
    out.append(f'# CRC32 whole ROM: {zlib.crc32(rom)&0xffffffff:08X}')
    out.append('# Keep @@ headers and @@END markers. Use {LN}/{NEXT}; raw controls are {XX}.')
    out.append('')

    if mode=='jp':
        dictionary=kc.build_dictionary(rom)
        for bname in ('B0','B1','D'):
            out.append(f'##### BLOCK {bname} #####')
            for idx,po,so,raw in kc.pointer_entries(rom,kc.BLOCKS[bname]):
                extra=f' CODE={idx+5:02X}' if bname=='D' else ''
                out.append(f'@@ {bname}:{idx:03d} PTR={po:X} STR={so:X} LEN={len(raw)}{extra}')
                out.append(kc.decode_direct(raw) if bname=='D' else kc.decode(raw,dictionary,expand_dict=True))
                out.append('@@END');out.append('')
    else:
        # D first so B1 dictionary annotations can be decoded using current RU glyphs.
        d_entries=kc.pointer_entries(rom,kc.BLOCKS['D'])
        d_raw=[raw for _,_,_,raw in d_entries]
        for bname in ('B0','B1','D'):
            out.append(f'##### BLOCK {bname} #####')
            if bname=='B1':
                for idx in range(kc.BLOCKS['B1'].count):
                    po,so,raw,bank,cpu=final_b1_raw(rom,idx)
                    out.append(f'@@ B1:{idx:03d} PTR={po:X} STR={so:X} LEN={len(raw)}')
                    out.append(decode_ru_b1(raw,idx,d_raw))
                    out.append('@@END');out.append('')
            else:
                for idx,po,so,raw in kc.pointer_entries(rom,kc.BLOCKS[bname]):
                    extra=f' CODE={idx+5:02X}' if bname=='D' else ''
                    out.append(f'@@ {bname}:{idx:03d} PTR={po:X} STR={so:X} LEN={len(raw)}{extra}')
                    out.append(decode_ru_direct(raw))
                    out.append('@@END');out.append('')

    a.output.write_text('\n'.join(out),encoding='utf-8')
    print(f'Wrote {a.output}; entries={sum(1 for x in out if x=="@@END")}; mode={mode}')

if __name__=='__main__':
    main()
