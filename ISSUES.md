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

## 3. Seção principal do ElemTable é delta/bit-packed

O ElemTable tem header `a7 04 [count u16]...` onde count = nº de elementos
(7.945 no basic, 17.132 no advanced). A seção inicial é alinhada
(`[id][id][0][parent][Q][0][-1]`), mas ~95% da tabela usa codificação
própria ainda não decodificada (padrões de delta + bit-packing observados).
Enquanto isso, a lista completa de elementos vem dos registros `5d 02`.
