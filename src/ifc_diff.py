#!/usr/bin/env python3
"""ifc_diff.py — compara dois arquivos IFC e mede o que sobreviveu.

Serve para o ciclo de ida e volta (Revit -> FreeCAD/outro -> Revit): depois de
editar e reexportar, este script mostra, por classe IFC, quantos elementos
existem em cada lado, quantos GUIDs coincidem e — para os que coincidem — se
nome, propriedades (psets) e volume continuam iguais.

Uso:
    python3 ifc_diff.py antes.ifc depois.ifc
    python3 ifc_diff.py antes.ifc depois.ifc --psets     # detalha psets
"""
import argparse
import collections
import math
import sys


def volume(geo):
    v, faces = geo.verts, geo.faces
    tot = 0.0
    for i in range(0, len(faces), 3):
        a, b, c = faces[i], faces[i + 1], faces[i + 2]
        ax, ay, az = v[3 * a], v[3 * a + 1], v[3 * a + 2]
        bx, by, bz = v[3 * b], v[3 * b + 1], v[3 * b + 2]
        cx, cy, cz = v[3 * c], v[3 * c + 1], v[3 * c + 2]
        tot += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
                + az * (bx * cy - by * cx)) / 6.0
    return abs(tot)


def carrega(caminho):
    import ifcopenshell
    import ifcopenshell.geom
    m = ifcopenshell.open(caminho)
    vols = {}
    try:
        s = ifcopenshell.geom.settings()
        s.set('use-world-coords', True)
        for sh in ifcopenshell.geom.iterator(s, m):
            vols[sh.guid] = volume(sh.geometry)
    except Exception:
        pass
    psets = collections.defaultdict(dict)
    try:
        import ifcopenshell.util.element as ue
        for e in m.by_type('IfcElement'):
            for nome, props in (ue.get_psets(e) or {}).items():
                for k, v in props.items():
                    if k.startswith('id') or k == 'GlobalId':
                        continue
                    psets[e.GlobalId]['%s.%s' % (nome, k)] = v
    except Exception:
        pass
    return m, vols, psets


def histograma(m):
    c = collections.Counter()
    for e in m:
        if e.is_a('IfcRoot'):
            c[e.is_a()] += 1
    return c


def compara(a_path, b_path, detalhar_psets=False):
    ma, va, pa = carrega(a_path)
    mb, vb, pb = carrega(b_path)
    print('A: %s (%s)' % (a_path, ma.schema))
    print('B: %s (%s)' % (b_path, mb.schema))

    ha, hb = histograma(ma), histograma(mb)
    classes = sorted(set(ha) | set(hb), key=lambda k: -(ha[k] + hb[k]))
    print('\n%-32s %6s %6s %s' % ('classe', 'A', 'B', 'situação'))
    perdas = 0
    for k in classes:
        n_a, n_b = ha[k], hb[k]
        sit = 'ok' if n_a == n_b else ('PERDA' if n_b < n_a else 'a mais')
        if n_a != n_b and k not in ('IfcPropertySingleValue', 'IfcCartesianPoint',
                                    'IfcDirection', 'IfcPolyline', 'IfcSite'):
            perdas += 1
        print('%-32s %6d %6d %s' % (k, n_a, n_b, sit))

    ids_a = {e.GlobalId for e in ma if e.is_a('IfcRoot')}
    ids_b = {e.GlobalId for e in mb if e.is_a('IfcRoot')}
    comuns = ids_a & ids_b
    print('\nGUIDs: A=%d B=%d | comuns=%d | só em A=%d | só em B=%d' % (
        len(ids_a), len(ids_b), len(comuns), len(ids_a - ids_b), len(ids_b - ids_a)))

    if comuns:
        el_a = {e.GlobalId: e for e in ma.by_type('IfcElement') if e.GlobalId in comuns}
        el_b = {e.GlobalId: e for e in mb.by_type('IfcElement') if e.GlobalId in comuns}
        iguais_nome = sum(1 for g in el_b if el_a.get(g) and
                          (el_a[g].Name or '') == (el_b[g].Name or ''))
        print('elementos comuns (IfcElement): %d | nome idêntico: %d' % (
            len(el_b), iguais_nome))
        dvol = []
        for g in el_b:
            if g in va and g in vb:
                dvol.append(abs(va[g] - vb[g]))
        if dvol:
            dvol.sort()
            print('volume de A vs B: %d comparáveis | diferença máx %.6f m3 | '
                  'mediana %.6f m3' % (len(dvol), dvol[-1], dvol[len(dvol) // 2]))
        chaves_a = collections.Counter(k for g in el_b for k in pa.get(g, {}))
        chaves_b = collections.Counter(k for g in el_b for k in pb.get(g, {}))
        faltando = sorted(set(chaves_a) - set(chaves_b))
        print('propriedades (psets) no elemento: A=%d chaves, B=%d chaves' % (
            len(chaves_a), len(chaves_b)))
        if faltando:
            print('  perdidas: %s' % ', '.join(faltando[:8]))
        if detalhar_psets:
            for k in sorted(set(chaves_a) | set(chaves_b)):
                print('    %-40s A=%d B=%d' % (k, chaves_a.get(k, 0), chaves_b.get(k, 0)))

    niveis_a = [(s.Name, s.Elevation) for s in ma.by_type('IfcBuildingStorey')]
    niveis_b = [(s.Name, s.Elevation) for s in mb.by_type('IfcBuildingStorey')]
    print('\npavimentos A: %s' % (niveis_a,))
    print('pavimentos B: %s' % (niveis_b,))
    print('\nresumo: %d classe(s) com perda de contagem' % perdas)
    return 0 if perdas == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description='Compara dois IFC (ida e volta).')
    ap.add_argument('antes')
    ap.add_argument('depois')
    ap.add_argument('--psets', action='store_true', help='detalha propriedades')
    args = ap.parse_args(argv)
    return compara(args.antes, args.depois, args.psets)


if __name__ == '__main__':
    sys.exit(main())
