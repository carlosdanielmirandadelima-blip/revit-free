"""Extrai particao gravando o mapa de verificacao CRC por regiao de output."""
import olefile, zlib, struct, json, sys

def u32(b,o): return int.from_bytes(b[o:o+4],'little')
def u16(b,o): return int.from_bytes(b[o:o+2],'little')

f = olefile.OleFileIO(sys.argv[1])
d = f.openstream(sys.argv[2] if len(sys.argv)>2 else 'Partitions/3').read()
p = d.find(b'\x1f\x8b\x08')
total = bytearray(); regions = []   # (start, end, verified)
prev = b''
n = 0
while p >= 0 and p+3 <= len(d) and d[p:p+3] == b'\x1f\x8b\x08' and n < 500000:
    n += 1
    do = zlib.decompressobj(-15, zdict=prev[-32768:] if prev else b'')
    try:
        out = do.decompress(d[p+10:])
        consumed = len(d)-p-10 - len(do.unused_data) - len(do.unconsumed_tail)
        de = p+10+consumed
        crc_ok = isize_ok = False
        if de+8 <= len(d):
            crc_ok = int.from_bytes(d[de:de+4],'little') == (zlib.crc32(out)&0xffffffff)
            isize_ok = len(out)%2**32 == int.from_bytes(d[de+4:de+8],'little')
        regions.append([len(total), len(total)+len(out), crc_ok and isize_ok])
        total += out; prev = out
        nxt = de+40
        if nxt > len(d) or d[nxt:nxt+3] != b'\x1f\x8b\x08':
            nxt = d.find(b'\x1f\x8b\x08', de)
    except zlib.error:
        nxt = d.find(b'\x1f\x8b\x08', p+10)
        if nxt < 0: break
    p = nxt
open(sys.argv[3],'wb').write(bytes(total))
json.dump(regions, open(sys.argv[3]+'.map.json','w'))
ok = sum(1 for r in regions if r[2])
print(f'{n} registros, {ok} verificados, output {len(total):,} bytes')
