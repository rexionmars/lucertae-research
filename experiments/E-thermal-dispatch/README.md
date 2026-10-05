# E-despacho-termico

Quanto da geração térmica do SIN é decisão e não preço — e a programação
do dia seguinte se sustenta?

Construído do zero sobre `data/raw/termica_despacho/`. Não lê, não importa
e não reaproveita nenhum resultado, painel ou script anterior deste
repositório. A decomposição contábil foi descoberta por teste sobre o dado,
não copiada de manual.

```
.venv/bin/python experiments/E-despacho-termico/1_painel.py
.venv/bin/python experiments/E-despacho-termico/2_controles.py   # bloqueia o passo 3
.venv/bin/python experiments/E-despacho-termico/3_medida.py
```

Saídas em `data/interim/E-despacho-termico/` (sobrescritível por `LUCERTAE_INTERIM`).

---

## Insumo

`GERACAO_TERMICA_DESPACHO-2`, 29 arquivos mensais, abr/2024 a ago/2026.
Painel usina × hora: **2.601.600 linhas, 186 usinas, 21.192 horas**, grade
completa sem hora ausente.

O conjunto mudou de esquema três vezes na janela — 42, 43 e 47 colunas.
As colunas da decomposição sobrevivem às três; `din_publicacao`,
`nom_combustivel`, `val_geracaodespachada` e `val_progdisponibilidade` só
existem a partir de fev/2026 ou abr/2026, e isso é limite declarado, não
falha do painel.

## Decomposição contábil

Descoberta por teste. A identidade que fecha é:

```
geracao = ordemdemeritoacimadainflex + inflexibilidade + RESTO
```

e como `inflexibilidade = inflexembutmerito + inflexpura` fecha em 100% das
linhas programadas, ela se reescreve na forma econômica usada aqui:

```
geracao = MERITO + FORA
MERITO  = ordemdemeritoacimadainflex + inflexembutmerito
FORA    = inflexpura + razaoeletrica + garantiaenergetica + gfom
        + reposicaoperdas + exportacao + reservapotencia + gsub + unitcommitment
```

`MERITO` é o que a ordem de mérito despacharia de qualquer forma, incluindo
a parcela inflexível que por acaso cai dentro dela. `FORA` é geração que
existe por decisão, e não por preço.

A coluna publicada `ordemmerito` **não** entra na soma: ela é redundante com
`ordemdemeritoacimadainflex + inflexembutmerito` e a redundância falha em
0,41% das linhas programadas e 0,46% das verificadas. O controle C1b mede
isso em vez de esconder.

## Controles

Rodam antes de qualquer número. Bloqueante reprovado interrompe o passo 3.

| | Controle | Resultado |
|---|---|---|
| C1 | identidade fecha sobre a **energia** | prog 99,887%, verif 99,977% — passa |
| C1b | `ordemmerito` = soma das partes | diverge em 0,41% / 0,46% das linhas — atenção |
| C1c | resíduo concentrado, não difuso | 40 e 41 usinas; prog em Baixada Fluminense, verif em térmicas a gás do AM |
| C2 | grade horária completa | 21.192 de 21.192 horas — passa |
| C3 | chave (usina, hora) única | 0 duplicatas — passa |
| C4 | componente de motivo não negativo | 9 valores negativos em 22 colunas — atenção |
| C5 | `verificado` publicado **depois** do instante | 0 violações; atraso mediano 41,8 d — passa |
| C6 | cobertura de identificador | `ceg` 100%, `cod_usinaplanejamento` 99,80% — passa |

**C1 mudou de critério durante a construção, e a mudança está registrada
no código.** A primeira versão exigia 99,9% das *linhas* e **reprovou o
painel** (verif fechava em 99,126%). O diagnóstico mostrou que a reprovação
vinha de usina pequena do Amazonas com diferença de décimo de MW em muitas
horas — Tucunaré, Pirarucu, Jaraqui, Poraqué — e não de erro de
decomposição. O critério passou a ser a fração da **energia** explicada,
que é a grandeza de que o passo 3 depende; a fração de linhas continua
reportada, como informativa. Isto é troca de critério com diagnóstico
publicado, não limiar afrouxado até passar.

O resíduo **não é redistribuído** entre motivos: aparece como linha própria
na tabela do passo 3.

---

## Resultado A — descritiva

Abr/2024 a ago/2026, 156,34 TWh programados e 153,09 TWh verificados.

| | Programado | Verificado |
|---|---|---|
| Total | 156,34 TWh | 153,09 TWh |
| Ordem de mérito | 81,44 TWh — 52,09% | 80,48 TWh — 52,57% |
| **Fora do mérito** | **75,07 TWh — 48,02%** | **72,58 TWh — 47,41%** |
| Resíduo não explicado | −0,174 TWh — −0,111% | +0,034 TWh — +0,022% |

Fora do mérito, por motivo (programado, % do total térmico):

