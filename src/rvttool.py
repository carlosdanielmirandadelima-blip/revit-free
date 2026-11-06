#!/usr/bin/env python3
"""rvttool — leitor de arquivos .rvt (Autodesk Revit) sem o Revit.

Descoberta central (ver README.md): o .rvt é um OLE Compound File cujos streams
são sequências de registros gzip com janela deflate COMPARTILHADA entre registros:

    [10B header gzip][deflate raw][CRC32 4B][ISIZE 4B][32B rodapé] ...

Descomprimir cada registro isolado falha ("invalid distance too far back") porque
o deflate continua a janela do anterior. Solução parcial: zdict = últimos 32 KB do
output anterior (verifica CRC32 de cada registro; ~75% dos registros verificam
perfeitamente, o resto é extraído sem verificação — ver issues).

Uso:
    python3 rvttool.py lista   arquivo.rvt              — lista streams
    python3 rvttool.py dump    arquivo.rvt STREAM [out] — descomprime stream
    python3 rvttool.py strings arquivo.rvt STREAM [min]  — strings UTF-16
    python3 rvttool.py verifica arquivo.rvt [STREAM]     — estatísticas de CRC
"""
import io
import olefile
import re
import sys
import zlib


def decompress_stream(data, verify=True):
    """Descomprime um stream .rvt (cadeia de registros gzip encadeados).

    Retorna dict com: data (bytes), records, ok, crc_ok, crc_bad, errors.
    """
    p = data.find(b'\x1f\x8b\x08')
    if p < 0:
        return dict(data=data, records=0, ok=0, crc_ok=0, crc_bad=0, errors=0)
    total = bytearray()
    prev = b''
    st = dict(records=0, ok=0, crc_ok=0, crc_bad=0, errors=0)
    while p >= 0 and p + 3 <= len(data) and data[p:p + 3] == b'\x1f\x8b\x08' and st['records'] < 500000:
        st['records'] += 1
        do = zlib.decompressobj(-15, zdict=prev[-32768:] if prev else b'')
        try:
            out = do.decompress(data[p + 10:])
            consumed = len(data) - p - 10 - len(do.unused_data) - len(do.unconsumed_tail)
            de = p + 10 + consumed
            st['ok'] += 1
            if verify and de + 8 <= len(data):
                crc_stored = int.from_bytes(data[de:de + 4], 'little')
                isize = int.from_bytes(data[de + 4:de + 8], 'little')
                if crc_stored == (zlib.crc32(out) & 0xffffffff) and isize == len(out) % 2**32:
                    st['crc_ok'] += 1
                else:
                    st['crc_bad'] += 1
            total += out
            prev = out
            nxt = de + 40
            if nxt > len(data) or data[nxt:nxt + 3] != b'\x1f\x8b\x08':
                nxt = data.find(b'\x1f\x8b\x08', de)
        except zlib.error:
            st['errors'] += 1
            nxt = data.find(b'\x1f\x8b\x08', p + 10)
            if nxt < 0:
                break
        p = nxt
    st['data'] = bytes(total)
    return st


def read_stream(rvt_path, stream):
    with olefile.OleFileIO(rvt_path) as f:
        raw = f.openstream(stream).read()
    return decompress_stream(raw)


def cmd_lista(rvt):
    with olefile.OleFileIO(rvt) as f:
        for s in sorted(f.listdir()):
            name = '/'.join(s)
            print(f'{f.get_size(name):>12,}  {name}')


def cmd_dump(rvt, stream, outfile=None):
    r = read_stream(rvt, stream)
    print(f"{stream}: {r['records']} registros, CRC OK: {r['crc_ok']}, "
          f"CRC divergente: {r['crc_bad']}, erros: {r['errors']}, "
          f"{len(r['data']):,} bytes descomprimidos", file=sys.stderr)
    if outfile:
        open(outfile, 'wb').write(r['data'])
        print(f'salvo em {outfile}', file=sys.stderr)
    else:
        sys.stdout.buffer.write(r['data'])


def cmd_strings(rvt, stream, min_len=6):
    r = read_stream(rvt, stream)
    print(f"{stream}: {r['records']} registros, CRC OK: {r['crc_ok']}/{r['records']}",
          file=sys.stderr)
    seen = set()
    pat = ('(?:[ -~\\xc0-\\xff]\\x00){%d,}' % min_len).encode()
    for m in re.finditer(pat, r['data']):
        t = m.group().decode('utf-16-le', errors='replace')
        if t not in seen:
            seen.add(t)
            print(t)


def cmd_verifica(rvt, stream='Partitions/3'):
    r = read_stream(rvt, stream)
    tot = r['records']
    print(f'{rvt} :: {stream}')
    print(f"  registros:        {tot}")
    print(f"  descomprimidos:   {r['ok']}")
    print(f"  CRC32+ISIZE OK:   {r['crc_ok']}  ({100*r['crc_ok']/max(tot,1):.1f}%)")
    print(f"  CRC divergente:   {r['crc_bad']}  (janela anterior desconhecida)")
    print(f"  erros:            {r['errors']}")
    print(f"  tamanho final:    {len(r['data']):,} bytes")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd, rvt = sys.argv[1], sys.argv[2]
    if cmd == 'lista':
        cmd_lista(rvt)
    elif cmd == 'dump':
        cmd_dump(rvt, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == 'strings':
        cmd_strings(rvt, sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 6)
    elif cmd == 'verifica':
        cmd_verifica(rvt, sys.argv[3] if len(sys.argv) > 3 else 'Partitions/3')
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
