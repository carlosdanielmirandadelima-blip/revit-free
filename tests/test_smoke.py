#!/usr/bin/env python3
"""Teste de fumaça do rvttool: roda os comandos principais sobre a amostra
avancada e verifica invariantes. Uso: python3 tests/test_smoke.py
"""
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(RAIZ, 'src', 'rvttool.py')
AMOSTRA = os.path.join(RAIZ, 'samples', 'rac_advanced_sample_project.rvt')

falhas = []


def checa(cond, msg):
    print(('  ok   ' if cond else '  FALHA') + ' ' + msg)
    if not cond:
        falhas.append(msg)


def roda(*args, **kw):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True,
                          text=True, **kw)


def main():
    if not os.path.exists(AMOSTRA):
        print('amostra ausente:', AMOSTRA)
        return 2
    tmp = tempfile.mkdtemp(prefix='rvttest')

    print('lista de streams')
    r = roda('lista', AMOSTRA)
    checa(r.returncode == 0 and 'Partitions/3' in r.stdout, 'stream Partitions/3 presente')

    print('verifica integridade')
    r = roda('verifica', AMOSTRA)
    checa(r.returncode == 0, 'verifica executou sem erro')

    print('curvas type-4')
    import json
    cp = os.path.join(tmp, 'curvas.json')
    r = roda('curvas', AMOSTRA, cp)
    linhas = json.load(open(cp)) if os.path.exists(cp) else []
    checa(r.returncode == 0 and len(linhas) > 500, 'extraiu mais de 500 curvas (%d)' % len(linhas))
    checa(all(abs(l['comp']) > 0 for l in linhas), 'todas as curvas tem comprimento != 0')
    import math
    ok = all(abs(math.hypot(l['x2'] - l['x1'], l['y2'] - l['y1']) - l['comp'])
             < 0.02 * max(1, abs(l['comp'])) for l in linhas)
    checa(ok, 'comprimento == distancia em todas as curvas (validacao matematica)')

    print('dxf')
    dp = os.path.join(tmp, 'planta.dxf')
    r = roda('dxf', AMOSTRA, dp)
    checa(r.returncode == 0 and os.path.getsize(dp) > 10000, 'DXF gerado')

    print('poligonos')
    pp = os.path.join(tmp, 'contornos.dxf')
    r = roda('poligonos', AMOSTRA, pp)
    checa(r.returncode == 0 and os.path.exists(pp), 'DXF de contornos gerado')
    try:
        import ezdxf
        from ezdxf.recover import readfile
        doc, aud = readfile(pp)
        checa(len(aud.errors) == 0, 'DXF de contornos sem erros de auditoria')
        pls = list(doc.modelspace().query('LWPOLYLINE'))
        checa(len(pls) > 20, 'contornos fechados (%d)' % len(pls))
        checa(all(p.closed for p in pls), 'todos os contornos fechados')
        checa(all(len(p.get_points('xy')) >= 3 for p in pls), 'todo contorno tem >= 3 lados')
        lado = [f for f in os.listdir(tmp) if f.startswith('contornos_') and f.endswith('.json')]
        checa(len(lado) >= 1, 'JSON de contornos ao lado do DXF (%d)' % len(lado))
        if lado:
            dados = json.load(open(os.path.join(tmp, lado[0])))
            checa(all(d['area_m2'] > 0 for d in dados), 'areas positivas no JSON de contornos')
    except ImportError:
        print('  (ezdxf ausente — teste de contornos pulado)')

    print('ifc')
    ip = os.path.join(tmp, 'modelo.ifc')
    r = roda('ifc', AMOSTRA, ip)
    checa(r.returncode == 0 and os.path.exists(ip), 'IFC gerado')
    try:
        import ifcopenshell
        m = ifcopenshell.open(ip)
        checa(m.schema == 'IFC4', 'IFC4')
        pav = m.by_type('IfcBuildingStorey')
        checa(len(pav) >= 1, 'pelo menos 1 pavimento (%d)' % len(pav))
        checa(all(p.Representation is not None for p in pav), 'todo pavimento tem geometria')
        n = sum(len(it.Elements) for p in pav for r_ in p.Representation.Representations
                for it in r_.Items)
        checa(n > 500, 'curvas no IFC (%d)' % n)
    except ImportError:
        print('  (ifcopenshell ausente — teste de IFC pulado)')

    print()
    if falhas:
        print('FALHAS: %d' % len(falhas))
        for f in falhas:
            print('  -', f)
        return 1
    print('TODOS OS TESTES PASSARAM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
