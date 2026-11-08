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

8. **Layout do registro de 109 bytes revisado**: `8 (assinatura) + 28 (7 u32)
   + 72 (9 doubles) + 1 byte`. Os sete u32 não são `[tipo][a][b][c][d][ref][0]`
   como documentado para o projeto básico — no avançado aparecem valores como
   `(4, 6, 20, 53, 54, 58, 0)` e `(5, 6, 56, 22, 21, 53, 0)`, com números na
   faixa 0–800 que variam por objeto. Ou seja: são **índices de vértice/nó**
   numa tabela do chunk, não estilo de linha. A leitura anterior (ref = estilo)
   vale para o subconjunto do projeto básico, não como regra geral.
9. **Família de 48 bytes é adjacência, não atribuição**: `A` reinicia por chunk
   (ex.: chunk #214: 49–64; #222: 341–483), `B = A+1` e `C` sobe de 4 em 4 —
   assinatura típica de índice vértice→segmento sobre um array de u32. Não há
   nenhuma correspondência entre `A` e os índices locais de elemento (em
   #213 os elementos têm índice ~251 e os `A` do chunk são 49–64).
10. **Registro de elemento**: `[tipo_idx u32][idx_local u32] … [01 00 00 00]
   [ptr u32][len u32][nome UTF-16]`. Exemplo real no chunk #213: tipo 180,
   índice 250, `len` 16, nome `Filled Box 2.5mm`. O nome é recuperável (já é,
   via marcadores `5d 02`), mas o campo `tipo_idx` é a primeira pista de
   categoria numérica que não depende do ElemTable.

11. **Tabela de vértices existe, mas o layout varia**: registros
   `ff ff ff ff | 04 80 08 01 | …` com 3–4 doubles de coordenada (ex.:
   `-0.666, 65.25, 89.26`) aparecem 102 vezes no chunk de geometria do avançado.
   A posição dos doubles muda de registro para registro (só 26/102 casam em
   `p+4`, 102/102 em `p+8` *e* em `p+16`), então não há stride fixo: sem o
   schema do serializador não dá para montar índice → vértice.
12. **Ids de elemento nunca aparecem na geometria**: extraí 668 ids reais de
   elemento (faixa 235–313.698, 86k+ na maioria) e procurei cada um no chunk de
   geometria: **1 coincidência** (id pequeno repetido 290×, acidental). Não há
   campo de id de elemento nos registros de geometria.

13. **Sem bbox nos registros de elemento (atribuição espacial inviável)**: os
   registros de tipo de parede carregam parâmetros (ex.: espessura
   `0.2952755905511811` m em "Exterior - Brick on Mtl. Stud"), mas nenhuma
   caixa envolvente. Procurando as coordenadas de uma linha no DB inteiro,
   elas aparecem em 5 chunks — **todos chunks de geometria** (#41, #54, #134,
   #220, #242), nenhum com strings/nomes (chunk #242: 127 KB, 0 strings).
   Como não existe bbox em registro de elemento nem nome em chunk de geometria,
   a hipótese "curva ⊂ bbox do elemento" não tem de onde sair.
14. **Pareamento de linhas paralelas não dá espessura**: testei inferir paredes
   pareando segmentos paralelos (tolerância 1°, sobreposição ≥ 80%, match
   1-para-1) no nível 0 do avançado: 1.119 segmentos → 343 pares, mas o
   histograma de distâncias é plano (0,03–0,23 m espalhados: 40×0,04;
   36×0,05; 32×0,03; 28×0,10; 10×0,20) — sem picos em espessuras de projeto
   (0,09/0,14/0,20/0,30). Motivo: as curvas extraídas são linhas de locação
   (eixo) e linhas de grade, não os dois paramentos da parede. Não serve.

**Entregue no lugar disso** (não depende do link): `rvttool poligonos`
reconstroi contornos fechados das curvas e exporta DXF `LWPOLYLINE` + JSON com
perímetro e área por nível, e o `ifc` inclui esses contornos no pavimento como
representação `Contorno`. No projeto avançado: 76 contornos (nível 0: 68,
mediana 76 m²; níveis 4,37 e 8,17 m: 4 contornos de 241 m² cada).
É geometria medida e conferida, mas sem semântica de elemento (não é parede
com categoria/material). Também saiu `rvttool catalogo`: registros de símbolo de
anotação com `nome`, `classe` (estável por nome, igual nos dois arquivos, mas
compartilhada por nomes parecidos — classe de símbolo, não categoria) e `id`
real. Não resolve o link, mas pela primeira vez temos ids de elemento
associados a nomes de forma verificável.

O caminho para fechar o item continua sendo decodificar o sistema de
referências do DB (arrays de offsets + contêineres type-1) ou a seção
bit-packed do ElemTable.