| Motivo | TWh | % do térmico | % do fora |
|---|---|---|---|
| inflexibilidade pura | 50,660 | 32,40% | 67,48% |
| unit commitment | 10,064 | 6,44% | 13,41% |
| exportação | 8,995 | 5,75% | 11,98% |
| GSUB | 2,653 | 1,70% | 3,53% |
| razão elétrica | 2,389 | 1,53% | 3,18% |
| garantia energética | 0,222 | 0,14% | 0,30% |
| GFOM | 0,090 | 0,06% | 0,12% |
| reposição de perdas | 0 | — | — |
| reserva de potência | 0 | — | — |

**Quase metade da geração térmica do SIN não é despachada por preço**, e
dois terços disso é inflexibilidade pura — parcela declarada pelo gerador,
não decidida pelo operador. Reposição de perdas e reserva de potência são
zero em toda a janela: as colunas existem e nunca foram usadas.

## Resultado B — decisão

Estimando: `d = fora_verificado − fora_programado`, agregado ao SIN por hora.
Perda declarada: MAE em MWh/h. 19.728 horas avaliáveis, jun/2024 a ago/2026.

**A restrição que define o desenho vem do C5.** O arquivo do mês M é
publicado no fim do mês M+1 — medido nos cinco arquivos que trazem carimbo:
atraso de 29,8 a 30,8 dias após o fim do mês. Logo, para uma hora do mês M,
o verificado mais recente **conhecível** é o do mês M−2. Nenhuma base usa
"os 7 dias anteriores", que seria vazamento de 30 a 60 dias.

Estimador central das bases: **mediana**, não média, porque a perda é MAE e
o constante que minimiza MAE é a mediana. Usar média mediria a escolha do
analista, não o atraso de publicação.

O viés existe: média −125,9 MWh/h, mediana −55,6 MWh/h, **−3,59% do fora do
mérito programado**. O verificado fica sistematicamente abaixo do programado.

| Base | MAE (MWh/h) | Habilidade | IC 95% |
|---|---|---|---|
| B0 — programa não enviesado | 257,1 | — | — |
| B1 — mediana por hora, mês M−2 | 268,8 | **−4,55%** | [−7,38%, −1,92%] |
| B2 — mediana do mês M−2 | 268,6 | **−4,44%** | [−7,28%, −1,91%] |
| ORÁCULO — mediana do próprio mês | 218,0 | **+15,23%** | [+13,07%, +17,49%] |

**O achado.** O viés é real e capturável: o oráculo ganha 15,2% com IC
inteiro acima de zero, o que é controle positivo — o experimento *consegue*
detectar viés quando ele está lá. Mas corrigir com o mês mais recente que o
ONS já publicou é **significativamente pior que não corrigir**, com IC
inteiro abaixo de zero nas duas bases.

A deriva explica: a mediana mensal do desvio anda de −351 a +102 MWh/h,
amplitude 453, com passo típico mês a mês de 43 MWh/h. O viés se move devagar
mas percorre faixa larga, e dois meses de defasagem bastam para o valor
publicado descrever outro regime.

**Leitura de decisão: o obstáculo não é ausência de sinal, é latência
institucional.** Quem está exposto ao encargo tem um viés de 3,6% para
corrigir e não consegue, porque o calendário de publicação do próprio
operador chega tarde demais. Isso não se resolve com modelo melhor; resolve-se
com publicação mais rápida — e é uma afirmação sobre o processo, não sobre a
técnica.

---

## Limites declarados

- **Sem preço.** `cvu-usitermica` não está em disco, então nada aqui é em
  R\$. Medido em 06/09/2026: 22 arquivos CSV, 9,8 MB, download testado.
- **A regra M+1 é medida em 5 arquivos de 29.** Os outros 24 não têm
  `din_publicacao`. E o arquivo de ago/2026 saiu 0,8 dia após o fim do mês,
  o que sugere versão preliminar sujeita a revisão — não verificado.
- **"Fora do mérito" mistura dois agentes.** Inflexibilidade pura é
  declaração do gerador; razão elétrica e GSUB são decisão do operador.
  A tabela sai por motivo justamente para permitir recompor com outro corte.
- **Exportação e GSUB entram em FORA.** Classificação discutível; a
  decomposição publicada permite tirá-las sem refazer o painel.
- **Grão de sistema.** Tudo em B é agregado ao SIN. Estrutura por
  subsistema, por usina, por combustível ou condicionada à carga não foi
  testada.
- **Sem hiperparâmetro e sem ajuste.** Não há modelo treinado aqui — só
  bases constantes e condicionais à hora. Um modelo com features poderia
  bater o oráculo; isso não foi tentado, e a conclusão sobre latência não
  depende disso, porque nenhuma feature muda a data em que o ONS publica.

## Não testado

Subsistema, usina, combustível; condicionamento à carga ou ao estado
hidrológico; horizonte diferente de "próxima hora publicada"; e se a versão
preliminar do mês corrente, publicada com um dia de atraso, resolveria a
latência — este último é o teste mais promissor e exige baixar o histórico
de versões, que o CKAN não guarda.
