#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse

from katte_codec import BLOCKS, check_rom, pointer_entries, parse_script, encode
from layout_check import check_layout, format_problem

# Confirmed unused padding inside B1's 32 KiB PRG window. These are optional
# overflow areas; the repacker prefers space released by edited strings first.
SAFE_FREE = {
    'B1': [
        (0x13FB7, 0x13FCC),
        (0x13FF0, 0x1400A),
        (0x17F89, 0x17FCC),
    ],
}


def merge_ranges(ranges):
    ranges = sorted((s, e) for s, e in ranges if e > s)
    out = []
    for s, e in ranges:
        if not out or s > out[-1][1]:
            out.append([s, e])
        else:
            out[-1][1] = max(out[-1][1], e)
    return [(s, e) for s, e in out]


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def write_ptr(rom: bytearray, po: int, so: int, delta: int):
    ptr = so - delta
    if not (0 <= ptr <= 0xFFFF):
        raise ValueError(f'New string address ${so:X} cannot be represented with delta ${delta:X}')
    rom[po] = ptr & 0xFF
    rom[po + 1] = (ptr >> 8) & 0xFF


def main():
    ap = argparse.ArgumentParser(
        description='Relocating inserter for Katte ni Shirokuma. '
                    'Reclaims storage of edited strings and recalculates their pointers.'
    )
    ap.add_argument('rom', type=Path, help='Original Japanese ROM')
    ap.add_argument('script', type=Path, help='Editable script dump')
    ap.add_argument('-o', '--output', type=Path, default=Path('katte_repacked.nes'))
    ap.add_argument('--no-crc-check', action='store_true')
    a = ap.parse_args()

    original = a.rom.read_bytes()
    check_rom(original, strict=not a.no_crc_check)
    rom = bytearray(original)
    parsed = parse_script(a.script)

    layout_problems = check_layout(parsed, width=16, rows=3, only_cyrillic=True)
    if layout_problems:
        print('Dialogue layout check failed:', flush=True)
        for problem in layout_problems:
            print('  ' + format_problem(problem), flush=True)
        raise SystemExit(f'Refusing to build: {len(layout_problems)} translated dialogue layout problem(s)')

    meta = {}
    for bname, block in BLOCKS.items():
        for idx, po, so, raw in pointer_entries(original, block):
            meta[(bname, idx)] = {
                'po': po, 'so': so, 'raw': raw,
                'span': (so, so + len(raw) + 1),
            }

    missing = [k for k in meta if k not in parsed]
    if missing:
        raise SystemExit(f'Missing entries in script, first: {missing[:5]}')

    encoded = {}
    changed = set()
    for k, m in meta.items():
        ent = parsed[k]
        if ent['ptr'] != m['po'] or ent['str'] != m['so'] or ent['len'] != len(m['raw']):
            raise SystemExit(f'Header metadata changed for {k}; restore PTR/STR/LEN')
        try:
            enc = encode(ent['text'])
        except Exception as ex:
            raise SystemExit(f'{k}: {ex}')
        encoded[k] = enc
        if enc != m['raw']:
            changed.add(k)

    # No changes means strict round-trip: write an identical ROM.
    if not changed:
        a.output.write_bytes(original)
        print(f'Wrote {a.output}; changed entries: 0; byte-identical pass')
        return

    placements = {}
    total_relocated = 0

    for bname, block in BLOCKS.items():
        keys = [k for k in meta if k[0] == bname]
        ckeys = [k for k in keys if k in changed]
        if not ckeys:
            continue

        unchanged_spans = [meta[k]['span'] for k in keys if k not in changed]

        # Refuse to reclaim bytes still used by an unchanged suffix/shared string.
        for k in ckeys:
            sp = meta[k]['span']
            conflicts = [uk for uk in keys if uk not in changed and overlaps(sp, meta[uk]['span'])]
            if conflicts:
                raise SystemExit(
                    f'{k} overlaps unchanged entries {conflicts[:8]}. '
                    f'Edit all sharing entries together or keep this one unchanged.'
                )

        # Storage released by changed entries. Adjacent changed strings merge into
        # one component, allowing one translated string to borrow space from another.
        released = merge_ranges(meta[k]['span'] for k in ckeys)

        # Assign each changed entry to the released component containing its old start.
        comp_items = {r: [] for r in released}
        for k in sorted(ckeys, key=lambda x: meta[x]['so']):
            old_so = meta[k]['so']
            owner = None
            for r in released:
                if r[0] <= old_so < r[1]:
                    owner = r
                    break
            if owner is None:
                raise SystemExit(f'Internal error: no released component for {k}')
            comp_items[owner].append(k)

        # Extra known-safe padding can receive a string if a local component is too small.
        overflow = [list(r) for r in SAFE_FREE.get(bname, [])]

        for comp in released:
            items = comp_items[comp]
            start, end = comp
            capacity = end - start

            # Exact duplicate translated strings may share one pointer.
            payload_groups = []
            by_payload = {}
            for k in items:
                payload = encoded[k] + b'\x00'
                by_payload.setdefault(payload, []).append(k)
            for payload, pkeys in by_payload.items():
                earliest = min(meta[k]['so'] for k in pkeys)
                payload_groups.append((earliest, payload, pkeys))
            payload_groups.sort(key=lambda x: x[0])

            need = sum(len(payload) for _, payload, _ in payload_groups)
            if need <= capacity:
                cursor = start
                for _, payload, pkeys in payload_groups:
                    rom[cursor:cursor + len(payload)] = payload
                    for k in pkeys:
                        placements[k] = cursor
                    cursor += len(payload)
                # Clear only the released tail; nothing unchanged points here.
                if cursor < end:
                    rom[cursor:end] = b'\x00' * (end - cursor)
                total_relocated += len(items)
                continue

            # If the component itself is insufficient, try placing individual payloads
            # into confirmed padding. We do not split a string across regions.
            if len(payload_groups) == 1:
                _, payload, pkeys = payload_groups[0]
                slot_i = None
                for i, (s, e) in enumerate(overflow):
                    if e - s >= len(payload):
                        slot_i = i
                        break
                if slot_i is not None:
                    s, e = overflow[slot_i]
                    rom[s:s + len(payload)] = payload
                    for k in pkeys:
                        placements[k] = s
                    overflow[slot_i][0] = s + len(payload)
                    rom[start:end] = b'\x00' * capacity
                    total_relocated += len(items)
                    continue

            raise SystemExit(
                f'{bname} released component ${start:X}-${end:X}: '
                f'need {need} bytes, have {capacity}. '
                f'Translate adjacent entries more compactly or expand the repack pool.'
            )

        # Recalculate pointers only for changed entries.
        for k in ckeys:
            write_ptr(rom, meta[k]['po'], placements[k], block.pointer_delta)

    a.output.write_bytes(rom)
    print(f'Wrote {a.output}; changed entries: {len(changed)}; relocated: {total_relocated}')
    for k in sorted(changed):
        old = meta[k]['so']
        new = placements[k]
        print(f'  {k[0]}:{k[1]:03d}  ${old:X} -> ${new:X}  {len(meta[k]["raw"])} -> {len(encoded[k])} bytes')


if __name__ == '__main__':
    main()
