# Estrutura interna do .rvt — achados até agora

Arquivo de referência: `rac_basic_sample_project.rvt` (Autodesk, Revit 2019, 31 MB).

## 1. Container

OLE Compound File (`D0 CF 11 E0`). Streams principais:

| Stream | Bruto | Descomprimido | Papel |
|---|---|---|---|
| `Partitions/3` | 16,2 MB | 77,7 MB | **banco principal** (elementos, geometria) |
| `Partitions/4` | 13 KB | 101 KB | views, render, help-links |
| `Partitions/5` | 283 B | 44 B | ? |
| `Global/ElemTable` | 41 KB | 222 KB | índice de elementos (bit-packed) |
| `Global/Latest` | 35 KB | 91 KB | estado do documento (schedules, params) |
| `Formats/Latest` | 143 KB | 403 KB | esquema/formato |
| `Global/ContentDocuments` | 582 KB | 3,2 MB | ? |
| `BasicFileInfo` | 2 KB | — | versão do Revit (texto puro) |
| `ProjectInformation` | 926 B | — | ZIP com XML (versão, template) |
| `RevitPreview4.0` | 10 KB | — | PNG de preview |

## 2. Compressão (DECIFRADA)

Cada stream comprimido = cadeia de registros:

```
[10B header gzip: 1f 8b 08 00 + mtime 0][deflate raw][CRC32 4B][ISIZE 4B][32B rodapé]
```

Rodapé (32B): `[u16 0cab][u32 comp_size][u16 0cb0][u32 seq +4/registro][u32 ?]
[u32 comp_próximo][u32 ~131072][u32 101][u32 0]`

- **O deflate NÃO reinicia a janela** entre registros — descomprimir isolado dá
  `invalid distance too far back`
- Solução parcial: `zlib.decompressobj(-15, zdict=últimos_32KB_do_output_anterior)`
- **Verificação**: CRC32 + ISIZE de cada registro — 735/978 (75,2%) verificam
  perfeitamente; 215 descomprimem mas CRC diverge (janela desconhecida — ver
  ISSUES.md); 28 erro duro
- Pista dos 215: o rodapé declara tamanho 353 bytes MENOR que o fim real do
  deflate; há um blob de 343 bytes extra (header `0x8d` = bloco Huffman
  dinâmico, BFINAL=1) cujo papel é desconhecido

## 3. Banco de dados (Partitions/3 descomprimido)

### 3.1 Cabeçalho
`[u32 0x15113][u32 0x57][assinatura 1218 = c2 04 00 00]...`
A assinatura `1218` aparece 72.416 vezes — marcador de segmento.

### 3.2 Segmentos (parcialmente mapeado)
Cadeia de segmentos de alocação:

```
[u32 0][u32 prev_len][u32 seq_id][u32 len][1218][u16 0][dados len bytes]
```

- `seq_id` incrementa (+1 na maioria, com saltos) — 58.763 segmentos em cadeia
  válida nas regiões verificadas, IDs de 230 a 1.085.199, quase todos únicos
- `prev_len` do segmento N+1 == `len` do segmento N (lista ligada)
- As strings UTF-16 NÃO ficam dentro desses segmentos — ficam em regiões entre
  eles (ainda não mapeadas)

### 3.3 Strings
`[u32 nchars][UTF-16LE]` — ex.: `07 00 00 00` + "Level 1"

### 3.4 Global/ElemTable — ÁRVORE DE ELEMENTOS (DECODIFICADA ~100%)

Header de 18 bytes: `a7 04 09 1f | 00 00 01 00 | 00 00 01 00 | 00 00 00 00 | 00 00`

Depois, stream de unidades autorrepetidas:

```
[id][dup][flags][parent]        (4 × u32)
[parent_ou_outro][X][T]         (3 × u32, presente quando parent != -1)
```

- `parent == 0xFFFFFFFF` (-1) = raiz, e nesse caso NÃO há bloco de 3 valores
- Parser em `rvttool.py::parse_elemtable` extrai a árvore completa:
  **7.945 elementos únicos** no projeto de teste, IDs de 2 a 1.086.590
- Grupos maiores (prováveis categorias): 551 (2.440 filhos), 828 (1.973),
  803 (366), 822 (352), 687 (197), 786 (151)
- O elemento 311 (filho de 828) coincide com o valor u32 que aparece junto
  à string "Level 1" no banco — 828 é provavelmente a categoria Níveis
- Campo `flags`: 0 na maioria; valores diversos em ~5% dos registros
- Campo `T` do bloco: -1 na maioria; às vezes um ID (possível link de
  vizinhança/junta entre elementos)

## 4. Contagem de strings no banco (amostra)

148.210 strings UTF-16 únicas extraídas da partição 3: níveis (Level 1/2/3),
famílias (M_*), pranchas (00000.X), parâmetros, textos de anotação.
