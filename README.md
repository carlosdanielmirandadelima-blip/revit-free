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
- [ ] Vértices de sólido (teselação identificada)
- [ ] Parâmetros completos por elemento

## Aviso legal

Projeto de interoperabilidade: análise própria do formato, sem código da Autodesk.
Licença MIT.
