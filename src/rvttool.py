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
    python3 rvttool.py elementos arquivo.rvt [STREAM]    — resumo de elementos
    python3 rvttool.py paredes arquivo.rvt [SAIDA]       — location lines
    python3 rvttool.py plano arquivo.rvt [SAIDA.svg]     — planta 2D em SVG
    python3 rvttool.py versao arquivo.rvt                — versão do Revit
    python3 rvttool.py exporta arquivo.rvt [SAIDA] [STREAM] — JSON completo
"""
import io
import json
import math
import collections
import olefile
import re
import struct
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


# ---------------------------------------------------------------- curvas type-4
# Registro de geometria "linha" (type 4): 109 bytes, 9 doubles:
#   [x1][y1][z1][0][x2][y2][z2][comprimento][~0]
#   counts = [4][a][b][c][d][ref][0]  (ref = counts[5])
# Validacao matematica: hypot(dx,dy) == comprimento

def extrai_curvas_t4(data):
    sig = b'\xff\xff\xff\xff\x04\x82\x08\x00'
    pos = [m.start() for m in re.finditer(re.escape(sig), data)]
    linhas = []
    i = 0
    while i < len(pos):
        s = pos[i]
        if s + 109 > len(data):
            break
        cnts = struct.unpack_from('<7I', data, s+8)
        dbls = struct.unpack_from('<9d', data, s+36)
        x1, y1, z1, q1, x2, y2, z2, L, z9 = dbls
        dist = math.hypot(x2-x1, y2-y1)
        ok_prox = (i+1 >= len(pos)) or (pos[i+1] == s+109)
        if (cnts[0] == 4 and abs(q1) < 1e-9 and abs(z9) < 1e-100
                and abs(dist-L) < 0.02*max(1, abs(L)) and ok_prox
                and abs(L) > 1e-9):
            linhas.append({'x1': x1, 'y1': y1, 'z': z1, 'x2': x2, 'y2': y2,
                           'comp': L, 'ref': cnts[5], 'item': cnts[1]})
        i += 1
    return linhas

def cmd_curvas(rvt, saida='curvas.json'):
    st = read_stream(rvt, 'Partitions/3')
    linhas = extrai_curvas_t4(st['data'])
    json.dump(linhas, open(saida, 'w'), indent=1)
    zs = collections.Counter(round(l['z'], 2) for l in linhas)
    print(f'curvas type-4 validadas: {len(linhas)}')
    print('niveis (z -> n):', dict(sorted(zs.items(), key=lambda kv: -kv[1])[:8]))
    print(f'salvo em {saida}')

# ---------------------------------------------------------------- dxf (MVP importador)
# Exporta as linhas de localizacao como DXF com uma camada por nivel.
# Unidades: converte pes -> metros (x0.3048). Abre no FreeCAD (Arquivo > Importar),
# AutoCAD, BricsCAD, QCAD, Inkscape etc.

def cmd_dxf(rvt, saida='planta.dxf'):
    import ezdxf
    st = read_stream(rvt, 'Partitions/3')
    linhas = extrai_curvas_t4(st['data'])
    PE = 0.3048
    vistos = set()
    por_nivel = collections.defaultdict(list)
    for l in linhas:
        key = (round(l['x1'], 3), round(l['y1'], 3), round(l['x2'], 3),
               round(l['y2'], 3), round(l['z'], 2))
        if key in vistos:
            continue
        vistos.add(key)
        por_nivel[round(l['z'] * PE, 3)].append(l)
    doc = ezdxf.new('R2010', setup=True)
    msp = doc.modelspace()
    for z in sorted(por_nivel):
        camada = f'NIVEL_{z:+.3f}'.replace('.', ',').replace('+', 'P').replace('-', 'M')
        # nome de camada DXF nao aceita virgula; usar ponto
        camada = f'NIVEL_{z:+.3f}'
        if camada not in doc.layers:
            doc.layers.add(camada)
        n = 0
        for l in por_nivel[z]:
            msp.add_line((l['x1']*PE, l['y1']*PE), (l['x2']*PE, l['y2']*PE),
                         dxfattribs={'layer': camada})
            n += 1
        print(f'  camada {camada}: {n} linhas')
    doc.saveas(saida)
    print(f'DXF salvo em {saida} ({sum(len(v) for v in por_nivel.values())} linhas, {len(por_nivel)} niveis)')

# ---------------------------------------------------------------- macro FreeCAD
# Gera um .FCMacro autocontido: ao executa-lo no FreeCAD (Macro > Macros...),
# cria um documento com as linhas de localizacao por nivel (Part::Feature)
# e uma planilha com o inventario de elementos nomeados.

# ---------------------------------------------------------------- ifc (BIM)
# Exporta IFC4: um IfcBuildingStorey por nivel, com a geometria de referencia
# (location lines type-4 validadas) como IfcGeometricCurveSet. Unidades em metros.
# A atribuicao elemento->geometria ainda nao foi decodificada (issue 3), por isso
# as curvas vao como referencia dentro do pavimento, nao como IfcWall/IfcSlab.

def cmd_ifc(rvt, saida='modelo.ifc', min_curvas=4):
    import ifcopenshell, ifcopenshell.guid
    st = read_stream(rvt, 'Partitions/3')
    linhas = extrai_curvas_t4(st['data'])
    PE = 0.3048
    por_nivel = collections.defaultdict(list)
    vistos = set()
    for l in linhas:
        key = (round(l['x1'], 3), round(l['y1'], 3), round(l['x2'], 3),
               round(l['y2'], 3), round(l['z'], 2))
        if key in vistos:
            continue
        vistos.add(key)
        por_nivel[round(l['z'] * PE, 3)].append(l)
    # niveis com poucas curvas sao ruido de conversao (1-3 linhas isoladas)
    ruido = {z: len(v) for z, v in por_nivel.items() if len(v) < min_curvas}
    for z in ruido:
        del por_nivel[z]
    if ruido:
        print('niveis descartados (<%d curvas): %s' % (
            min_curvas, ', '.join('%+.3f(%d)' % (z, n) for z, n in sorted(ruido.items()))))
    if not por_nivel:
        print('nenhuma curva valida — nada a exportar')
        return

    f = ifcopenshell.file(schema='IFC4')
    G = ifcopenshell.guid.new

    unidade = f.create_entity(
        'IfcUnitAssignment', Units=[
            f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE'),
            f.create_entity('IfcSIUnit', UnitType='AREAUNIT', Name='SQUARE_METRE'),
            f.create_entity('IfcSIUnit', UnitType='VOLUMEUNIT', Name='CUBIC_METRE'),
            f.create_entity('IfcSIUnit', UnitType='PLANEANGLEUNIT', Name='RADIAN'),
        ])
    proj = f.create_entity('IfcProject', GlobalId=G(), Name='Revit import (rvttool)',
                           UnitsInContext=unidade)

    origem = f.create_entity('IfcCartesianPoint', Coordinates=(0.0, 0.0, 0.0))
    eixo = f.create_entity('IfcAxis2Placement3D', Location=origem)
    ctx = f.create_entity('IfcGeometricRepresentationContext',
                          ContextIdentifier='Model', ContextType='Model',
                          CoordinateSpaceDimension=3, Precision=1e-5,
                          WorldCoordinateSystem=eixo)
    proj.RepresentationContexts = [ctx]

    site = f.create_entity('IfcSite', GlobalId=G(), Name='Site')
    edif = f.create_entity('IfcBuilding', GlobalId=G(), Name='Edificacao')
    f.create_entity('IfcRelAggregates', GlobalId=G(), RelatingObject=proj,
                    RelatedObjects=[site])
    f.create_entity('IfcRelAggregates', GlobalId=G(), RelatingObject=site,
                    RelatedObjects=[edif])

    pavimentos = []
    for z in sorted(por_nivel):
        p = f.create_entity('IfcBuildingStorey', GlobalId=G(),
                            Name='Nivel %+.3f m' % z, Elevation=z)
        pavimentos.append((p, z))
    f.create_entity('IfcRelAggregates', GlobalId=G(), RelatingObject=edif,
                    RelatedObjects=[p for p, _ in pavimentos])

    total = 0
    for p, z in pavimentos:
        itens = []
        for l in por_nivel[z]:
            a = f.create_entity('IfcCartesianPoint',
                                Coordinates=(l['x1'] * PE, l['y1'] * PE, 0.0))
            b = f.create_entity('IfcCartesianPoint',
                                Coordinates=(l['x2'] * PE, l['y2'] * PE, 0.0))
            itens.append(f.create_entity('IfcPolyline', Points=[a, b]))
        if not itens:
            continue
        total += len(itens)
        curvas = f.create_entity('IfcGeometricCurveSet', Elements=itens)
        rep = f.create_entity('IfcShapeRepresentation', ContextOfItems=ctx,
                              RepresentationIdentifier='Reference',
                              RepresentationType='GeometricCurveSet',
                              Items=[curvas])
        p.Representation = f.create_entity('IfcProductDefinitionShape',
                                           Representations=[rep])
        props = f.create_entity('IfcPropertySet', GlobalId=G(),
                                Name='Pset_RevitImport', HasProperties=[
                                    f.create_entity('IfcPropertySingleValue', Name='Linhas',
                                                    NominalValue=f.create_entity('IfcInteger', len(itens))),
                                    f.create_entity('IfcPropertySingleValue', Name='Fonte',
                                                    NominalValue=f.create_entity('IfcLabel', 'Partitions/3 type-4')),
                                ])
        f.create_entity('IfcRelDefinesByProperties', GlobalId=G(),
                        RelatedObjects=[p], RelatingPropertyDefinition=props)

    f.write(saida)
    print('IFC salvo em %s' % saida)
    print('  pavimentos: %d | curvas de referencia: %d' % (len(pavimentos), total))
    print('  niveis (m): %s' % ', '.join('%+.3f' % z for z in sorted(por_nivel)))
    print('  obs: geometria como referencia (elemento->geometria ainda nao decodificado)')


# ---------------------------------------------------------------- poligonos
# Reconstroi contornos fechados a partir das curvas type-4: agrupa extremos
# com tolerancia (1 cm), traca cadeias preferindo o menor angulo de virada
# (segue a parede em vez de cortar caminho) e fecha quando volta ao inicio.
# Saida em metros: DXF com LWPOLYLINE fechada + JSON com perimetro/area.

def _poligonos_nivel(curvas, PE=0.3048, tol=0.01, min_lados=3):
    def nid(x, y):
        return (round(x * PE / tol), round(y * PE / tol))

    arestas = []
    adj = collections.defaultdict(list)
    for l in curvas:
        a, b = nid(l['x1'], l['y1']), nid(l['x2'], l['y2'])
        if a == b:
            continue
        k = len(arestas)
        arestas.append((a, b))
        adj[a].append(k)
        adj[b].append(k)

    usado = set()
    polis = []
    for i in range(len(arestas)):
        if i in usado:
            continue
        usado.add(i)
        a, b = arestas[i]
        pts, ini, atual = [a, b], a, b
        while True:
            cand = [j for j in adj[atual] if j not in usado]
            if not cand:
                break
            if len(cand) > 1:
                vx, vy = atual[0] - pts[-2][0], atual[1] - pts[-2][1]
                nv = math.hypot(vx, vy) or 1

                def ang(j, _atual=atual, _vx=vx, _vy=vy, _nv=nv):
                    e = arestas[j]
                    e2 = e[1] if e[0] == _atual else e[0]
                    wx, wy = e2[0] - _atual[0], e2[1] - _atual[1]
                    nw = math.hypot(wx, wy) or 1
                    return 1 - (_vx * wx + _vy * wy) / (_nv * nw)
                cand.sort(key=ang)
            j = cand[0]
            usado.add(j)
            e = arestas[j]
            prox = e[1] if e[0] == atual else e[0]
            if prox == ini:
                if len(pts) + 1 >= min_lados:
                    polis.append(pts)
                break
            pts.append(prox)
            atual = prox
    return polis


def _poligono_metrico(pts, PE=0.3048, tol=0.01):
    """Converte ids de grade para metros e devolve (xy, perimetro, area)."""
    xy = [(p[0] * tol / PE, p[1] * tol / PE) for p in pts]
    per = 0.0
    area = 0.0
    n = len(xy)
    for i in range(n):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % n]
        per += math.hypot(x2 - x1, y2 - y1)
        area += x1 * y2 - x2 * y1
    return xy, per, abs(area) / 2.0


def cmd_poligonos(rvt, saida='contornos.dxf', min_lados=3):
    import ezdxf
    import json
    import os
    st = read_stream(rvt, 'Partitions/3')
    linhas = extrai_curvas_t4(st['data'])
    por_nivel = collections.defaultdict(list)
    for l in linhas:
        por_nivel[round(l['z'], 3)].append(l)

    doc = ezdxf.new('R2010', setup=True)
    msp = doc.modelspace()
    resumo = []
    for z in sorted(por_nivel):
        polis = _poligonos_nivel(por_nivel[z])
        if not polis:
            continue
        z_m = z * 0.3048
        camada = 'CONTORNO_%+.3f' % z_m
        if camada not in doc.layers:
            doc.layers.add(camada)
        itens = []
        for pts in polis:
            xy, per, area = _poligono_metrico(pts)
            if area <= 1e-6:
                continue
            itens.append({'lados': len(xy), 'perimetro_m': round(per, 3),
                          'area_m2': round(area, 3),
                          'xy': [[round(x, 3), round(y, 3)] for x, y in xy]})
        if not itens:
            continue
        itens.sort(key=lambda i: -i['area_m2'])
        areas = sorted(i['area_m2'] for i in itens)
        mediana = areas[len(areas) // 2]
        # lacos muito maiores que a mediana costumam ser tracejado por linhas de
        # grade/site, nao um ambiente: ficam no arquivo, mas marcados
        for i in itens:
            if mediana > 0 and i['area_m2'] > 20 * mediana:
                i['suspeita'] = 'laco_muito_grande'
            msp.add_lwpolyline([tuple(p) for p in i['xy']], close=True,
                               dxfattribs={'layer': camada})
        resumo.append({'nivel_m': round(z_m, 3), 'poligonos': len(itens),
                       'area_total_m2': round(sum(i['area_m2'] for i in itens), 3),
                       'area_mediana_m2': round(mediana, 3),
                       'area_max_m2': areas[-1]})
        print('  nivel %+.3f m: %d contornos | area total %.1f m2 | mediana %.1f m2 '
              '| maior %.1f m2' % (z_m, len(itens),
                                  sum(i['area_m2'] for i in itens), mediana, areas[-1]))
        json.dump(itens, open('%s_%+.3f.json' % (os.path.splitext(saida)[0], z_m), 'w'))

    doc.saveas(saida)
    total = sum(r['poligonos'] for r in resumo)
    print('contornos fechados: %d em %d niveis -> %s (+ JSON por nivel)' % (
        total, len(resumo), saida))
    print('  obs: contorno geometrico (sem elemento/material associado)')


def cmd_macro(rvt, saida='revit_import.FCMacro'):
    st = read_stream(rvt, 'Partitions/3')
    linhas = extrai_curvas_t4(st['data'])
    PE = 0.3048
    vistos = set()
    por_nivel = collections.defaultdict(list)
    for l in linhas:
        key = (round(l['x1'], 3), round(l['y1'], 3), round(l['x2'], 3),
               round(l['y2'], 3), round(l['z'], 2))
        if key in vistos:
            continue
        vistos.add(key)
        por_nivel[round(l['z'] * PE, 3)].append(l)
    # elementos nomeados
    tbl = dict(parse_elemtable(read_stream(rvt, 'Global/ElemTable')['data'])[0])
    els = extrai_elementos(st['data'], tbl)
    nomeados = [(e['id'], e['nome']) for e in els if e['nome']]
    nomeados = nomeados[:4000]
    L = []
    a = L.append
    a('# Gerado por revit-free (rvttool macro) — importador .rvt -> FreeCAD')
    a('# Executar dentro do FreeCAD: Macro > Macros... > selecionar este arquivo > Executar')
    a('import FreeCAD as App')
    a('import Part')
    a('doc = App.newDocument("RevitImport")')
    a('')
    for z in sorted(por_nivel):
        nome = f'NIVEL_{z:+.3f}'
        a(f'grp = doc.addObject("App::DocumentObjectGroup", "{nome}")')
        a(f'grp.Label = "{nome} (linhas de localizacao)"')
        a('comp = []')
        for l in por_nivel[z]:
            a(f'comp.append(Part.LineSegment(App.Vector({l["x1"]*PE:.6f}, {l["y1"]*PE:.6f}, {z:.6f}), '
              f'App.Vector({l["x2"]*PE:.6f}, {l["y2"]*PE:.6f}, {z:.6f})))')
        a('obj = doc.addObject("Part::Feature", "%s")' % nome)
        a(f'obj.Label = "{nome}"')
        a('obj.Shape = Part.Shape(comp)')
        a('grp.addObject(obj)')
        a('')
    a('sheet = doc.addObject("Spreadsheet::Sheet", "Elementos")')
    a('sheet.set("A1", "id"); sheet.set("B1", "nome")')
    for i, (eid, nome) in enumerate(nomeados, start=2):
        nm = nome.replace('\\', '\\\\').replace('"', '\\"')
        a(f'sheet.set("A{i}", "{eid}"); sheet.set("B{i}", "{nm}")')
    a('doc.recompute()')
    a('print("revit-free: documento criado —", len(doc.Objects), "objetos")')
    open(saida, 'w').write('\n'.join(L))
    print(f'macro salva em {saida}: {len(por_nivel)} niveis, {len(nomeados)} elementos nomeados')

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
    elif cmd == 'elementos':
        cmd_elementos(rvt, sys.argv[3] if len(sys.argv) > 3 else 'Partitions/3')
    elif cmd == 'paredes':
        cmd_paredes(rvt, sys.argv[3] if len(sys.argv) > 3 else 'paredes.json')
    elif cmd == 'plano':
        cmd_plano(rvt, sys.argv[3] if len(sys.argv) > 3 else 'plano.svg')
    elif cmd == 'versao':
        cmd_versao(rvt)
    elif cmd == 'curvas':
        cmd_curvas(rvt, sys.argv[3] if len(sys.argv) > 3 else 'curvas.json')
    elif cmd == 'dxf':
        cmd_dxf(rvt, sys.argv[3] if len(sys.argv) > 3 else 'planta.dxf')
    elif cmd == 'macro':
        cmd_macro(rvt, sys.argv[3] if len(sys.argv) > 3 else 'revit_import.FCMacro')
    elif cmd == 'ifc':
        cmd_ifc(rvt, sys.argv[3] if len(sys.argv) > 3 else 'modelo.ifc')
    elif cmd == 'poligonos':
        cmd_poligonos(rvt, sys.argv[3] if len(sys.argv) > 3 else 'contornos.dxf')
    elif cmd == 'exporta':
        cmd_exporta(rvt,
                    sys.argv[3] if len(sys.argv) > 3 else 'elementos.json',
                    sys.argv[4] if len(sys.argv) > 4 else 'Partitions/3')
    else:
        print(__doc__)
        return 1
    return 0




# ---------------------------------------------------------------- elementos

def parse_elemtable(data):
    """Decodifica o Global/ElemTable (árvore de elementos).

    Header 18B: a7 04 [count u16] 00 00 01 00 00 00 01 00 00 00 00 00 00 00
    Registros:
      raiz:  [id][id][0][-1]                      (16B)
      normal:[id][id][0][parent][Q][0][-1]        (28B)
    Retorna lista de (id, parent).
    """
    if len(data) < 18 or data[0:2] != b'\xa7\x04':
        return [], 0
    total = struct.unpack_from('<H', data, 2)[0]
    n = (len(data) - 18) // 4
    vals = struct.unpack_from(f'<{n}I', data, 18)
    out = []
    i = 0
    while i + 3 < n and len(out) < total + 16:
        a, b, f3, p = vals[i:i+4]
        if a != b or f3 != 0 or a == 0 or a >= 4_000_000:
            i += 1
            continue
        if p == 0xFFFFFFFF:
            out.append((a, -1))
            i += 4
        else:
            if p >= 4_000_000 or i + 6 >= n:
                i += 1
                continue
            out.append((a, p))
            i += 7
    return out, total


def cmd_elementos(rvt, stream='Partitions/3'):
    """Best-effort: árvore de elementos (ElemTable) + catálogo de strings."""
    import json
    et = read_stream(rvt, 'Global/ElemTable')['data']
    entradas, total_hdr = parse_elemtable(et)
    ids = sorted(set(a for a, _ in entradas))
    filhos = {}
    vistos = set()
    for a, p in entradas:
        if a in vistos:
            continue
        vistos.add(a)
        filhos.setdefault(p, []).append(a)
    data = read_stream(rvt, stream)['data']
    pat = ('(?:[ -~\\xc0-\\xff]\\x00){3,}').encode()
    strs = []
    for m in re.finditer(pat, data):
        try:
            t = m.group().decode('utf-16-le')
        except Exception:
            continue
        strs.append(t)
    resumo = {
        'AVISO': 'árvore de elementos extraída do ElemTable (gramática parcial, ver docs)',
        'elementos_na_arvore': len(ids),
        'count_no_header': total_hdr,
        'raizes': [a for a, p in entradas if p == -1][:20],
        'grupos_maiores': [(p, len(f)) for p, f in
                           sorted(filhos.items(), key=lambda kv: -len(kv[1]))[:10]],
        'total_strings': len(strs),
        'strings_unicas': len(set(strs)),
        'amostra_familias': sorted(set(s for s in strs if s.startswith('M_')))[:30],
        'amostra_niveis': sorted(set(s for s in strs if 'Level' in s or 'Nível' in s))[:15],
        'amostra_pranchas': sorted(set(s for s in strs if re.match(r'^\\d{4,5}\\.\\w', s)))[:20],
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- exporta

MK_ELEM = b'\x5d\x02\x01\x00\x00\x00'
RE_UTF16 = re.compile(rb'(?:[\x20-\x7e\xc0-\xff]\x00){2,}')
RE_STRLIST = re.compile(rb'\xff\xff\xff\xff\x02\x08(....)', re.S)


def _strings_seg(seg, limite=1200, minimo=2):
    out = []
    for u in RE_UTF16.finditer(seg[:limite]):
        try:
            t = u.group().decode('utf-16-le')
        except Exception:
            continue
        if len(t) >= minimo:
            out.append(t)
    return out


def extrai_elementos(data, tbl):
    """Extrai elementos do banco: lista de dicts id/grupo/nome/strings/listas."""
    pos = [m.start() for m in re.finditer(re.escape(MK_ELEM), data)]
    els = []
    for k, s in enumerate(pos):
        fim = pos[k+1] if k+1 < len(pos) else min(s+8192, len(data))
        eid = struct.unpack_from('<I', data, s+6)[0]
        seg = data[s+10:fim]
        strs = _strings_seg(seg)
        listas = []
        for m in RE_STRLIST.finditer(seg):
            L = struct.unpack('<I', m.group(1))[0]
            o = m.end()
            if 1 <= L <= 300 and o+2*L <= len(seg):
                try:
                    t = seg[o:o+2*L].decode('utf-16-le')
                except Exception:
                    continue
                if t and all(9 <= ord(c) < 0x300 for c in t):
                    listas.append(t)
        els.append({
            'id': eid,
            'grupo': tbl.get(eid),
            'nome': strs[0] if strs else None,
            'strings': strs[:10],
            'lista_strings': listas[:20],
            'bytes': len(seg),
        })
    return els

def cmd_exporta(rvt, saida='elementos.json', stream='Partitions/3'):
    """Extrai todos os elementos do banco: id, grupo, nome, strings, listas."""
    import json
    data = read_stream(rvt, stream)['data']
    et = read_stream(rvt, 'Global/ElemTable')['data']
    tbl = dict(parse_elemtable(et)[0])
    els = extrai_elementos(data, tbl)
    doc = {
        'arquivo': rvt,
        'aviso': 'extracao best-effort da fase 2 — formato em docs/ESTRUTURA.md',
        'total_registros': len(els),
        'com_nome': sum(1 for e in els if e['nome']),
        'elementos': els,
    }
    with open(saida, 'w') as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f'{len(els)} registros -> {saida} ({sum(1 for e in els if e["nome"])} com nome)')


def cmd_versao(rvt):
    """Lê a versão do Revit do BasicFileInfo."""
    import olefile
    ole = olefile.OleFileIO(rvt)
    b = ole.openstream('BasicFileInfo').read()
    ole.close()
    txt = b.decode('utf-16-le', errors='ignore')
    import re as _re
    m = _re.search(r'Revit \d{4}(?:[^\x00]*?Build: [0-9_()x]+)?', txt)
    print(m.group(0) if m else txt[:80])


# ---------------------------------------------------------------- paredes

RE_GEO = re.compile(rb'\xff\xff\xff\xff\x04\x82\x08\x00')


def cmd_paredes(rvt, saida='paredes.json', stream='Partitions/3'):
    """Extrai location lines (paredes/linhas) dos registros de geometria.

    Cada registro de geometria [-1][04 82][08 00][counts...] contém arrays
    de doubles; quando o 8-tuple [x1,y1,z1,0,x2,y2,z2,L] satisfaz
    dist((x1,y1),(x2,y2)) == L, é uma location line auto-validada.
    """
    import json, math
    d = read_stream(rvt, stream)['data']
    out = []
    for m in RE_GEO.finditer(d):
        o = m.end()
        start = o + 24 + ((8 - (o + 24) % 8) % 8)
        if start + 64 > len(d):
            continue
        dbls = [struct.unpack_from('<d', d, start + k)[0] for k in range(0, 96, 8)]
        for f in range(0, 5):
            w = dbls[f:f+8]
            if len(w) < 8:
                break
            x1, y1, z1, p1, x2, y2, z2, L = w
            if not all(abs(v) < 1e4 for v in (x1, y1, x2, y2, L)):
                continue
            if abs(z1 - z2) > 1e-9:
                continue
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist < 0.5 or abs(dist - L) > 0.02 * L:
                continue
            out.append({'x1': round(x1, 4), 'y1': round(y1, 4), 'z': round(z1, 4),
                        'x2': round(x2, 4), 'y2': round(y2, 4), 'comp': round(L, 4)})
            break
    doc = {'arquivo': rvt, 'location_lines': len(out), 'linhas': out}
    with open(saida, 'w') as f:
        json.dump(doc, f)
    print(f'{len(out)} location lines -> {saida}')


def cmd_plano(rvt, saida='plano.svg', stream='Partitions/3'):
    """Renderiza as location lines em SVG (planta 2D)."""
    import json, math
    d = read_stream(rvt, stream)['data']
    lines = []
    for m in RE_GEO.finditer(d):
        o = m.end()
        start = o + 24 + ((8 - (o + 24) % 8) % 8)
        if start + 64 > len(d):
            continue
        dbls = [struct.unpack_from('<d', d, start + k)[0] for k in range(0, 96, 8)]
        for f in range(0, 5):
            w = dbls[f:f+8]
            if len(w) < 8:
                break
            x1, y1, z1, p1, x2, y2, z2, L = w
            if not all(abs(v) < 1e4 for v in (x1, y1, x2, y2, L)):
                continue
            if abs(z1 - z2) > 1e-9:
                continue
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist < 0.5 or abs(dist - L) > 0.02 * L:
                continue
            lines.append((x1, y1, x2, y2))
            break
    if not lines:
        print('nenhuma linha encontrada')
        return
    xs = [v for l in lines for v in (l[0], l[2])]
    ys = [v for l in lines for v in (l[1], l[3])]
    W = H = 1500
    pad = 40
    x0, xa, y0, ya = min(xs), max(xs), min(ys), max(ys)
    sc = min((W - 2 * pad) / max(1e-9, xa - x0), (H - 2 * pad) / max(1e-9, ya - y0))
    px = lambda x: pad + (x - x0) * sc
    py = lambda y: H - pad - (y - y0) * sc
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}">',
           '<rect width="100%" height="100%" fill="white"/>']
    for x1, y1, x2, y2 in lines:
        svg.append(f'<line x1="{px(x1):.1f}" y1="{py(y1):.1f}" x2="{px(x2):.1f}" '
                   f'y2="{py(y2):.1f}" stroke="black" stroke-width="1.2"/>')
    svg.append('</svg>')
    with open(saida, 'w') as f:
        f.write('\n'.join(svg))
    print(f'{len(lines)} linhas -> {saida}')


if __name__ == '__main__':
    sys.exit(main())
