# Gerar arquivos para o Revit (direção de saída)

Este documento cobre o caminho **inverso** do `rvttool`: em vez de ler `.rvt`,
gerar arquivos que o Revit consome.

## O que o Revit aceita de fora

| Formato | Revit aceita? | Nós geramos? |
|---|---|---|
| **IFC** (`.ifc`) | Sim, nativo — *Abrir* (converte em elementos) ou *Vincular IFC* | **Sim** (`src/criar_ifc.py` e `rvttool ifc`) |
| **DXF / DWG** | Sim, como CAD importado (linhas, base para traçar) | Sim (`rvttool dxf`, `rvttool poligonos`) |
| **SAT (ACIS)** | Sim, como sólido importado | Não (exportador ACIS é proprietário) |
| **SKP (SketchUp)** | Sim | Não |
| **.rvt / .rfa** | Formato proprietário do Revit | **Não** — e não é realista: o container é fechado e o Revit valida a estrutura ao abrir |

Ou seja: **IFC é a ponte prática**. `.rvt` gravado à mão não é uma opção viável.

## Como gerar

```bash
python3 src/criar_ifc.py --exemplo > minha_casa.json     # spec de partida
python3 src/criar_ifc.py minha_casa.json casa.ifc --schema IFC4 --verifica
```

A spec é JSON simples (metros):

```json
{
  "niveis":  [{"nome": "Térreo", "elevacao": 0.0, "altura": 2.8}],
  "paredes": [{"nivel": "Térreo", "nome": "Parede Norte",
               "p1": [0, 0], "p2": [8, 0], "espessura": 0.15, "externo": true}],
  "lajes":   [{"nivel": "Térreo", "espessura": 0.12,
               "contorno": [[0, 0], [8, 0], [8, 6], [0, 6]]}],
  "vaos":    [{"parede": 0, "inicio": 4.0, "largura": 1.2,
               "altura": 1.2, "peitoril": 1.0}]
}
```

## O que o Revit reconhece no arquivo gerado

| IFC gerado | Vira no Revit |
|---|---|
| `IfcWallStandardCase` com `Axis` + `Body` | Parede, com linha de locação e espessura |
| `IfcMaterialLayerSetUsage` | Composição/espessura da parede |
| `IfcSlab` (`PredefinedType=FLOOR`) | Piso |
| `IfcOpeningElement` + `IfcRelVoidsElement` | Abertura na parede (porta/janela a preencher) |
| `IfcBuildingStorey` | Nível |
| `IfcRelContainedInSpatialStructure` | Elemento no nível certo |

`Axis` + `Body` + camada de material são os três detalhes que fazem a diferença
entre "sólido genérico" e "parede editável" no Revit.

## Qual schema usar

- **IFC2X3** — caminho mais maduro do importador do Revit; use em Revit 2018 e
  anteriores (funciona em versões novas também).
- **IFC4** — Revit 2019+.

Os dois saem do mesmo gerador (`--schema`).

## O que foi verificado aqui

- Validação de schema com `ifcopenshell.validate`: **0 erros** em IFC4 e IFC2X3.
- Geometria avaliada pelo kernel (`ifcopenshell.geom`): **volumes exatos** —
  parede 8 × 0,15 × 2,8 = 3,3600 m³ e 6 × 0,15 × 2,8 = 2,5200 m³, laje
  8 × 6 × 0,12 = 5,7600 m³, valor idêntico nos dois schemas.
- Parede com vãos perde volume (2,7840 < 3,3600), provando que o boolean de
  `IfcOpeningElement` está sendo aplicado.
- Leitura independente: o FreeCAD importa o arquivo sem erro
  (`nativeifc.ifc_import.insert`).

## O que **não** foi verificado

- **Não abri esses arquivos no Revit** (não há Revit nesta máquina — é o motivo
  do projeto existir). A validação foi por schema + kernel geométrico + segundo
  leitor, não no Revit.
- Não geramos `.rvt` nem `.rfa`, nem famílias paramétricas.
- A spec não cobre telhado, escada, pilar, laje inclinada ou terreno.

## Alternativa: modelar no FreeCAD e exportar IFC

O FreeCAD 1.1.4 (BIM) tem exportação IFC no menu, mas o caminho *headless* é
frágil (`importers.exportIFC` depende de GUI e falhou aqui com
`TypeError: 'module' object is not callable`). Para uso manual: no FreeCAD, menu
**BIM → Exportar IFC**. Não testado nesta máquina.
