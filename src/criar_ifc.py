#!/usr/bin/env python3
"""criar_ifc.py — gera IFC que o Revit abre como elementos BIM de verdade.

Motivo: o Revit importa/abre IFC nativamente (Revit 2018+ abre IFC4; IFC2X3 é o
caminho mais maduro). Este script monta o arquivo a partir de uma descrição
simples em JSON, com:

  - IfcProject > IfcSite > IfcBuilding > IfcBuildingStorey (um por nível)
  - IfcWallStandardCase com representação 'Axis' (eixo 2D) + 'Body' (sólido
    extrudado) e IfcMaterialLayerSetUsage (espessura real, vira camada no Revit)
  - IfcSlab com contorno fechado e espessura
  - IfcOpeningElement + IfcRelVoidsElement para vãos (portas/janelas)
  - IfcRelContainedInSpatialStructure por pavimento (é o que faz o Revit
    colocar o elemento no nível certo)
  - Psets (Pset_WallCommon / Pset_SlabCommon)

Uso:
    python3 criar_ifc.py spec.json saida.ifc --schema IFC4
    python3 criar_ifc.py --exemplo > spec.json      # spec de demonstração
    python3 criar_ifc.py spec.json saida.ifc --verifica

Unidades na spec: metros, ângulo em graus não é usado (parede = segmento p1->p2).
O eixo Z do sólido é sempre +Z a partir da elevação do nível.
"""
import argparse
import json
import math
import sys
import time

import ifcopenshell
import ifcopenshell.guid


# ------------------------------------------------------------------ utilitários

def _gid():
    return ifcopenshell.guid.new()


def _ponto3(f, x, y, z):
    return f.create_entity('IfcCartesianPoint', Coordinates=(float(x), float(y), float(z)))


def _ponto2(f, x, y):
    return f.create_entity('IfcCartesianPoint', Coordinates=(float(x), float(y)))


def _dir(f, x, y, z):
    return f.create_entity('IfcDirection', DirectionRatios=(float(x), float(y), float(z)))


def _unidades(f):
    return f.create_entity('IfcUnitAssignment', Units=[
        f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE'),
        f.create_entity('IfcSIUnit', UnitType='AREAUNIT', Name='SQUARE_METRE'),
        f.create_entity('IfcSIUnit', UnitType='VOLUMEUNIT', Name='CUBIC_METRE'),
        f.create_entity('IfcSIUnit', UnitType='PLANEANGLEUNIT', Name='RADIAN'),
    ])


def _owner(f):
    """IfcOwnerHistory só é obrigatório no IFC2X3; no IFC4 pode ser None."""
    if f.schema != 'IFC2X3':
        return None
    pessoa = f.create_entity('IfcPerson', Id='rvttool', FamilyName='criar_ifc')
    org = f.create_entity('IfcOrganization', Name='rvttool')
    porg = f.create_entity('IfcPersonAndOrganization', ThePerson=pessoa,
                           TheOrganization=org)
    app = f.create_entity('IfcApplication', ApplicationDeveloper=org,
                          Version='1.0', ApplicationFullName='rvttool criar_ifc',
                          ApplicationIdentifier='rvttool')
    return f.create_entity('IfcOwnerHistory', OwningUser=porg, OwningApplication=app,
                           ChangeAction='ADDED', CreationDate=int(time.time()))


def _contextos(f):
    """Contextos 3D (Body) e 2D (Axis). O Revit usa 'Axis' para a linha de
    locação da parede e 'Body' para o sólido."""
    o3 = _ponto3(f, 0, 0, 0)
    a3 = f.create_entity('IfcAxis2Placement3D', Location=o3)
    body = f.create_entity('IfcGeometricRepresentationContext',
                           ContextIdentifier='Body', ContextType='Model',
                           CoordinateSpaceDimension=3, Precision=1e-5,
                           WorldCoordinateSystem=a3)
    o2 = _ponto2(f, 0, 0)
    a2 = f.create_entity('IfcAxis2Placement2D', Location=o2)
    axis = f.create_entity('IfcGeometricRepresentationContext',
                           ContextIdentifier='Axis', ContextType='Plan',
                           CoordinateSpaceDimension=2, Precision=1e-5,
                           WorldCoordinateSystem=a2)
    return body, axis


