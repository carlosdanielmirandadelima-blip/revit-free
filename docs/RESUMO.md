# RESUMO DO PROJETO — o que o `revit-free` entrega hoje

Documento de fechamento (Plano A): consolida o que foi construído e medido, o que
está bloqueado, e como usar. Serve para quem chega agora não repetir o caminho.

## O que é

`revit-free` é um projeto de **interoperabilidade** com o formato `.rvt`
(Revit): engenharia reversa própria, sem código da Autodesk, com base no art. 7º
da Lei do Software (acesso ao formato para interoperabilidade). Nada aqui
contorna licença, DRM ou ativação.

Duas direções:

1. **Leitura** — abrir um `.rvt` sem Revit e extrair geometria/inventário para
   FreeCAD, DXF e IFC (`src/rvttool.py`).
2. **Escrita** — gerar IFC que o Revit abre como elementos BIM, e um ciclo de
   ida e volta por IFC (`src/criar_ifc.py`, `src/rt_freecad.py`,
   `src/ifc_diff.py`).

## O que funciona (números medidos, não estimados)

| Capacidade | Comando | Resultado medido |
|---|---|---|
| Ler estrutura OLE e descomprimir partições | `rvttool lista`, `verifica` | 77,7 MB de DB decodificados; 876 registros, 27 com erro duro |
| Inventário de elementos | `rvttool elementos`, `exporta` | 28.494 registros, 6.494 com nome, 3.268 na planilha do FreeCAD |
| Curvas de geometria (tipo 4) | `rvttool curvas` | 2.777 validadas no avançado (`hypot == comprimento`) |
| Planta por nível em DXF | `rvttool dxf` | 3 níveis, 1.646 linhas; camada por nível |
| Planta no FreeCAD | `rvttool macro` | 13 objetos, 9.741 arestas no nível 0; planilha populada |
| Contornos fechados com área | `rvttool poligonos` | 76 contornos (nível 0: 68, mediana 76 m²; 4,37 e 8,17 m: 4 × 241 m²) |
| IFC do próprio `.rvt` (referência) | `rvttool ifc` | 3 pavimentos, 1.722 polylines, 0 erros de schema |
| Catálogo de símbolos com id real | `rvttool catalogo` | 669 registros, 30 nomes, 15 classes, 668 ids únicos |
| **Gerar IFC para o Revit** | `criar_ifc.py` | 7 paredes, 2 lajes, 3 vãos; IFC4 e IFC2x3 com 0 erros de schema |
| Volumes do IFC gerado | `criar_ifc.py --verifica` | parede 3,3600 m³ e 2,5200 m³ exatos; laje 5,7600 m³ exatos |
| **Ida e volta pelo FreeCAD** | `rt_freecad.py` + `ifc_diff.py` | 50/50 GUIDs, volume com diferença máx **0,000000 m³**, psets e pavimentos intactos |
| Comparar dois IFC | `ifc_diff.py` | detecta perda por classe, GUID, volume e pset |

Testes: `tests/test_smoke.py` (20 checks), `tests/test_criar_ifc.py` (26),
`tests/test_roundtrip.py` (12). Todos passam.

## O que está bloqueado — e por quê

O único item não resolvido é o **vínculo elemento → geometria** dentro do `.rvt`
(saber que "esta curva pertence àquela parede"). Sem ele, o IFC extraído do
`.rvt` traz geometria de referência por pavimento, não `IfcWall` com
categoria/material.

Rotas testadas e descartadas com evidência (detalhe em `ISSUES.md`):

1. Marcador mais próximo antes da curva — o `u32` do marcador não é id de
   elemento (é contador/offset local).
2. Família de registros de 48 bytes — é adjacência vértice→segmento; `A`
   reinicia por chunk e não correlaciona com elemento.
3. Tabela de vértices — existe, mas sem stride fixo (26/102 em `p+4`, 102/102
   em `p+8` e em `p+16`): sem o schema do serializador não fecha.
4. Ids de elemento na geometria — testados 668 ids: 1 coincidência acidental.
5. Bbox em registro de elemento — não existe; coordenadas só aparecem em chunks
   de geometria, que não têm strings.
6. Espessura por pareamento de paralelas — histograma plano (0,03–0,23 m), sem
   picos em 0,09/0,14/0,20/0,30: as curvas são linha de locação/grade.

Conclusão honesta: fechar esse item exige reconstruir o schema do serializador
da Autodesk — semanas de trabalho, sem garantia. Não é bloqueio de esforço, é
bloqueio de informação.

## Limites conhecidos

- Não geramos `.rvt` nem `.rfa` (container proprietário fechado; inviável).
- "Ida e volta sem perder nada" entre Revit e qualquer ferramenta **não
  existe**: famílias, ids, parâmetros não mapeados, vistas, pranchas, cotas,
  fases e worksets não têm representação em IFC. Ver `docs/ROUNDTRIP.md`.
- **Nada foi aberto no Revit**: não há Revit nesta máquina. A validação é por
  schema (`ifcopenshell.validate`), kernel geométrico (volumes) e leitura por
  um segundo programa (FreeCAD).
- Registrar o exportador genérico do FreeCAD (`importers.exportIFC`) sobre um
  documento NativeIFC **destrói** o IFC (0/50 GUIDs). Use `ifc_tools.save_ifc`
  ou `src/rt_freecad.py`.

## Se alguém quiser continuar

Ordem de maior retorno:

1. **Testar o IFC gerado no Revit de verdade** — é a única validação que falta
   para a direção de escrita, e é rápida (abrir/vincular + `ifc_diff`).
2. Ampliar a spec do `criar_ifc.py`: pilares, telhado, escada, laje inclinada.
3. Usar os contornos já extraídos do `.rvt` para gerar IFC com `IfcSlab`/
   `IfcSpace` a partir de um projeto real (aproveita 100% do que já funciona).
4. Só então, se ainda fizer sentido, atacar o serializador para o item 3.

## Verificação rápida (para quem clonar)

```bash
python3 tests/test_smoke.py        # leitura do .rvt, DXF, IFC, contornos, catálogo
python3 tests/test_criar_ifc.py    # gerador de IFC (IFC4 + IFC2x3, volumes)
python3 tests/test_roundtrip.py    # ida e volta pelo FreeCAD + diff
```

Requisitos: Python 3.11+, `olefile`, `ezdxf`, `ifcopenshell`; FreeCAD 1.x para
`rt_freecad.py` e `rvttool macro`.
