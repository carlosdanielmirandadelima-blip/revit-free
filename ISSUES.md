# Problemas abertos

## 1. Registros com janela desconhecida (~22%)

~22% dos registros descomprimem sem erro, mas o CRC32 não confere: a janela
deflate desses registros referencia conteúdo que não é a cauda do registro
anterior. Hipóteses testadas e descartadas:

- janela = output anterior + bytes de rodapé/cabeçalho entre registros
- janela = output de 2 registros atrás
- janela = outputs de outros streams (Formats/Latest, Global/*, Partitions/4/5)
- dicionário presets comuns

Pista: nesses registros o rodapé declara um tamanho comprimido **353 bytes
menor** que o fim real do deflate — há um bloco extra de 343 bytes (+10 de
estrutura) entre o fim "oficial" e o trailer. Quem decifrar isso fecha o gap.

## 2. 28 registros com erro duro

Cascata provável do problema 1 (navegação cai em posição errada).

## 3. Seção principal do ElemTable é delta/bit-packed

O ElemTable tem header `a7 04 [count u16]...` onde count = nº de elementos
(7.945 no basic, 17.132 no advanced). A seção inicial é alinhada
(`[id][id][0][parent][Q][0][-1]`), mas ~95% da tabela usa codificação
própria ainda não decodificada (padrões de delta + bit-packing observados).
Enquanto isso, a lista completa de elementos vem dos registros `5d 02`.
