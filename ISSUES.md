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
