"""Parser de registros de Partitions/* — v2: dobj fresco por membro."""
import olefile, zlib, sys

def u32(b,o): return int.from_bytes(b[o:o+4],'little')
def u16(b,o): return int.from_bytes(b[o:o+2],'little')

f = olefile.OleFileIO(sys.argv[1])
d = f.openstream('Partitions/3').read()

p = 44
recs = []
while p >= 0 and len(recs) < 3000:
    if d[p:p+3] != b'\x1f\x8b\x08':
        break
    flg = d[p+3]; hlen = 10
    if flg & 8: hlen = d.index(b'\0', hlen+p)+1-p
    payload = d[p+hlen:]
    do = zlib.decompressobj(-15)
    try:
        out = do.decompress(payload)
        err = None
    except zlib.error as e:
        out = b''; err = str(e)
    consumed = len(payload) - len(do.unused_data) - len(do.unconsumed_tail)
    end = p + hlen + consumed          # fim do deflate
    isize = u32(d, end+4) if end+8 <= len(d) else -1
    footer = d[end+8:end+8+32]
    nxt = d.find(b'\x1f\x8b\x08', end)
    recs.append(dict(n=len(recs), p=p, usize=len(out), isize=isize, err=err,
                     end=end, nxt=nxt, footer=footer))
    p = nxt

print(f'{len(recs)} registros')
print(f"{'n':>3} {'off':>10} {'usize':>9} {'isize':>9} ok  err")
for r in recs[:12]:
    print(f"{r['n']:>3} {r['p']:>10} {r['usize']:>9} {r['isize']:>9} {str(not r['err'])[:1]}  {r['err'] or ''}")
ok = sum(1 for r in recs if not r['err'])
print(f'OK: {ok}/{len(recs)}')
for r in recs[:4]:
    fb = r['footer']
    print(f"rec {r['n']} footer: {fb.hex(' ')}")
    print(f"   u32: {[u32(fb,i) for i in range(0,32,4)]}")
