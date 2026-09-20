#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from okhotsk_common import DIRECT, hira_to_kata, decode_bytes

# Fixed-bank static analysis of F0..FF dispatch (CPU $C7B8 table at $C7C6).
# Number below is the count of immediate bytes consumed AFTER the control byte.
# F0 is variable length and is handled separately. FF terminates/returns.
F_ARG_COUNTS = {
    0xF1: 1,
    0xF2: 2,  # little-endian text-region address; pushes a nested text source
    0xF3: 0,
    0xF4: 0,
    0xF5: 2,
    0xF6: 1,
    0xF7: 0,
    0xF8: 0,
    0xF9: 0,
    0xFA: 0,
    0xFB: 1,
    0xFC: 1,
    0xFD: 1,
    0xFE: 0,
}

@dataclass
class Op:
    offset: int
    code: int
    args: bytes = b''

    @property
    def size(self) -> int:
        return 1 + len(self.args)


def _need(region: bytes, i: int, n: int, start: int):
    if i + n > len(region):
        raise ValueError(f'truncated stream at 0x{i:04X} (start 0x{start:04X})')


def parse_stream(region: bytes, start: int, *, max_len: int = 0x4000) -> tuple[bytes, list[Op], bool]:
    """Parse ONE source stream until its own FF.

    Important: FF bytes that are F-command arguments are not terminators. F2 nested
    targets are not expanded here; the returned stream is only the bytes physically
    stored at *start*.
    """
    if not (0 <= start < len(region)):
        return b'', [], False
    i = start
    ops: list[Op] = []
    while i < len(region) and i - start < max_len:
        pos = i
        code = region[i]
        i += 1
        if code == 0xFF:
            ops.append(Op(pos, code))
            return region[start:i], ops, True
        if code < 0xF0:
            ops.append(Op(pos, code))
            continue
        if code == 0xF0:
            # C7E6: read bytes until one with bit7 set; that last byte belongs to F0.
            args = bytearray()
            while True:
                _need(region, i, 1, start)
                x = region[i]
                i += 1
                args.append(x)
                if x & 0x80:
                    break
                if i - start >= max_len:
                    return region[start:i], ops + [Op(pos, code, bytes(args))], False
            ops.append(Op(pos, code, bytes(args)))
            continue
        n = F_ARG_COUNTS.get(code)
        if n is None:
            # Should only be FF, handled above. Preserve unknown future F-command safely.
            ops.append(Op(pos, code))
            continue
        _need(region, i, n, start)
        args = region[i:i+n]
        i += n
        ops.append(Op(pos, code, args))
    return region[start:i], ops, False


def stream_refs_f2(ops: Iterable[Op]) -> list[int]:
    out = []
    for op in ops:
        if op.code == 0xF2 and len(op.args) == 2:
            out.append(op.args[0] | (op.args[1] << 8))
    return out


def stream_control_codes(ops: Iterable[Op]) -> list[int]:
    return [op.code for op in ops if op.code >= 0xF0 and op.code != 0xFF]


def _fmt_args(args: bytes) -> str:
    return ','.join(f'${b:02X}' for b in args)


def control_marker(op: Op) -> str:
    c = op.code
    if c == 0xF0:
        return f'[F0:{_fmt_args(op.args)}]'
    if c == 0xF1:
        return f'[F1:${op.args[0]:02X}]'
    if c == 0xF2:
        target = op.args[0] | (op.args[1] << 8)
        return f'[F2:${target:04X}]'
    if c == 0xF3:
        return '[F3]'
    if c == 0xF4:
        return '[F4]'
    if c == 0xF5:
        return f'[F5:${op.args[0]:02X},${op.args[1]:02X}]'
    if c == 0xF6:
        return f'[F6:${op.args[0]:02X}]'
    if c == 0xF7:
        return '[F7]'
    if c == 0xF8:
        return '\n'
    if c == 0xF9:
        return '[F9]'
    if c == 0xFA:
        return '[FA]'
    if c == 0xFB:
        return f'[FB:${op.args[0]:02X}]'
    if c == 0xFC:
        return f'[FC:${op.args[0]:02X}]'
    if c == 0xFD:
        return f'[FD:${op.args[0]:02X}]'
    if c == 0xFE:
        return '[FE]'
    if c == 0xFF:
        return ''
    return f'[RAW:${c:02X}]'


