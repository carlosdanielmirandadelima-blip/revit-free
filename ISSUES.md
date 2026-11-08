# Problemas abertos

## 1. ~~Registros com janela desconhecida (~22%)~~ — RESOLVIDO NA PRÁTICA

**Conclusão: os 216 registros "divergentes" NÃO estão corrompidos.** Evidências:

1. O deflate deles termina limpo (eof próprio, stream auto-consistente).
2. O output contém dados de banco perfeitamente coerentes — strings reais do
   projeto: perfis de aço `W610x91`/`W610x84`, vistas `A101`/`Elevation 2`/
   `North`, materiais `Chrome-Polished_Chrome-CP` com URLs da Kohler, etc.
3. A cadeia de segmentos do DB caminha limpa ATRAVESSANDO a fronteira para
   dentro desses registros (1.667 segmentos consecutivos validados).
4. O ISIZE declarado se agrupa em torno de 131.072 (2^17) — os rodapés descrevem
   o tamanho do registro em um SAVE ANTERIOR (cota de 128 KB), antes do dado
   crescer. São metadados obsoletos de save incremental do Revit, não checksum
   do dado atual.
5. O "blob de 343 bytes" era artefato das fronteiras erradas do parser antigo:
   o separador real de registros é o header gzip `1f 8b 08 00`, não o tamanho
   declarado no rodapé.

**Consequência prática: ~100% do banco decodifica para dados utilizáveis.**
A verificação por rodapé fica em 75,1% — propriedade do METADADO do arquivo,
nao do decodificador. O resto é coberto por validação estrutural (cadeia de
segmentos + coerência de strings).

Nota: o DB tem blocos heterogêneos (cadeia de segmentos
`[pl][X][len][c2 04 00 00]...` intercalada com dados de doubles), então
caminhadas lineares "tudo-é-segmento" quebram em pontos legítimos.

Hipóteses antigas testadas e descartadas:

- janela = output anterior + bytes de rodapé/cabeçalho entre registros
- janela = output de 2 registros atrás
- janela = outputs de outros streams (Formats/Latest, Global/*, Partitions/4/5)
- dicionário presets comuns

Pista: nesses registros o rodapé declara um tamanho comprimido **353 bytes
menor** que o fim real do deflate — há um bloco extra de 343 bytes (+10 de
estrutura) entre o fim "oficial" e o trailer. Quem decifrar isso fecha o gap.

## 2. 28 registros com erro duro

Com as fronteiras corretas (scan `1f 8b 08 00`) restam 27 spans sem decode —
cascata provável de headers não detectados; impacto pequeno.

## 2b. Importador FreeCAD — MVP ENTREGUE, BIM completo pendente

Entregue (testado no FreeCAD 1.1.4): `rvttool macro` (FCMacro autocontida:
planta por nivel + planilha de elementos) e `rvttool dxf` (DXF por nivel).
Entregue tambem `rvttool ifc` (IFC4: `IfcBuildingStorey` por nivel com a
geometria de referencia em `IfcGeometricCurveSet`), validado reabrindo com
ifcopenshell 0.9.0. Regressao coberta por `tests/test_smoke.py`.

Pendencia para BIM completo: link elemento->geometria. Os conteineres type-1
tem indice crescente (195, 196, 197...) e extensao conhecida (36 + count6*8),
mas o elemento dono de cada bloco ainda nao foi localizado — deve passar pelo
sistema de referencias do DB (issue 3 / tabelas de indice).

Sem esse link, o IFC sai com a geometria como **referencia** dentro do
pavimento (nao como `IfcWall`/`IfcSlab`): a planta e fiel, mas nao ha
material/espessura/categoria por curva — ou seja, o arquivo abre e mede, mas
nao e um modelo BIM navegavel por elemento.

## 3. Seção principal do ElemTable é delta/bit-packed

O ElemTable tem header `a7 04 [count u16]...` onde count = nº de elementos
(7.945 no basic, 17.132 no advanced). A seção inicial é alinhada
(`[id][id][0][parent][Q][0][-1]`), mas ~95% da tabela usa codificação
própria ainda não decodificada (padrões de delta + bit-packing observados).
Enquanto isso, a lista completa de elementos vem dos registros `5d 02`.

### Evidências coletadas sobre o link elemento→geometria (2026-11, não resolvido)

Testes feitos e descartados — registrados para poupar retrabalho:

1. **Marcador mais próximo antes da curva**: a atribuição linear pelo último
   `5d 02 01 00 00 00 [u32]` antes de cada curva type-4 dá 46 elementos com
   geometria no projeto básico e **0 ids coincidem** com o ElemTable. O campo
   `u32` do marcador **não é id de elemento** — em trechos contíguos ele
   incrementa (…230, 231, 232, 233) e em outros contém offsets (ex.: 86291
   aponta para um trecho com arrays de ponteiros `3a a5 08 00 3b a5 08 00 …`).
   É um contador/índice de contexto, não identidade.
2. **Registros de 32 bytes confundidos com geometria**: `ff ff ff ff | 04 82
   08 00 | 01 00 00 00 | [idx] | 05 06 01 00 00 00 | ff ff ff ff | 01 07 |
   ff ff ff ff` aparecem em série com `idx` crescente. Não são curvas — o
   validador matemático (`hypot == comprimento`) já os rejeita corretamente.
3. **Offset marcador→primeira curva**: mediana de 57 KB (máx. 532 KB), ou
   seja, a geometria está em bloco longe do marcador — não há justaposição
   que permita atribuição por proximidade.
4. **Curvas de comprimento zero**: ~6 registros por arquivo eram degenerados
   (L = 0) e geravam níveis espúrios (z = 0,163/0,166/0,170 m). Passaram a
   ser filtrados em `extrai_curvas_t4`; isso limpou o DXF/IFC sem perder
   geometria real.

5. **Ponteiros são relativos ao chunk**: nenhuma referência absoluta ao
   offset de uma curva (procurei o u32 do offset em todo o DB, inclusive
   offset±3: zero ocorrências). Cada registro gzip decodifica um grafo de
   objetos independente, com índices locais — então atribuição exige parsear
   o grafo dentro de cada chunk, não uma tabela global.
6. **Chunks de geometria não têm nomes**: o chunk que contém as curvas
   (avançado, `#220`, 82 KB, geometria em +20.996) tem 66 strings UTF-16 e
   **nenhuma** é nome de elemento — são bytes binários que casam com o padrão
   de texto por acidente. Geometria e nomes vivem em chunks diferentes.
7. **Família de registros de 48 bytes**: `ff ff ff ff | 04 82 08 00 | [A] |
   72 04 00 00 | ... | 04 00 00 00 | ff ff ff ff | [B=A+1] | d8 01 | [C]`,
   com `A` incrementando 1 por registro e `C` subindo de 4 em 4 (1, 52, 55,
   59, 63...). 17.024 ocorrências no projeto avançado. Parece a indexação
   interna que liga curva → objeto, mas o mapeamento objeto → elemento
   continua desconhecido.

**Entregue no lugar disso** (não depende do link): `rvttool poligonos`
reconstroi contornos fechados das curvas e exporta DXF `LWPOLYLINE` + JSON com
perímetro e área por nível. No projeto avançado: 131 contornos (nível 0:
mediana 62 m²; níveis 4,37 e 8,17 m: 4 contornos de 240 m² cada).
É geometria medida e conferida, mas sem semântica de elemento (não é parede
com categoria/material).

O caminho para fechar o item continua sendo decodificar o sistema de
referências do DB (arrays de offsets + contêineres type-1) ou a seção
bit-packed do ElemTable.
