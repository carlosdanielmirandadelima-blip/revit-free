#!/usr/bin/env python3
"""rt_freecad.py — passa um IFC pelo FreeCAD (NativeIFC) e grava de volta.

É a peça do ciclo "Revit/AutoCAD -> IFC -> FreeCAD (editar) -> IFC -> Revit".
Roda headless: abre o IFC no FreeCAD, carrega a árvore inteira e salva em IFC
pelo caminho nativo (`ifc_tools.save_ifc`), que preserva GUIDs, psets,
materiais, aberturas e pavimentos.

IMPORTANTE: não use o exportador genérico do FreeCAD (`importers.exportIFC`)
para isso — ele converte objetos do FreeCAD em IFC e devasta a semântica
(medido: 50 GUIDs -> 0 comuns, pavimentos e psets perdidos). Use este script ou
`ifc_tools.save_ifc`.

Uso:
    python3 rt_freecad.py entrada.ifc saida.ifc
    python3 rt_freecad.py entrada.ifc saida.ifc --renomear "Parede Norte=Renomeada"

Requer `freecad.cmd` no PATH (snap do FreeCAD 1.x).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = r'''
import FreeCAD
import nativeifc.ifc_import as I
import nativeifc.ifc_tools as T

doc = FreeCAD.newDocument("RT")
I.insert({entrada!r}, "RT")
raiz = doc.Objects[0]
T.create_children(raiz, recursive=True)

renomear = {renomear!r}
if renomear:
    for obj in doc.Objects:
        try:
            el = T.get_ifc_element(obj)
        except Exception:
            el = None
        if el is not None and getattr(el, "Name", None) in renomear:
            T.set_attribute(T.get_ifcfile(obj), el, "Name", renomear[el.Name])

T.save_ifc(raiz, {saida!r})
print("RT_OK", len(doc.Objects))
'''


def main(argv=None):
    ap = argparse.ArgumentParser(description='Passa um IFC pelo FreeCAD NativeIFC.')
    ap.add_argument('entrada')
    ap.add_argument('saida')
    ap.add_argument('--renomear', action='append', default=[],
                    metavar='NOME=NOVO', help='renomeia um elemento (Name do IFC)')
    args = ap.parse_args(argv)

    exe = shutil.which('freecad.cmd') or shutil.which('freecad')
    if not exe:
        print('freecad.cmd nao encontrado no PATH')
        return 2
    if not os.path.exists(args.entrada):
        print('entrada inexistente:', args.entrada)
        return 2

    mapa = {}
    for par in args.renomear:
        if '=' not in par:
            print('valor invalido em --renomear (use NOME=NOVO):', par)
            return 2
        k, v = par.split('=', 1)
        mapa[k] = v

    home = os.path.expanduser('~')
    tmp = tempfile.mkdtemp(prefix='rtfc_', dir=home)
    # o snap do FreeCAD nao enxerga /tmp nem caminhos fora do home: levar tudo
    # para dentro do home e, no fim, mover o resultado para o destino pedido
    entrada = os.path.abspath(args.entrada)
    if not entrada.startswith(home):
        copia = os.path.join(tmp, 'entrada.ifc')
        shutil.copyfile(entrada, copia)
        entrada = copia
    saida_pedida = os.path.abspath(args.saida)
    if saida_pedida.startswith(home):
        saida = saida_pedida
    else:
        saida = os.path.join(tmp, 'saida.ifc')
    script = os.path.join(tmp, 'rt.py')
    with open(script, 'w') as fh:
        fh.write(SCRIPT.format(entrada=entrada, saida=saida, renomear=mapa))

    r = subprocess.run([exe, '-c', 'exec(open(%r).read())' % script],
                       capture_output=True, text=True)
    ok = 'RT_OK' in (r.stdout or '')
    if not ok:
        print('falhou. stdout:', (r.stdout or '')[-400:])
        print('stderr:', (r.stderr or '')[-800:])
        return 1
    if not os.path.exists(saida):
        print('FreeCAD disse OK mas nao gravou o IFC em', saida)
        print('stdout:', (r.stdout or '')[-400:])
        return 1
    if saida != saida_pedida:
        shutil.copyfile(saida, saida_pedida)
        saida = saida_pedida
    print('FreeCAD: %s' % [l for l in r.stdout.splitlines() if 'RT_OK' in l][0])
    print('IFC gravado em', saida, '(%d bytes)' % os.path.getsize(saida))
    for k, v in mapa.items():
        print('  renomeado:', k, '->', v)
    return 0


if __name__ == '__main__':
    sys.exit(main())
