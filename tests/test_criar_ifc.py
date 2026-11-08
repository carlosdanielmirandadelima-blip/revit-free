#!/usr/bin/env python3
"""Testes do gerador de IFC (src/criar_ifc.py).

Confere o que importa para o arquivo ser usado no Revit:
  - schema válido (0 erros) em IFC4 e IFC2X3
  - paredes com representação Axis + Body
  - material com camada (espessura vira composição de parede)
  - vãos como IfcOpeningElement + IfcRelVoidsElement
  - elementos contidos no pavimento (IfcRelContainedInSpatialStructure)
  - volumes reais: parede sem vão == L*t*h; parede com vão < L*t*h
"""
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(RAIZ, 'src', 'criar_ifc.py')
falhas = []


def checa(cond, msg):
    print(('  ok   ' if cond else '  FALHA') + ' ' + msg)
    if not cond:
        falhas.append(msg)


def gera(spec, saida, schema):
    r = subprocess.run([sys.executable, TOOL, spec, saida, '--schema', schema],
                       capture_output=True, text=True)
    return r


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


def main():
    try:
        import ifcopenshell
        import ifcopenshell.geom
        import ifcopenshell.validate
    except ImportError:
        print('ifcopenshell ausente — testes do gerador pulados')
        return 0
    import logging

    tmp = tempfile.mkdtemp(prefix='ifctest')
    spec = os.path.join(tmp, 'spec.json')
    with open(spec, 'w') as fh:
        subprocess.run([sys.executable, TOOL, '--exemplo'], stdout=fh, check=True)

    for schema in ('IFC4', 'IFC2X3'):
        print('schema', schema)
        saida = os.path.join(tmp, 'casa_%s.ifc' % schema)
        r = gera(spec, saida, schema)
        checa(r.returncode == 0, '%s gerado' % schema)
        if r.returncode != 0:
            print(r.stderr[-500:])
            continue

        m = ifcopenshell.open(saida)
        checa(m.schema == schema, 'schema de saida %s' % m.schema)

        class Cont(logging.Handler):
            def __init__(self):
                super().__init__()
                self.n = 0

            def emit(self, rec):
                self.n += 1

        lg = logging.getLogger('val' + schema)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        h = Cont()
        lg.addHandler(h)
        ifcopenshell.validate.validate(m, lg)
        checa(h.n == 0, 'validacao de schema sem erros (%d)' % h.n)

        paredes = m.by_type('IfcWallStandardCase')
        checa(len(paredes) == 7, '7 paredes (%d)' % len(paredes))
        ok_repr = all({'Axis', 'Body'} <=
                      {r_.RepresentationIdentifier for r_ in p.Representation.Representations}
                      for p in paredes)
        checa(ok_repr, 'todas as paredes com Axis + Body')
        checa(len(m.by_type('IfcMaterialLayerSetUsage')) == 7,
              'material com camada em todas as paredes')
        checa(len(m.by_type('IfcOpeningElement')) == 3, '3 vaos abertos')
        checa(len(m.by_type('IfcRelVoidsElement')) == 3, '3 relacoes de void')
        checa(len(m.by_type('IfcRelContainedInSpatialStructure')) == 2,
              'contencao por pavimento')
        checa(len(m.by_type('IfcBuildingStorey')) == 2, '2 pavimentos')

        s = ifcopenshell.geom.settings()
        s.set('use-world-coords', True)
        vols = {}
        for sh in ifcopenshell.geom.iterator(s, m):
            vols[sh.guid] = volume(sh.geometry)

        sem_vao = [p for p in paredes if p.Name in ('Parede Sul', 'Parede Oeste')]
        checa(len(sem_vao) == 2, 'achou as paredes sem vao')
        for p in sem_vao:
            esperado = 8.0 * 0.15 * 2.8 if p.Name == 'Parede Sul' else 6.0 * 0.15 * 2.8
            got = vols.get(p.GlobalId, 0.0)
            checa(abs(got - esperado) < 1e-6,
                  '%s volume %.4f == L*t*h %.4f' % (p.Name, got, esperado))

        norte = [p for p in paredes if p.Name == 'Parede Norte'][0]
        bruto = 8.0 * 0.15 * 2.8
        got = vols.get(norte.GlobalId, 0.0)
        checa(0 < got < bruto, 'Parede Norte com vaos perde volume (%.4f < %.4f)' % (got, bruto))

        lajes = m.by_type('IfcSlab')
        checa(len(lajes) == 2, '2 lajes (%d)' % len(lajes))
        for l in lajes:
            got = vols.get(l.GlobalId, 0.0)
            checa(abs(got - 48.0 * 0.12) < 1e-6,
                  '%s volume %.4f == 8x6x0,12' % (l.Name, got))

    print()
    if falhas:
        print('FALHAS: %d' % len(falhas))
        for f in falhas:
            print('  -', f)
        return 1
    print('TODOS OS TESTES DO GERADOR PASSARAM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
