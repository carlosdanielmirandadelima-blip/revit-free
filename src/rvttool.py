#!/usr/bin/env python3
"""rvttool — leitor de arquivos .rvt (Autodesk Revit) sem o Revit.

Descoberta central (ver README.md): o .rvt é um OLE Compound File cujos streams
são sequências de registros gzip com janela deflate COMPARTILHADA entre registros:

    [10B header gzip][deflate raw][8B CRC+ISIZE][32B rodapé] [próximo registro]...

Descomprimir cada registro isolado falha ("invalid distance too far back") porque
o deflate continua a janela do anterior. Solução: zdict = últimos 32 KB do output
do registro anterior.

Uso:
    python3 rvttool.py lista  arquivo.rvt           — lista streams e tamanhos
    python3 rvttool.py dump   arquivo.rvt STREAM    — descomprime stream para stdout/arquivo
    python3 rvttool.py info   arquivo.rvt           — metadados do projeto
    python3 rvttool.py strings arquivo.rvt STREAM   — strings UTF-16 legíveis
"""
import io
import json
import olefile
import re
import struct
import sys
import zlib


def u32(b, o):
    return int.from_bytes(b[o:o + 4], 'little')


def decompress_stream(data):
    """Descomprime um stream .rvt (sequência de registros gzip encadeados).

    Retorna (bytes, n_registros, n_falhas).
    """
    # localizar primeiro magic gzip
    p = data.find(b'\x1f\x8b\x08')
    if p < 0:
        return data, 0, 0  # stream não comprimido
    total = bytearray()
    prev_out = b''
    n = ok = fail = 0
    while p >= 0 and p + 3 <= len(data) and data[p:p + 3] == b'\x1f\x8b\x08':
        zdict = prev_out[-32768:] if prev_out else b''
        do = zlib.decompressobj(-15, zdict=zdict)
        payload = data[p + 10:]
        try:
            out = do.decompress(payload)
            ok += 1
        except zlib.error:
            out = b''
            fail += 1
        consumed = len(payload) - len(do.unused_data) - len(do.unconsumed_tail)
        end = p + 10 + consumed
        total += out
        if out:
            prev_out = out
        # próximo registro: fim do deflate + 40 (trailer+rodapé) se cair em magic
        nxt = data.find(b'\x1f\x8b\x08', p + 10)
        cand = end + 40
        if cand <= len(data) and data[cand:cand + 3] == b'\x1f\x8b\x08':
            nxt = cand
        p = nxt
        n += 1
        if n > 200000:
            break
    return bytes(total), n, fail


def read_stream(rvt_path, stream):
    with olefile.OleFileIO(rvt_path) as f:
        raw = f.openstream(stream).read()
    return decompress_stream(raw)


def cmd_lista(rvt):
    with olefile.OleFileIO(rvt) as f:
        for s in sorted(f.listdir()):
            name = '/'.join(s)
            size = f.get_size(name)
            print(f'{size:>12,}  {name}')


def cmd_dump(rvt, stream, outfile=None):
    data, n, fail = read_stream(rvt, stream)
    print(f'{stream}: {n} registros, {fail} falhas, {len(data):,} bytes descomprimidos',
          file=sys.stderr)
    if outfile:
        open(outfile, 'wb').write(data)
        print(f'salvo em {outfile}', file=sys.stderr)
    else:
        sys.stdout.buffer.write(data)


def cmd_info(rvt):
    info = {}
    try:
        data, _, _ = read_stream(rvt, 'BasicFileInfo')
        # BasicFileInfo costuma ter texto com versão/paths
        txt = data.decode('utf-8', errors='replace')
        info['basicFileInfo'] = txt[:2000]
    except Exception as e:
        info['basicFileInfo'] = f'erro: {e}'
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_strings(rvt, stream, min_len=6):
    data, n, fail = read_stream(rvt, stream)
    print(f'{stream}: {n} registros, {fail} falhas, {len(data):,} bytes',
          file=sys.stderr)
    pat = ('(?:[ -~\xc0-\xff]\x00){%d,}' % min_len).encode()
    seen = set()
    for m in re.finditer(pat, data):
        t = m.group().decode('utf-16-le', errors='replace')
        if t not in seen:
            seen.add(t)
            print(t)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd, rvt = sys.argv[1], sys.argv[2]
    if cmd == 'lista':
        cmd_lista(rvt)
    elif cmd == 'dump':
        cmd_dump(rvt, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == 'info':
        cmd_info(rvt)
    elif cmd == 'strings':
        cmd_strings(rvt, sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 6)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
