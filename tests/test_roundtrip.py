#!/usr/bin/env python3
"""Testes de ida e volta: ifc_diff.py e rt_freecad.py.

ifc_diff sempre roda; rt_freecad só se `freecad.cmd` existir no PATH.
"""
import os
import shutil
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIFF = os.path.join(RAIZ, 'src', 'ifc_diff.py')
RT = os.path.join(RAIZ, 'src', 'rt_freecad.py')
CRIA = os.path.join(RAIZ, 'src', 'criar_ifc.py')
falhas = []


def checa(cond, msg):
    print(('  ok   ' if cond else '  FALHA') + ' ' + msg)
    if not cond:
        falhas.append(msg)


def roda(*args):
    return subprocess.run([sys.executable] + list(args), capture_output=True, text=True)


def main():
    tmp = tempfile.mkdtemp(prefix='rttest')
    spec = os.path.join(tmp, 'spec.json')
    with open(spec, 'w') as fh:
        subprocess.run([sys.executable, CRIA, '--exemplo'], stdout=fh, check=True)
    base = os.path.join(tmp, 'base.ifc')
    r = roda(CRIA, spec, base, '--schema', 'IFC4')
    checa(r.returncode == 0, 'IFC base gerado')

    print('ifc_diff: arquivo contra ele mesmo')
    r = roda(DIFF, base, base)
    checa(r.returncode == 0, 'sem diferencas (codigo 0)')
    checa('0 classe(s) com perda' in r.stdout, 'resumo sem perdas')

    print('ifc_diff: detecta perda')
    import ifcopenshell
    m = ifcopenshell.open(base)
    # remove todas as lajes -> o diff tem que acusar perda
    for laje in m.by_type('IfcSlab'):
        m.remove(laje)
    podre = os.path.join(tmp, 'sem_laje.ifc')
    m.write(podre)
    r = roda(DIFF, base, podre)
    checa(r.returncode != 0, 'sai com codigo != 0 quando ha perda')
    checa('IfcSlab' in r.stdout and 'PERDA' in r.stdout, 'aponta IfcSlab como PERDA')

    print('rt_freecad (FreeCAD NativeIFC)')
    if not (shutil.which('freecad.cmd') or shutil.which('freecad')):
        print('  (freecad.cmd ausente — pulado)')
    else:
        vol1 = os.path.join(tmp, 'volta.ifc')
        r = roda(RT, base, vol1)
        checa(r.returncode == 0, 'round-trip sem erro')
        if r.returncode == 0:
            r = roda(DIFF, base, vol1)
            checa(r.returncode == 0, 'nenhuma classe perdida na volta')
            checa('comuns=50' in r.stdout or 'só em A=0' in r.stdout,
                  'GUIDs preservados')
            checa('diferença máx 0.000000' in r.stdout, 'volumes identicos')

        edit = os.path.join(tmp, 'editado.ifc')
        r = roda(RT, base, edit, '--renomear', 'Parede Norte=Editada')
        checa(r.returncode == 0, 'round-trip com edicao')
        if r.returncode == 0:
            m2 = ifcopenshell.open(edit)
            nomes = {p.Name for p in m2.by_type('IfcWallStandardCase')}
            checa('Editada' in nomes, 'edicao aplicada no IFC de saida')
            r = roda(DIFF, base, edit)
            checa('nome idêntico: 11' in r.stdout, 'so o elemento editado mudou')

    print()
    if falhas:
        print('FALHAS: %d' % len(falhas))
        for f in falhas:
            print('  -', f)
        return 1
    print('TODOS OS TESTES DE ROUND-TRIP PASSARAM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
