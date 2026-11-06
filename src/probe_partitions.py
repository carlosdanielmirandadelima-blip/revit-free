"""Sonda do stream Partitions/*: localizar e descomprimir membros gzip."""
import olefile, gzip, zlib, sys

f = olefile.OleFileIO(sys.argv[1])
d = f.openstream('Partitions/3').read()
print(f'Partitions/3: {len(d)} bytes')

# achar todos os magic gzip
pos = []
i = 0
while True:
    j = d.find(b'\x1f\x8b\x08', i)
    if j < 0: break
    pos.append(j); i = j + 1
print(f'membros gzip encontrados: {len(pos)}')

# tentar descomprimir cada membro a partir do magic
ok, fail = 0, 0
out = bytearray()
sizes = []
for k, p in enumerate(pos[:50]):
    try:
        import io as _io
        dec = gzip.GzipFile(fileobj=_io.BytesIO(d[p:])).read()
        ok += 1
        if k < 5: print(f'  membro @{p}: {len(dec)} bytes descomprimidos')
        out += dec
    except Exception as e:
        fail += 1
        if k < 5: print(f'  membro @{p}: FALHOU ({e})')
print(f'descomprimidos OK: {ok}, falhas: {fail}')
print(f'total descomprimido (50 primeiros): {len(out)} bytes')
print('head descomprimido:', out[:64].hex(' '))
