#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

def decode(src: bytes, out_size: int | None=None):
 out=bytearray(); i=0
 while i<len(src) and (out_size is None or len(out)<out_size):
  c=src[i];i+=1
  if c==0: raise ValueError(f'Zero-length control at input 0x{i-1:X}')
  if c&0x80:
   n=c&0x7F
   if i>=len(src): raise ValueError('Truncated RLE run')
   v=src[i];i+=1;out.extend([v]*n)
  else:
   n=c
   if i+n>len(src): raise ValueError('Truncated literal')
   out.extend(src[i:i+n]);i+=n
 if out_size is not None:
  if len(out)!=out_size: raise ValueError(f'Decoded {len(out)} bytes, expected {out_size}')
 return bytes(out), i

def encode(data: bytes):
 return _emit_packets(_tokenize_for_encode(data))


def _tokenize_for_encode(data: bytes):
    """Return canonical packets as ('run', bytes) / ('lit', bytes)."""
    toks=[]; i=0; n=len(data)
    while i<n:
        run=1
        while i+run<n and data[i+run]==data[i] and run<127:
            run+=1
        if run>=3:
            toks.append(('run', data[i:i+run])); i+=run; continue
        start=i; i+=run
        while i<n and i-start<127:
            r=1
            while i+r<n and data[i+r]==data[i] and r<127:
                r+=1
            if r>=3 or i-start+r>127:
                break
            i+=r
        toks.append(('lit', data[start:i]))
    return toks

def _emit_packets(toks):
    out=bytearray()
    for kind, payload in toks:
        if kind=='run':
            if not 1 <= len(payload) <= 127 or len(set(payload)) != 1:
                raise ValueError('Invalid RLE run packet')
            out.extend((0x80|len(payload), payload[0]))
        else:
            if not 1 <= len(payload) <= 127:
                raise ValueError('Invalid RLE literal packet')
            out.append(len(payload)); out.extend(payload)
    return bytes(out)

def encode_exact_length(data: bytes, target_len: int):
    """Encode to an exact compressed byte length without changing output.

    Okhotsk keeps more than one compressed substream sequentially in some
    graphics blocks.  For those blocks it is unsafe to emit a *shorter* valid
    stream, because the runtime continues parsing at the byte immediately after
    the stream.  This helper starts from the canonical encoding and deliberately
    splits literal packets to add harmless packet-header bytes until target_len
    is reached.
    """
    toks=_tokenize_for_encode(data)
    base=_emit_packets(toks)
    if len(base)>target_len:
        raise ValueError(f'Canonical encoding is too large: {len(base)} > {target_len}')
    delta=target_len-len(base)
    if delta==0:
        return base
    expanded=[]
    for kind,payload in toks:
        if kind!='lit' or delta==0 or len(payload)==1:
            expanded.append((kind,payload)); continue
        # Splitting one literal packet into N packets adds exactly N-1 bytes
        # of compressed overhead while decoding to the exact same bytes.
        add=min(delta,len(payload)-1)
        for b in payload[:add]:
            expanded.append(('lit',bytes([b])))
        rest=payload[add:]
        if rest:
            expanded.append(('lit',rest))
        delta-=add
    if delta:
        raise ValueError(
            f'Cannot reach exact length {target_len} by safe literal splitting; '
            f'{delta} extra bytes still needed')
    out=_emit_packets(expanded)
    if len(out)!=target_len:
        raise AssertionError((len(out),target_len))
    # Internal safety check: exact round-trip and exact input consumption.
    dec,used=decode(out,len(data))
    if dec!=data or used!=len(out):
        raise AssertionError('Exact-length RLE self-check failed')
    return out

def main():
 ap=argparse.ArgumentParser(description='Okhotsk PackBits-like RLE primitive.')
 sub=ap.add_subparsers(dest='cmd',required=True)
 d=sub.add_parser('decode');d.add_argument('input');d.add_argument('output');d.add_argument('--size',type=lambda x:int(x,0))
 e=sub.add_parser('encode');e.add_argument('input');e.add_argument('output')
 x=sub.add_parser('encode-exact');x.add_argument('input');x.add_argument('output');x.add_argument('--length',required=True,type=lambda v:int(v,0))
 a=ap.parse_args();src=Path(a.input).read_bytes()
 if a.cmd=='decode':
  out,used=decode(src,a.size);print('input bytes used:',used)
 elif a.cmd=='encode-exact':
  out=encode_exact_length(src,a.length)
 else:
  out=encode(src)
 Path(a.output).write_bytes(out);print(f'{len(src)} -> {len(out)} bytes')
if __name__=='__main__':main()
