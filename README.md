# revit-free

> **Leia arquivos `.rvt` do Autodesk Revit sem o Revit** — formato decifrado por engenharia reversa, 100% Python, roda em Linux/Mac/Windows.

[![formato decifrado](https://img.shields.io/badge/compress%C3%A3o-decifrada-brightgreen)](docs/ESTRUTURA.md) [![verifica%C3%A7%C3%A3o](https://img.shields.io/badge/CRC32-75%25%20%2B%20dados%20%C3%ADntegros-brightgreen)](ISSUES.md)

Engenharia reversa do formato de arquivo `.rvt` (Autodesk Revit) — leitura de projetos
Revit **sem o Revit**, em Linux.

## Descoberta principal (2025-11)

O `.rvt` é um **OLE Compound File** (mesmo container de .doc/.xls antigo). Os streams
`Partitions/*` — onde mora o banco de dados do projeto — **não são opacos**: são uma
sequência de registros gzip com **janela deflate compartilhada**:

```
[10B header gzip][deflate raw][8B CRC+ISIZE][32B rodapé] [10B header gzip][deflate]...
```

- Cada registro tem header gzip próprio (`1f 8b 08 00`), mas o **deflate continua a
  janela do registro anterior** → descomprimir isolado falha com `invalid distance too far back`
- **Solução**: `zlib.decompressobj(-15, zdict=cauda_de_32KB_do_output_anterior)`
- O campo `ISIZE` do trailer valida cada membro
- Resultado: 16 MB de partição → 77 MB de banco de dados estruturado, com strings
  UTF-16 legíveis (nomes de famílias, níveis, pranchas, parâmetros)

## PIPELINE FREECAD FUNCIONANDO

`rvttool macro samples/rac_advanced_sample_project.rvt import.FCMacro` gera uma
macro autocontida que, executada no FreeCAD (Macro > Macros...), cria um
documento com as linhas de localizacao de cada nivel (Part::Feature, metros) e
uma planilha com o inventario de elementos nomeados. Testado no FreeCAD 1.1.4:
documento com 13 objetos, 9.741 arestas no nivel 0, planilha populada.
Exemplos prontos em `exemplos/` (`.FCMacro`, `.dxf`, `.FCStd`).

Alternativa leve: `rvttool dxf` gera DXF R2010 com uma camada por nivel
(`NIVEL_+0.000`, `NIVEL_+4.370`, ...) — abre nativamente no FreeCAD.

### Catalogo de simbolos de anotacao

`rvttool catalogo arquivo.rvt catalogo.csv` extrai os registros
`[01 00 00 00][ptr][01 00 00 00][len][nome UTF-16][classe u32][id u32]` e grava
`nome,classe,id`. Amostra avancada: 669 registros, 30 nomes, 15 classes, 668 ids
unicos (faixa 86k+, a mesma do ElemTable). A `classe` e estavel por nome e igual
nos dois arquivos de amostra (`Arrowhead 1` = 170), mas e **compartilhada** por
nomes parecidos (`Diagonal 1/8"`, `Diagonal 3 mm`, `Heavy End 3mm` = 174) —
por isso e documentada como classe de simbolo, nao como categoria de elemento.

### Contornos fechados

`rvttool poligonos arquivo.rvt contornos.dxf` reconstroi os **contornos
fechados** das curvas (extremidades agrupadas com tolerancia de 1 cm, tracado
preferindo o menor angulo de virada) e grava `LWPOLYLINE` fechada por contorno,
mais um JSON por nivel com `lados`, `perimetro_m`, `area_m2` e o vetor de
pontos. Segmentos repetidos sao deduplicados (mesma regra do `ifc`).
Amostra avancada: 76 contornos (nivel 0: 68, mediana 76 m2; niveis superiores:
4 contornos de 240 m2 = a laje). O `ifc` inclui esses contornos no pavimento
como representacao `Contorno`. Contornos maiores que 20x a
mediana ganham `"suspeita": "laco_muito_grande"` — normalmente sao tracejados
por linhas de grade/site, nao ambientes.

### IFC (BIM)

`rvttool ifc arquivo.rvt modelo.ifc` gera um IFC4 com `IfcProject` → `IfcSite`
→ `IfcBuilding` → um `IfcBuildingStorey` por nivel, cada pavimento com a
geometria de referencia (`IfcGeometricCurveSet` de `IfcPolyline`) e um
`Pset_RevitImport`. Unidades em metros; niveis com menos de 4 curvas sao
descartados como ruido (niveis espurios de 1-3 linhas). Cada pavimento tem duas
representacoes: `Reference` (segmentos) e `Contorno` (poligonais fechadas, quando
existem). Testado com `ifcopenshell 0.9.0` (reabre e itera a geometria).

A geometria entra como **referencia** dentro do pavimento, nao como
`IfcWall`/`IfcSlab`: o vinculo elemento→geometria ainda nao foi decodificado
(ver `ISSUES.md`, item 3).

## Criar arquivos que o Revit abre (saida)

A direcao inversa — gerar modelo para o Revit — usa **IFC**, que o Revit abre
nativamente. `src/criar_ifc.py` monta o arquivo a partir de um JSON simples
(niveis, paredes, lajes, vaos) com geometria real:

```bash
python3 src/criar_ifc.py --exemplo > casa.json
python3 src/criar_ifc.py casa.json casa.ifc --schema IFC4 --verifica
python3 src/criar_ifc.py casa.json casa2x3.ifc --schema IFC2X3
```

Gera `IfcWallStandardCase` com representacao `Axis` + `Body` e
`IfcMaterialLayerSetUsage` (vira parede com espessura no Revit), `IfcSlab`,
`IfcOpeningElement` + `IfcRelVoidsElement` (vaos), `IfcBuildingStorey` e
`IfcRelContainedInSpatialStructure`. Verificado: 0 erros de schema em IFC4 e
IFC2X3, volumes exatos pelo kernel (parede 8x0,15x2,8 = 3,3600 m3; laje
8x6x0,12 = 5,7600 m3), vao reduzindo volume (2,7840 < 3,3600).

Nao geramos `.rvt`/`.rfa` (formato proprietario fechado). Detalhes, tabela do
que o Revit reconhece e limitacoes: `docs/REVIT_SAIDA.md`.

Exemplos prontos: `exemplos/casa_demo_spec.json`,
`exemplos/casa_demo_IFC4.ifc`, `exemplos/casa_demo_IFC2X3.ifc`.

## Ida e volta: Revit/AutoCAD -> FreeCAD -> Revit

O ciclo funciona por IFC, e o lado do FreeCAD e **lossless** (medido):

```bash
python3 src/rt_freecad.py entrada.ifc saida.ifc          # edita/abre e salva IFC
python3 src/rt_freecad.py entrada.ifc saida.ifc --renomear "Parede Norte=Nova"
python3 src/ifc_diff.py antes.ifc depois.ifc             # mede o que sobreviveu
```

Medicao real (7 paredes, 2 lajes, 3 vaos, 2 pavimentos): **50/50 GUIDs
preservados**, volumes com diferenca maxima **0,000000 m3**, psets e
pavimentos intactos; ao renomear uma parede, 11 de 12 nomes ficam iguais.
Aviso importante: usar o exportador generico do FreeCAD
(`importers.exportIFC`) num documento NativeIFC **destroi** o arquivo
(2 pavimentos -> 0, 9 psets -> 0, 50 GUIDs -> 0 comuns). Use
`ifc_tools.save_ifc` — o `rt_freecad.py` ja faz isso.

"Sem perder nada" entre Revit e qualquer outra ferramenta **nao existe**:
familias, ids de elemento, parametros nao mapeados, vistas, pranchas, cotas,
fases e worksets nao tem representacao em IFC. Tabela completa do que se perde,
como configurar a exportacao do Revit, *Abrir IFC* vs *Vincular IFC* e o caso
DWG/AutoCAD: `docs/ROUNDTRIP.md`.

## Uso

```bash
python3 src/rvttool.py versao  arquivo.rvt                  # versão do Revit
python3 src/rvttool.py lista   arquivo.rvt                  # streams OLE
python3 src/rvttool.py dump    arquivo.rvt Partitions/3 out.bin
python3 src/rvttool.py strings arquivo.rvt                  # catálogo de strings
python3 src/rvttool.py verifica arquivo.rvt                 # estatísticas de CRC
python3 src/rvttool.py elementos arquivo.rvt                # árvore + resumo
python3 src/rvttool.py exporta arquivo.rvt elementos.json   # TODOS os elementos
python3 src/rvttool.py paredes arquivo.rvt paredes.json     # location lines
python3 src/rvttool.py plano  arquivo.rvt plano.svg         # planta 2D (SVG)
python3 src/rvttool.py curvas arquivo.rvt curvas.json       # curvas type-4 (JSON)
python3 src/rvttool.py dxf    arquivo.rvt planta.dxf        # DXF por nivel
python3 src/rvttool.py macro  arquivo.rvt import.FCMacro    # macro FreeCAD
python3 src/rvttool.py ifc    arquivo.rvt modelo.ifc        # IFC4 (pavimentos)
python3 src/rvttool.py poligonos arquivo.rvt contornos.dxf   # contornos fechados (DXF+JSON)
python3 src/rvttool.py catalogo arquivo.rvt catalogo.csv     # simbolos: nome, classe, id
```

Testes (o primeiro roda tudo sobre a amostra avancada; o segundo valida o
gerador de IFC nos dois schemas):

```bash
python3 tests/test_smoke.py
python3 tests/test_criar_ifc.py
python3 tests/test_roundtrip.py     # inclui ida e volta pelo FreeCAD
```

**`exporta`** gera um JSON com cada registro de elemento: `id`, `grupo`
(categoria pelo ElemTable), `nome`, `strings` e `lista_strings`. No projeto
de teste (sample oficial da Autodesk, Revit 2017):

- 28.494 registros de elemento, 6.494 com nome
- níveis ("Level 1/2/3"), vistas ("North", "Elevation 2", "Site"),
  famílias ("M_Basic Wall"), tipos de parede ("Generic - 200mm",
  "Exterior - Brick on Mtl. Stud"), pranchas ("A10", "01530.A2"),
  famílias de anotação, materiais e textos de ferramenta
- validado em 2 arquivos Revit 2017 distintos

Veja `exemplos/elementos_amostra.json` e `docs/ESTRUTURA.md`.
## Formato decifrado (detalhes)

**Container**: OLE Compound File (`D0 CF 11 E0`). Streams relevantes:

| Stream | Conteúdo |
|---|---|
| `Partitions/3` | banco de dados principal do projeto (elementos, geometria) |
| `Partitions/4`, `/5` | metadados de views/render, config |
| `Global/ElemTable` | índice de elementos (assinatura interna `0x1f09`) |
| `Global/Latest`, `Formats/Latest` | estado/formato do documento |
| `ProjectInformation` | ZIP com XML de metadados (versão, template) |
| `RevitPreview4.0` | PNG de preview |
| `BasicFileInfo` | versão do Revit que gravou |

**Compressão**: cada stream comprimido é uma cadeia de registros

```
[10B header gzip: 1f 8b 08 00 + mtime 0][deflate raw][CRC32 4B][ISIZE 4B][32B rodapé]
```

- rodapé (32B) contém: magic `0cab`, tamanho comprimido do registro, magic `0cb0`,
  contador sequencial (+4 por registro), tamanho descomprimido, tamanho do próximo
- **o deflate NÃO reinicia a janela entre registros**: descomprimir isolado dá
  `invalid distance too far back`
- **solução**: `zlib.decompressobj(-15, zdict=últimos_32KB_do_output_anterior)`
- `ISIZE` de cada registro valida o tamanho descomprimido
- no arquivo de teste (Revit 2019, 31 MB): 978 registros, 950 OK, 28 falhas,
  16 MB → 77 MB de banco de dados com strings UTF-16 legíveis
  (famílias, níveis, pranchas, parâmetros, textos de anotação)

**Strings dentro do banco**: `[u32 nchars][UTF-16LE]`.

## Estado

- [x] Estrutura OLE mapeada
- [x] Compressão das partições decifrada (gzip em registros + janela compartilhada)
- [x] Extração do banco de dados em texto puro
- [x] **ElemTable parcialmente decodificado** — árvore de elementos
      (gramática `[id][id][0][parent]` + bloco; contagem no header)
- [x] **Registros de elemento localizados** — marcador `5d 02 01 00 00 00 [id]`,
      nome UTF-16 inline, listas de strings `[-1][02 08][len][str]`
- [x] **Extrator de elementos** (`rvttool exporta`): 28.494 registros no
      projeto de teste, 6.494 com nome (níveis, vistas, famílias, pranchas,
      tipos de parede), validado em 2 arquivos Revit 2017 diferentes
- [ ] Seção principal do ElemTable (delta/bit-packed)
- [x] **Location lines de paredes decodificadas** (auto-validadas:
      `hypot(dx,dy) == comprimento`) — `rvttool plano` gera a planta em SVG
- [x] **Importador FreeCAD** (`macro`, `dxf`) — planta por nivel + planilha
      de elementos, testado no FreeCAD 1.1.4
- [x] **Export IFC4** (`ifc`) — pavimentos + geometria de referencia,
      validado reabrindo com ifcopenshell 0.9.0
- [x] **Contornos fechados** (`poligonos`) — reconstrucao de poligonais com
      perimetro/area por nivel (nivel 0 avancado: 131 contornos)
- [x] **Catalogo de simbolos** (`catalogo`) com nome, classe e id real
- [x] **Testes de fumaca** (`tests/test_smoke.py`)
- [ ] Vinculo elemento→geometria (issue 3) — bloqueia `IfcWall`/`IfcSlab` reais
- [ ] Vértices de sólido (teselação identificada)
- [ ] Parâmetros completos por elemento

## Resumo do projeto

O que ja funciona, com numeros medidos, o que esta bloqueado e por que, limites
conhecidos e ordem sugerida para continuar: **[`docs/RESUMO.md`](docs/RESUMO.md)**.

## Aviso legal

Projeto de interoperabilidade: análise própria do formato, sem código da Autodesk.
Licença MIT.