def _material_com_camada(f, hist, nome, espessura):
    """IfcMaterial + IfcMaterialLayerSet + uso. É isso que faz o Revit criar a
    parede com espessura composta em vez de um sólido solto."""
    mat = f.create_entity('IfcMaterial', Name=nome)
    camada = f.create_entity('IfcMaterialLayer', Material=mat,
                             LayerThickness=float(espessura))
    conjunto = f.create_entity('IfcMaterialLayerSet', MaterialLayers=[camada],
                               LayerSetName='%s %gmm' % (nome, round(espessura * 1000)))
    uso = f.create_entity('IfcMaterialLayerSetUsage', ForLayerSet=conjunto,
                          LayerSetDirection='AXIS2', DirectionSense='POSITIVE',
                          OffsetFromReferenceLine=-float(espessura) / 2.0)
    return uso


def _associa(f, hist, objeto, material_uso):
    f.create_entity('IfcRelAssociatesMaterial', GlobalId=_gid(), OwnerHistory=hist,
                    RelatedObjects=[objeto], RelatingMaterial=material_uso)


def _pset(f, hist, objeto, nome, valores):
    props = []
    for k, v in valores.items():
        if isinstance(v, bool):
            val = f.create_entity('IfcBoolean', v)
        elif isinstance(v, (int, float)):
            val = f.create_entity('IfcReal', float(v))
        else:
            val = f.create_entity('IfcLabel', str(v))
        props.append(f.create_entity('IfcPropertySingleValue', Name=k, NominalValue=val))
    ps = f.create_entity('IfcPropertySet', GlobalId=_gid(), OwnerHistory=hist,
                         Name=nome, HasProperties=props)
    f.create_entity('IfcRelDefinesByProperties', GlobalId=_gid(), OwnerHistory=hist,
                    RelatedObjects=[objeto], RelatingPropertyDefinition=ps)


# ------------------------------------------------------------------ estrutura

def _estrutura(f, hist, spec):
    proj = f.create_entity('IfcProject', GlobalId=_gid(), OwnerHistory=hist,
                          Name=spec.get('projeto', 'Projeto'),
                          UnitsInContext=_unidades(f))
    body, axis = _contextos(f)
    proj.RepresentationContexts = [body, axis]
    proj.RepresentationContexts = [body, axis]
    site = f.create_entity('IfcSite', GlobalId=_gid(), OwnerHistory=hist,
                           Name=spec.get('local', 'Terreno'),
                           CompositionType='ELEMENT')
    edif = f.create_entity('IfcBuilding', GlobalId=_gid(), OwnerHistory=hist,
                           Name=spec.get('edificacao', 'Edificação'),
                           CompositionType='ELEMENT')
    f.create_entity('IfcRelAggregates', GlobalId=_gid(), OwnerHistory=hist,
                    RelatingObject=proj, RelatedObjects=[site])
    f.create_entity('IfcRelAggregates', GlobalId=_gid(), OwnerHistory=hist,
                    RelatingObject=site, RelatedObjects=[edif])

    niveis = {}
    ordem = []
    for n in spec['niveis']:
        st = f.create_entity('IfcBuildingStorey', GlobalId=_gid(), OwnerHistory=hist,
                             Name=n['nome'], CompositionType='ELEMENT',
                             Elevation=float(n['elevacao']))
        niveis[n['nome']] = {'ent': st, 'elev': float(n['elevacao']),
                             'altura': float(n.get('altura', 2.8)), 'itens': []}
        ordem.append(n['nome'])
    f.create_entity('IfcRelAggregates', GlobalId=_gid(), OwnerHistory=hist,
                    RelatingObject=edif,
                    RelatedObjects=[niveis[n]['ent'] for n in ordem])
    return proj, body, axis, niveis, ordem


# ------------------------------------------------------------------ elementos

