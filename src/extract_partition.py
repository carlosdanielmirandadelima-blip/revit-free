"""Extrator de Partitions/* do .rvt — formato decifrado:
registro = [10B header gzip][deflate raw][8B CRC+ISIZE][32B rodape]
janela deflate compartilhada entre registros -> zdict = ultimos 32KB do output anterior
"""
import olefile, zlib, sys, struct

def u32(b,o): return int.from_bytes(b[o:o+4],'little')

f = olefile.OleFileIO(sys.argv[1])
d = f.openstream(sys.argv[2] if len(sys.argv)>2 else 'Partitions/3').read()

p = 44 if d[44:47] == b'\x1f\x8b\x08' else d.find(b'\x1f\x8b\x08')
prev_out = b''
total = bytearray()
n = 0; ok = 0; fail = 0
while p >= 0 and p+3 <= len(d) and d[p:p+3] == b'\x1f\x8b\x08':
    do = zlib.decompressobj(-15, zdict=prev_out[-32768:] if prev_out else b'')
    try:
        out = do.decompress(d[p+10:])
        ok += 1
    except zlib.error as e:
        fail += 1
        out = b''
        # tentar achar proximo magic pela busca (fallback)
    consumed = len(d)-p-10 - len(do.unused_data) - len(do.unconsumed_tail)
    end = p+10+consumed if not do.unused_data or consumed>0 else p+10
    total += out
    prev_out = out if out else prev_out
    nxt = d.find(b'\x1f\x8b\x08', p+10)
    # avanco preferencial: fim do deflate + 40
    if not do.unused_data or consumed > 0:
        cand = end + 40
        if cand <= len(d) and d[cand:cand+3] == b'\x1f\x8b\x08':
            nxt = cand
    p = nxt
    n += 1

print(f'{sys.argv[2]}: {n} registros, {ok} OK, {fail} falha, output total {len(total)} bytes')
open(sys.argv[3], 'wb').write(bytes(total))
print(f'salvo em {sys.argv[3]}')
