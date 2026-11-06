# rvt-format

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

## Uso

```bash
# listar streams do arquivo
python3 src/rvttool.py lista arquivo.rvt

# descomprimir qualquer stream (o banco principal é Partitions/3)
python3 src/rvttool.py dump arquivo.rvt Partitions/3 banco.bin

# strings legíveis de um stream (UTF-16)
python3 src/rvttool.py strings arquivo.rvt Global/Latest
```

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
- [ ] Estrutura interna do banco (tabelas de elementos, geometria)
- [ ] Leitor completo .rvt → dados

## Aviso legal

Projeto de interoperabilidade: análise própria do formato, sem código da Autodesk.
Licença MIT.