def _parede(f, hist, ctx, nivel, w, indice):
    (x1, y1), (x2, y2) = w['p1'], w['p2']
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1e-6:
        raise ValueError('parede %d com comprimento zero' % indice)
    ang = math.atan2(y2 - y1, x2 - x1)
    t = float(w.get('espessura', 0.15))
    h = float(w.get('altura') or nivel['altura'])
    z = nivel['elev'] + float(w.get('base', 0.0))

    perfil = f.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA',
        Position=f.create_entity('IfcAxis2Placement2D',
                                 Location=_ponto2(f, L / 2.0, 0.0)),
        XDim=L, YDim=t)
    pos = f.create_entity('IfcAxis2Placement3D',
                          Location=_ponto3(f, x1, y1, z),
                          Axis=_dir(f, 0, 0, 1),
                          RefDirection=_dir(f, math.cos(ang), math.sin(ang), 0))
    solido = f.create_entity('IfcExtrudedAreaSolid', SweptArea=perfil, Position=pos,
                             ExtrudedDirection=_dir(f, 0, 0, 1), Depth=h)
    rep_body = f.create_entity('IfcShapeRepresentation', ContextOfItems=ctx['body'],
                               RepresentationIdentifier='Body',
                               RepresentationType='SweptSolid', Items=[solido])
    eixo = f.create_entity('IfcPolyline', Points=[_ponto2(f, x1, y1), _ponto2(f, x2, y2)])
    rep_axis = f.create_entity('IfcShapeRepresentation', ContextOfItems=ctx['axis'],
                               RepresentationIdentifier='Axis',
                               RepresentationType='Curve2D', Items=[eixo])

    parede = f.create_entity(
        'IfcWallStandardCase', GlobalId=_gid(), OwnerHistory=hist,
        Name=w.get('nome', 'Parede %02d' % (indice + 1)), Tag='P%02d' % (indice + 1),
        Representation=f.create_entity('IfcProductDefinitionShape',
                                       Representations=[rep_axis, rep_body]))
    uso = _material_com_camada(f, hist, w.get('material', 'Alvenaria'), t)
    _associa(f, hist, parede, uso)
    _pset(f, hist, parede, 'Pset_WallCommon', {
        'IsExternal': bool(w.get('externo', False)),
        'LoadBearing': bool(w.get('estrutural', False)),
        'Reference': w.get('nome', 'Parede %02d' % (indice + 1)),
    })
    dados = {'L': L, 't': t, 'h': h, 'z': z, 'ang': ang, 'p1': (x1, y1), 'p2': (x2, y2)}
    return parede, dados


def _laje(f, hist, ctx, nivel, s, indice):
    cont = [(float(p[0]), float(p[1])) for p in s['contorno']]
    if len(cont) < 3:
        raise ValueError('laje %d com menos de 3 pontos' % indice)
    esp = float(s.get('espessura', 0.12))
    topo = nivel['elev'] + float(s.get('topo', 0.0))
    base = topo - esp
    pts = [_ponto2(f, x, y) for x, y in cont]
    pts.append(pts[0])
    perfil = f.create_entity('IfcArbitraryClosedProfileDef', ProfileType='AREA',
                             OuterCurve=f.create_entity('IfcPolyline', Points=pts))
    solido = f.create_entity('IfcExtrudedAreaSolid', SweptArea=perfil,
                             Position=f.create_entity('IfcAxis2Placement3D',
                                                      Location=_ponto3(f, 0, 0, base)),
                             ExtrudedDirection=_dir(f, 0, 0, 1), Depth=esp)
    rep = f.create_entity('IfcShapeRepresentation', ContextOfItems=ctx['body'],
                          RepresentationIdentifier='Body',
                          RepresentationType='SweptSolid', Items=[solido])
    laje = f.create_entity('IfcSlab', GlobalId=_gid(), OwnerHistory=hist,
                           PredefinedType='FLOOR',
                           Name=s.get('nome', 'Laje %02d' % (indice + 1)),
                           Tag='L%02d' % (indice + 1),
                           Representation=f.create_entity('IfcProductDefinitionShape',
                                                          Representations=[rep]))
    _pset(f, hist, laje, 'Pset_SlabCommon', {
        'IsExternal': bool(s.get('externo', False)),
        'LoadBearing': bool(s.get('estrutural', True)),
        'Reference': s.get('nome', 'Laje %02d' % (indice + 1)),
    })
    area = abs(sum(cont[i][0] * cont[(i + 1) % len(cont)][1] -
                   cont[(i + 1) % len(cont)][0] * cont[i][1]
                   for i in range(len(cont)))) / 2.0
    return laje, {'area': area, 'esp': esp, 'base': base, 'topo': topo}