def _decode_sequence(data: bytes, pos: int, dict_entries, *, region: bytes,
                     expand_f2: bool, state: dict, stop_on_ff: bool,
                     max_depth: int, depth: int, seen: tuple[int, ...]) -> tuple[str, int]:
    """Interpret the text bytecode for display, sharing E-run state through dictionary macros."""
    out=[]
    while pos < len(data):
        b=data[pos]; pos += 1
        if b == 0xFF and stop_on_ff:
            break
        if b < 0x60:
            ch=DIRECT.get(b, f'[GLYPH:${b:02X}]')
            if state.get('eshift',0)>0:
                state['eshift'] -= 1
                ch=hira_to_kata(ch)
            out.append(ch); continue
        if 0x60 <= b <= 0xCF:
            idx=b-0x60
            if idx < len(dict_entries):
                # Dictionary entries are bytecode macros and may themselves contain F-controls.
                txt,_=_decode_sequence(dict_entries[idx],0,dict_entries,region=region,
                                       expand_f2=expand_f2,state=state,stop_on_ff=False,
                                       max_depth=max_depth,depth=depth+1,seen=seen)
                out.append(txt)
            else:
                out.append(f'[DICT:${b:02X}]')
            continue
        if 0xD0 <= b <= 0xDF:
            if state.get('eshift',0)>0: state['eshift']-=1
            out.append(f'[GLYPH:${b:02X}]'); continue
        if 0xE0 <= b <= 0xEF:
            state['eshift']=b&0x0F
            continue
        # F commands.
        if b == 0xF0:
            args=[]
            while pos < len(data):
                x=data[pos]; pos+=1; args.append(x)
                if x&0x80: break
            out.append(f'[F0:{_fmt_args(bytes(args))}]'); continue
        if b == 0xF1:
            if pos>=len(data): out.append('[F1:TRUNC]'); break
            x=data[pos]; pos+=1; out.append(f'[F1:${x:02X}]'); continue
        if b == 0xF2:
            if pos+2>len(data): out.append('[F2:TRUNC]'); break
            lo,hi=data[pos],data[pos+1]; pos+=2; target=lo|(hi<<8)
            if expand_f2 and 0<=target<len(region):
                if depth>=max_depth or target in seen:
                    out.append(f'[F2:${target:04X}:RECURSION]')
                else:
                    txt,_=_decode_sequence(region,target,dict_entries,region=region,
                                           expand_f2=True,state=state,stop_on_ff=True,
                                           max_depth=max_depth,depth=depth+1,seen=seen+(target,))
                    out.append(txt)
            else:
                out.append(f'[F2:${target:04X}]')
            continue
        if b in (0xF3,0xF4,0xF7,0xF9,0xFA,0xFE):
            out.append(f'[{b:02X}]'.replace('[F3]','[F3]').replace('[F4]','[F4]'))
            continue
        if b == 0xF5:
            if pos+2>len(data): out.append('[F5:TRUNC]'); break
            a,c=data[pos],data[pos+1]; pos+=2; out.append(f'[F5:${a:02X},${c:02X}]'); continue
        if b in (0xF6,0xFB,0xFC,0xFD):
            if pos>=len(data): out.append(f'[{b:02X}:TRUNC]'); break
            a=data[pos]; pos+=1; out.append(f'[{b:02X}:${a:02X}]'); continue
        if b == 0xF8:
            out.append('\n'); continue
        if b == 0xFF:
            if stop_on_ff: break
            out.append('[FF]'); continue
        out.append(f'[RAW:${b:02X}]')
    return ''.join(out),pos


def decode_stream_symbolic(region: bytes, start: int, dict_entries, *, expand_f2: bool = False,
                           max_depth: int = 12, _depth: int = 0, _seen: tuple[int, ...] = ()) -> str:
    state={'eshift':0}
    txt,_=_decode_sequence(region,start,dict_entries,region=region,expand_f2=expand_f2,
                           state=state,stop_on_ff=True,max_depth=max_depth,depth=_depth,
                           seen=_seen+(start,))
    return txt

def collect_f2_graph(region: bytes, roots: Iterable[int]) -> tuple[set[int], dict[int, list[int]]]:
    """Return all streams reachable through F2 plus an outgoing-reference map."""
    seen: set[int] = set()
    refs: dict[int, list[int]] = {}
    todo = list(dict.fromkeys(int(x) for x in roots if 0 <= int(x) < len(region)))
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        _, ops, _ = parse_stream(region, p)
        rr = [r for r in stream_refs_f2(ops) if 0 <= r < len(region)]
        refs[p] = rr
        for r in rr:
            if r not in seen:
                todo.append(r)
    return seen, refs
