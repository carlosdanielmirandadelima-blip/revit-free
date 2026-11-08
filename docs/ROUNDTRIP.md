# Ida e volta: Revit / AutoCAD ↔ FreeCAD (o que sobrevive de verdade)

Resposta curta: **"sem perder nada" não existe** entre o Revit e qualquer outra
ferramenta. Não é limitação de software livre — é como o Revit funciona: ao
importar, ele **cria elementos novos**, e o que é específico do Revit (famílias,
parâmetros, vistas, pranchas, cotas, fases, worksets, sistemas MEP) não tem
representação no formato de troca.

O que existe é um ciclo com perda **medida e pequena**, e é isso que este
documento documenta com números do que foi testado aqui.

## O ciclo que funciona

```
Revit ──exporta IFC──> FreeCAD (NativeIFC: editar) ──save_ifc──> IFC ──> Revit
```

Do lado do FreeCAD, o round-trip é **lossless** — medido, não estimado.

### Medição 1 — IFC nosso (7 paredes, 2 lajes, 3 vãos, 2 pavimentos) → FreeCAD → IFC

Feito com o caminho nativo (`ifc_tools.save_ifc`):

| item | antes | depois |
|---|---|---|
| IfcWallStandardCase | 7 | 7 |
| IfcSlab | 2 | 2 |
| IfcOpeningElement | 3 | 3 |
| IfcRelVoidsElement | 3 | 3 |
| IfcPropertySet | 9 | 9 |
| IfcRelAssociatesMaterial | 7 | 7 |
| IfcBuildingStorey | 2 | 2 |
| **GUIDs comuns** | — | **50 de 50** |
| volume (12 elementos) | — | diferença máx **0,000000 m³** |
| psets por elemento | 6 chaves | 6 chaves |
| pavimentos | Térreo 0,0 / Piso 1 2,8 | idênticos |

Edição também propaga: renomeei `Parede Norte` → `Parede Editada` dentro do
FreeCAD e o arquivo voltou com o nome novo, **11 de 12 nomes idênticos** (só o
editado mudou), volumes intactos, 50/50 GUIDs.

Comando único:

```bash
python3 src/rt_freecad.py entrada.ifc saida.ifc
python3 src/rt_freecad.py entrada.ifc saida.ifc --renomear "Parede Norte=Nova"
python3 src/ifc_diff.py antes.ifc depois.ifc     # confere o que mudou/perdeu
```

### Medição 2 — o caminho ERRADO (importante)

Exportar um documento NativeIFC pelo exportador genérico do FreeCAD
(`importers.exportIFC`, o que a maioria dos tutoriais manda usar em script)
**destrói o arquivo**:

| item | antes | depois (errado) |
|---|---|---|
| IfcBuildingStorey | 2 | **0** |
| IfcPropertySet | 9 | **0** |
| IfcOpeningElement | 3 | **0** |
| IfcRelVoidsElement | 3 | **0** |
| GUIDs comuns | — | **0 de 50** |

Use `ifc_tools.save_ifc` (ou este repositório: `src/rt_freecad.py`), nunca o
exportador genérico, para preservar IFC.

## O que NÃO sobrevive em nenhum caminho

Perdas inerentes à ponte IFC (vale para Revit, ArchiCAD, qualquer um):

- **Famílias e tipos nativos do Revit** — viram `IfcWall`/`IfcDoor` genéricos;
  ao voltar, você reatribui tipos.
- **Ids de elemento do Revit** — o IFC tem GUID próprio; ao reimportar, o Revit
  cria ids novos. (O GUID do IFC sobrevive no arquivo, mas o Revit não o usa
  como ElementId.)
- **Parâmetros personalizados** — só sobrevivem se você configurar a exportação
  do Revit para incluí-los em property sets ("Export user defined property
  sets"), via arquivo de mapeamento. Sem isso, são descartados **na saída do
  Revit**, antes de chegar ao FreeCAD.
- **Vistas, pranchas, cotas, textos, tabelas, detalhes 2D** — não vão para IFC.
- **Fases, worksets, opções de projeto, grupos, vínculos** — não vão para IFC.
- **Sistemas MEP, armadura, famílias aninhadas complexas** — perda parcial ou
  total.
- **Restrições e dimensões paramétricas** — o IFC guarda geometria e atributos,
  não a lógica de projeto.

## Revit: *Abrir IFC* vs *Vincular IFC* (decide o seu fluxo)

- **Abrir IFC** → converte em elementos nativos editáveis no Revit. Bom para
  trazer o modelo de uma vez. **Não atualiza**: reimportar cria outra cópia.
- **Vincular IFC (Link IFC)** → mantém referência e permite **recarregar** o
  arquivo. É o único jeito de ter ciclo iterativo: edita no FreeCAD, salva IFC,
  e no Revit você recarrega o vínculo. Limitação: o conteúdo vinculado é
  referência (não editável como elemento nativo).

Regra prática: **um dono por disciplina**. Se o modelo nasce no Revit, ele é o
mestre e o FreeCAD entra só para geometria específica (vinculada). Se nasce no
FreeCAD, use o Revit para documentação/coordenação a partir do IFC.

## AutoCAD / DWG

- **DXF** entra e sai do FreeCAD nativamente (é o nosso `rvttool dxf`).
- **DWG** no FreeCAD exige o conversor ODA (não incluído no snap). Sem ele, use
  DXF como intermediário.
- Pelo DXF/DWG você carrega **geometria (linhas, polilinhas, blocos)**, não BIM:
  paredes do AutoCAD Architecture (AEC Objects) viram linhas soltas ou somem.
  Volta e volta preserva geometria, não inteligência de objeto.

## Recomendação de configuração (para perder o mínimo)

1. No Revit, exporte com **IFC2x3 Coordination View 2.0** ou **IFC4 Reference
   View**; mantenha **Base Quantities** ligado.
2. Ative **"Export user defined property sets"** com um arquivo de mapeamento
   dos seus parâmetros — é o único jeito de levá-los ao FreeCAD e trazer de
   volta.
3. No FreeCAD, edite via **NativeIFC** e salve com `ifc_tools.save_ifc`
   (`src/rt_freecad.py` faz isso).
4. Depois de cada volta, rode `src/ifc_diff.py antes.ifc depois.ifc`: ele mostra
   contagem por classe, GUIDs coincidentes, diferença de volume e psets
   perdidos. Se aparecer "PERDA", o ciclo estragou algo — não siga em frente.

## O que foi verificado aqui (e o que não foi)

Verificado: round-trip FreeCAD lossless (tabela acima), propagação de edição,
exportação IFC4/IFC2X3 com 0 erros de schema e volumes exatos
(`tests/test_criar_ifc.py`), e o desastre do exportador genérico.

Não verificado: **nada disso foi aberto no Revit** (não há Revit nesta máquina).
A parte "Revit → IFC" e "IFC → Revit" segue o comportamento documentado da
Autodesk, não uma medição local.