def _vao(f, hist, ctx, parede, d, v, indice):
    """Vão retangular ao longo do eixo da parede (IfcOpeningElement + void)."""
    ini = float(v.get('inicio', 0.5))
    larg = float(v.get('largura', 0.9))
    alt = float(v.get('altura', 2.1))
    pei = float(v.get('peitoril', 0.0))
    if ini < 0 or ini + larg > d['L'] + 1e-9:
        raise ValueError('vão %d fora da parede (inicio %.2f + largura %.2f > L %.2f)'
                         % (indice, ini, larg, d['L']))
    folga = 0.05
    perfil = f.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA',
        Position=f.create_entity('IfcAxis2Placement2D',
                                 Location=_ponto2(f, ini + larg / 2.0, 0.0)),
        XDim=larg + 2 * folga, YDim=d['t'] + 2 * folga)
    pos = f.create_entity('IfcAxis2Placement3D',
                          Location=_ponto3(f, d['p1'][0], d['p1'][1], d['z'] + pei - folga),
                          Axis=_dir(f, 0, 0, 1),
                          RefDirection=_dir(f, math.cos(d['ang']), math.sin(d['ang']), 0))
    solido = f.create_entity('IfcExtrudedAreaSolid', SweptArea=perfil, Position=pos,
                             ExtrudedDirection=_dir(f, 0, 0, 1), Depth=alt + 2 * folga)
    rep = f.create_entity('IfcShapeRepresentation', ContextOfItems=ctx['body'],
                          RepresentationIdentifier='Body',
                          RepresentationType='SweptSolid', Items=[solido])
    vao = f.create_entity('IfcOpeningElement', GlobalId=_gid(), OwnerHistory=hist,
                          Name=v.get('nome', 'Vão %02d' % (indice + 1)),
                          Tag='V%02d' % (indice + 1),
                          Representation=f.create_entity('IfcProductDefinitionShape',
                                                         Representations=[rep]))
    f.create_entity('IfcRelVoidsElement', GlobalId=_gid(), OwnerHistory=hist,
                    RelatingBuildingElement=parede, RelatedOpeningElement=vao)
    return vao, {'larg': larg, 'alt': alt}


# ------------------------------------------------------------------ montagem

def constroi(spec, schema='IFC4'):
    f = ifcopenshell.file(schema=schema)
    hist = _owner(f)
    proj, body, axis, niveis, ordem = _estrutura(f, hist, spec)
    ctx = {'body': body, 'axis': axis}

    # a spec pode apontar o nível por nome; ausente = primeiro nível
    padrao = ordem[0]
    paredes = []
    for i, w in enumerate(spec.get('paredes', [])):
        nivel = niveis[w.get('nivel', padrao)]
        p, dados = _parede(f, hist, ctx, nivel, w, i)
        nivel['itens'].append(p)
        paredes.append((p, dados))

    for i, s in enumerate(spec.get('lajes', [])):
        nivel = niveis[s.get('nivel', padrao)]
        l, _d = _laje(f, hist, ctx, nivel, s, i)
        nivel['itens'].append(l)

    for i, v in enumerate(spec.get('vaos', [])):
        k = int(v.get('parede', 0))
        if not (0 <= k < len(paredes)):
            raise ValueError('vão %d aponta para parede %d inexistente' % (i, k))
        p, dados = paredes[k]
        vao, _d = _vao(f, hist, ctx, p, dados, v, i)
        niveis[v.get('nivel', padrao)]['itens'].append(vao)

    for nome in ordem:
        itens = niveis[nome]['itens']
        if not itens:
            continue
        f.create_entity('IfcRelContainedInSpatialStructure', GlobalId=_gid(),
                        OwnerHistory=hist, RelatingStructure=niveis[nome]['ent'],
                        RelatedElements=itens)
    return f


def resumo(caminho):
    """Reabre o IFC e confere estrutura + volumes reais das paredes/lajes."""
    m = ifcopenshell.open(caminho)
    import ifcopenshell.geom as g
    s = g.settings()
    s.set('use-world-coords', True)

    vol = {}
    try:
        it = g.iterator(s, m)
        for sh in it:
            vol[sh.guid] = sh.geometry
    except Exception as exc:                       # kernel ausente
        print('  (geometria não avaliada: %s)' % exc)

    def volume(ent):
        geo = vol.get(ent.GlobalId)
        if geo is None:
            return None
        v = geo.verts
        faces = geo.faces
        if not faces:
            return None
        tot = 0.0
        for i in range(0, len(faces), 3):
            a, b, c = faces[i], faces[i + 1], faces[i + 2]
            ax, ay, az = v[3 * a], v[3 * a + 1], v[3 * a + 2]
            bx, by, bz = v[3 * b], v[3 * b + 1], v[3 * b + 2]
            cx, cy, cz = v[3 * c], v[3 * c + 1], v[3 * c + 2]
            tot += (ax * (by * cz - bz * cy)
                    - ay * (bx * cz - bz * cx)
                    + az * (bx * cy - by * cx)) / 6.0
        return abs(tot)

    linhas = []
    paredes = m.by_type('IfcWallStandardCase')
    for p in paredes:
        ids = [r.RepresentationIdentifier for r in p.Representation.Representations]
        v = volume(p)
        linhas.append(('parede', p.Name, 'Axis' in ids and 'Body' in ids, v))
    lajes = m.by_type('IfcSlab')
    for l in lajes:
        v = volume(l)
        linhas.append(('laje', l.Name, True, v))
    vaos = m.by_type('IfcOpeningElement')

    print('  schema %s | pavimentos %d | paredes %d | lajes %d | vãos %d' % (
        m.schema, len(m.by_type('IfcBuildingStorey')), len(paredes), len(lajes), len(vaos)))
    if vol:
        ruims = [l for l in linhas if l[3] is None or l[3] <= 0]
        print('  volumes: %d elementos com volume > 0 | sem volume: %d' % (
            len(linhas) - len(ruims), len(ruims)))
        for tipo, nome, ok_repr, v in linhas[:4]:
            print('    %-6s %-16s repr ok=%s volume=%s' % (
                tipo, nome, ok_repr, ('%.4f m3' % v) if v else 'n/a'))
    return m


SPEC_EXEMPLO = {
    'projeto': 'Casa Demonstração',
    'local': 'Terreno',
    'edificacao': 'Residência',
    'niveis': [
        {'nome': 'Térreo', 'elevacao': 0.0, 'altura': 2.8},
        {'nome': 'Pavimento 1', 'elevacao': 2.8, 'altura': 2.8},
    ],
    'paredes': [
        {'nivel': 'Térreo', 'nome': 'Parede Norte', 'p1': [0, 0], 'p2': [8, 0],
         'espessura': 0.15, 'externo': True},
        {'nivel': 'Térreo', 'nome': 'Parede Leste', 'p1': [8, 0], 'p2': [8, 6],
         'espessura': 0.15, 'externo': True},
        {'nivel': 'Térreo', 'nome': 'Parede Sul', 'p1': [8, 6], 'p2': [0, 6],
         'espessura': 0.15, 'externo': True},
        {'nivel': 'Térreo', 'nome': 'Parede Oeste', 'p1': [0, 6], 'p2': [0, 0],
         'espessura': 0.15, 'externo': True},
        {'nivel': 'Térreo', 'nome': 'Divisória', 'p1': [4, 0], 'p2': [4, 6],
         'espessura': 0.10},
        {'nivel': 'Pavimento 1', 'nome': 'P1 Norte', 'p1': [0, 0], 'p2': [8, 0],
         'espessura': 0.15, 'externo': True},
        {'nivel': 'Pavimento 1', 'nome': 'P1 Sul', 'p1': [8, 6], 'p2': [0, 6],
         'espessura': 0.15, 'externo': True},
    ],
    'lajes': [
        {'nivel': 'Térreo', 'nome': 'Laje Térreo', 'espessura': 0.12, 'topo': 0.0,
         'contorno': [[0, 0], [8, 0], [8, 6], [0, 6]]},
        {'nivel': 'Pavimento 1', 'nome': 'Laje Piso 1', 'espessura': 0.12, 'topo': 0.0,
         'contorno': [[0, 0], [8, 0], [8, 6], [0, 6]]},
    ],
    'vaos': [
        {'parede': 0, 'nome': 'Porta Entrada', 'inicio': 1.0, 'largura': 0.9,
         'altura': 2.1, 'peitoril': 0.0},
        {'parede': 0, 'nome': 'Janela 1', 'inicio': 4.0, 'largura': 1.2,
         'altura': 1.2, 'peitoril': 1.0},
        {'parede': 1, 'nome': 'Janela Leste', 'inicio': 2.0, 'largura': 1.2,
         'altura': 1.2, 'peitoril': 1.0},
    ],
}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Gera IFC (paredes/lajes/vãos) para abrir no Revit.')
    ap.add_argument('spec', nargs='?', help='JSON com a descrição do modelo')
    ap.add_argument('saida', nargs='?', default='modelo.ifc', help='arquivo .ifc de saída')
    ap.add_argument('--schema', default='IFC4', choices=['IFC4', 'IFC2X3'])
    ap.add_argument('--exemplo', action='store_true', help='imprime a spec de exemplo')
    ap.add_argument('--verifica', action='store_true', help='reabre e confere volumes')
    args = ap.parse_args(argv)

    if args.exemplo:
        print(json.dumps(SPEC_EXEMPLO, indent=2, ensure_ascii=False))
        return 0
    if not args.spec:
        ap.error('informe a spec (ou use --exemplo)')

    with open(args.spec) as fh:
        spec = json.load(fh)
    modelo = constroi(spec, args.schema)
    modelo.write(args.saida)
    print('IFC %s gravado em %s' % (args.schema, args.saida))
    resumo(args.saida)
    return 0


if __name__ == '__main__':
    sys.exit(main())
