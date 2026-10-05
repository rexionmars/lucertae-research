# E-preco-cmo

O custo marginal de operação do dia seguinte é previsível a partir do estado do
sistema, ou a repetição do dia anterior já é o melhor que se consegue?

**A um dia, empate; a dois, o modelo ganha.** Contra a ingênua sazonal da
literatura de preço, o melhor modelo dá +0,76% de habilidade em MAE com IC 95%
[−6,72%; +7,70%] — indistinguível — e +16,2% em RMSE. Deslocado o alvo para
D+1, com o portão de informação deslocado junto, a habilidade vai a +16,31%,
IC 95% [+10,64%; +21,87%]. O que a ingênua tem é o caminho realizado mais
recente, e ele acerta o piso do CMO exatamente; esse trunfo vale a um dia e
não vale a dois.

Família 11 da `report/tarefas-dados.tex` — preço e custo marginal — que até
06/09/2026 tinha o dado em disco e nenhum experimento. Construído sobre
`data/raw/cmo/`, que estava listado em `TAREFAS.txt` como bruto órfão: baixado
e nunca lido por código.

```
.venv/bin/python experiments/E-preco-cmo/1_painel.py
.venv/bin/python experiments/E-preco-cmo/2_controles.py   # bloqueia o passo 3
.venv/bin/python experiments/E-preco-cmo/3_modelos.py
.venv/bin/python experiments/E-preco-cmo/4_decomposicao.py
.venv/bin/python experiments/E-preco-cmo/5_ablacao.py
```

Saídas em `data/interim/E-preco-cmo/` (sobrescritível por `LUCERTAE_INTERIM`).

| script | o que faz | saída |
|---|---|---|
| `1_painel.py` | painel subsistema × meia-hora com 40 features numéricas dentro do portão | `painel.parquet`, `janelas.json` |
| `2_controles.py` | seis controles, todos bloqueantes | `controles.json` |
| `3_modelos.py` | quatro linhas de base, três modelos, um oráculo; origem móvel com recalibração mensal | `previsoes.parquet`, `resultado.json` |
| `4_decomposicao.py` | quantil do erro, comportamento no piso, nível contra forma | `decomposicao.json` |
| `5_ablacao.py` | ablação por família de feature, nulo por permutação, controle de horizonte | `ablacao.json` |

---

## Insumo

`CMO semi-horário` do ONS, três arquivos anuais, **184.704 registros**,
4 subsistemas × 46.176 meias-horas, 01/01/2024 a 27/08/2026, zero nulos.
Covariáveis: curva de carga horária, intercâmbio nacional horário, EAR e ENA
diárias por subsistema.

O alvo tem duas propriedades que decidem o desenho inteiro:

- **Inflado no piso.** 20,5% das meias-horas ficam em CMO ≤ 1 R$/MWh — custo
  marginal nulo, oferta sobrando. O mínimo observado é −39,24.
- **Cauda pesada.** O máximo é 4.870,95 R$/MWh, e o p99 fica entre 614 e 1.082
  conforme o subsistema.

Faltam **8 dias inteiros** de CMO na janela. Entram na grade como ausentes,
são descartados com contagem e nunca interpolados: interpolar criaria alvo que
o operador não publicou.

**Cada buraco custa três dias de painel**, e isso só apareceu porque o C1
reprovou com o número errado: além do próprio dia, cai o dia seguinte, que
perde o D-1 da ingênua, e o dia sete depois, que perde o D-7. São 8 buracos e
**24 dias fora do painel**, mais os 7 primeiros dias da série, que não têm D-7.
Total descartado: 1.536 linhas sem alvo e 4.416 sem termo de comparação, de
186.240 na grade cheia.

## Portão de informação, medido e não suposto

A previsão sai às 12:00 do dia D-1 e vale para as 48 meias-horas do dia D. O
que está disponível nesse instante foi medido fonte a fonte, pela diferença
entre o último registro do arquivo e a data de modificação dele:

| fonte | baixado em | último registro | atraso |
|---|---|---|---|
| CMO semi-horário | 2026-08-27 10:08 | 2026-08-27 23:30 | **−0,6 dia** |
| curva de carga | 2026-09-02 04:25 | 2026-08-31 23:00 | 1,2 dia |
| intercâmbio | 2026-09-02 04:44 | 2026-08-31 23:00 | 1,2 dia |
| EAR diária | 2026-09-02 04:25 | 2026-08-31 | 2,2 dias |
| ENA diária | 2026-09-06 11:22 | 2026-09-04 | 2,3 dias |

**O CMO é publicado com antecedência.** O arquivo baixado às 10:08 de 27/08 já
trazia as 48 meias-horas daquele mesmo dia. Ele é saída do modelo de despacho,
não medição ex-post. Isso não esvazia a tarefa — às 12:00 de D-1 o número do
operador para o dia D ainda não saiu — mas define o portão:

    CMO ................ até o fim do dia D-1
    carga, intercâmbio . até o fim do dia D-2
    EAR, ENA ........... até o dia D-3
    calendário de D .... determinístico, liberado

O portão vale **igualmente para o modelo e para as linhas de base**. Dar D-1 à
ingênua e D-2 ao modelo viciaria a comparação contra o modelo.

Cada atraso é **uma observação por fonte**, e isso é limite declarado: os
arquivos do ONS não trazem carimbo de publicação, e a data de modificação é a
única evidência em disco.

## Desenho

**Estimando.** CMO em R$/MWh de cada meia-hora do dia D, nos quatro
subsistemas.

**Adversário.** A ingênua sazonal canônica da literatura de previsão de preço:
terça a sexta repetem D-1; sábado, domingo e segunda repetem D-7. Não a
ingênua simples — em série de preço a repetição do dia anterior já carrega
nível e forma diurna, e é ela que um modelo precisa bater.

**Perda.** MAE, declarada antes de olhar resultado, pelas duas razões que a
área registra: é a métrica em que estudos de preço se comparam, e a cauda do
CMO faria o RMSE virar relatório de meia dúzia de horas. RMSE sai como
secundário.

**Recalibração mensal, janela expansiva.** 15 reajustes ao longo do teste. Sem
recalibrar, um ajuste teria de valer 14 meses enquanto a ingênua se atualiza
todo dia — a ingênua ganharia por desenho.

**Três modelos sobre o mesmo insumo.** `direto` prevê o nível do preço;
`residual` prevê a correção da ingênua; `duas_partes` classifica se a meia-hora
cai no piso e regride o resto, com regra de decisão que é a que minimiza MAE
sob esse modelo.

**IC por reamostragem de dia**, 2.000 repetições, os quatro subsistemas juntos
no bloco: meias-horas do mesmo dia têm erro correlacionado, e reamostrar linha
daria intervalo estreito demais.

## Controles

Rodam antes de qualquer número, e reprovação bloqueia o passo 3.

| | Controle | Resultado |
|---|---|---|
| C1 | grade, chave única e os dias ausentes continuam ausentes | 0 duplicatas, 0 dias incompletos, 24 ausentes — passa |
| C2 | CMO dentro da faixa física, alvo sem nulo | 0 fora de faixa, mín −39,24, máx 4.870,95 — passa |
| C3 | **portão de informação**: refazer as features com as fontes mascaradas na emissão | 40 dias sorteados, 307.200 células, 0 divergências — passa |
| C4 | cobertura de feature ≥ 97% | pior 99,15% (`cmo_l2`) — passa |
| C5 | ordem das ingênuas: D-1 bate climatologia, sazonal bate D-7 | 43,93 < 136,40 e 42,47 ≤ 61,75 — passa |
| C6 | os quatro subsistemas são séries distintas | correlação máxima 0,933 — passa |

**O C1 já reprovou uma vez**, com o limiar em 8 — o número de buracos na
fonte. O painel perde 24 dias, e a diferença é a aritmética acima. O limiar
está fixo em 24 e não é calculado: se a fonte for rebaixada e o número mudar,
o controle reprova e obriga a olhar em vez de absorver a mudança em silêncio.

**O C3 é o que testa o desenho e não o dado.** Ele apaga das fontes tudo o que
está depois do instante de emissão, reconstrói as features do dia sorteado com
a mesma função do passo 1 e exige valor idêntico célula a célula. Uma única
feature que olhasse para o futuro faria o controle falhar.

### Controle positivo, e o que ele custou

O oráculo de nível recebe a mediana verdadeira do resíduo do dia e desloca a
ingênua por ela. A primeira versão deslocava pela **média** e entregou **+0,9%**
de habilidade, com IC cruzando zero — o desenho pareceria incapaz de detectar
ganho, e nenhum resultado negativo do modelo significaria nada.

O defeito era de estatística, não de dado: a perda declarada é MAE, e a
constante que minimiza MAE é a mediana. Trocada a média pela mediana, sobre o
mesmo dia e o mesmo dado, o oráculo passa a **+17,66%**, IC [+15,28; +20,21].
É a mesma regra que o `E-despacho-termico` já tinha registrado, aplicada aqui a
um oráculo em vez de a uma linha de base.

---

## Resultado A — nenhum modelo se distingue da ingênua em MAE

Teste de 01/06/2025 a 27/08/2026: **85.248 linhas, 444 dias, 15
recalibrações, 41 features**.

| preditor | MAE | RMSE | habilidade MAE | IC 95% |
|---|---|---|---|---|
| ingênua D-1 | 52,70 | 129,33 | −7,36% | [−14,08; −1,16] |
| ingênua D-7 | 69,82 | 140,19 | −42,24% | [−53,71; −32,04] |
| **ingênua sazonal** | **49,09** | **122,02** | adversário | |
| climatologia por meia-hora | 125,18 | 162,89 | −155,02% | [−176,41; −136,05] |
| LightGBM direto | 51,32 | 103,38 | −4,54% | [−12,39; +2,74] |
| LightGBM residual | 50,04 | 115,42 | −1,94% | [−6,50; +2,26] |
| **LightGBM duas partes** | **48,71** | **102,31** | **+0,76%** | [−6,72; +7,70] |
| oráculo de nível | 40,42 | 112,69 | +17,66% | [+15,28; +20,21] |

**Em MAE, os três modelos têm IC cruzando zero: nenhum se distingue da
repetição do dia anterior.** O melhor deles empata, com +0,76% e intervalo de
14 pontos de largura.

**Em RMSE, os mesmos modelos batem a ingênua com folga**: +16,2% o de duas
partes, +15,3% o direto. A divergência entre as duas métricas não é ruído — o
passo 4 mostra de onde ela vem.

O controle positivo passa: o oráculo tem IC inteiro acima de zero. O
experimento detecta ganho quando ele existe, e o empate acima é medida, não
incapacidade do desenho.

## Resultado B — a ingênua ganha no piso e perde na cauda

O CMO fica no piso em 14,0% das meias-horas do período de teste.

| preditor | prevê no piso quando o alvo está lá | erro mediano ali | erro mediano fora |
|---|---|---|---|
| ingênua sazonal | **71,6%** | 0,00 | 15,10 |
| LightGBM direto | 19,2% | 16,65 | 22,86 |
| LightGBM residual | 18,6% | 13,06 | 19,48 |
| LightGBM duas partes | **66,0%** | 0,01 | 22,03 |

**A ingênua é um caminho realizado, e por isso acerta o piso exatamente.** Um
regressor único devolve a mediana condicional, que quase nunca cai em zero, e
paga 13 a 17 R$/MWh de erro mediano em 14% das linhas. Modelar o piso
explicitamente recupera o comportamento — e é o que move a habilidade de
−4,54% para +0,76%.

Quantis do erro absoluto, no mesmo teste:

| preditor | q25 | q50 | q90 | q95 |
|---|---|---|---|---|
| ingênua sazonal | **2,25** | **12,10** | 157,62 | 222,46 |
| LightGBM direto | 7,73 | 22,06 | 136,53 | 179,90 |
| LightGBM duas partes | 5,13 | 19,78 | **131,75** | **184,86** |

**A troca é sempre a mesma:** a ingênua erra menos nas linhas fáceis e mais nas
difíceis. O modelo de duas partes erra menos que ela em apenas **40,7%** das
linhas e ainda assim tem RMSE 16,2% menor. MAE pesa toda linha igual e escolhe
a ingênua; RMSE pesa a cauda e escolhe o modelo. **A escolha da perda decide o
vencedor, e escolhê-la depois de ver o resultado seria escolher o resultado.**

### Nível e forma

Separando o CMO em nível do dia e desvio de cada meia-hora em torno dele:

| preditor | completo | nível | forma |
|---|---|---|---|
| ingênua sazonal | 49,09 | 40,21 | 48,64 |
| LightGBM direto | 51,32 | 37,80 | 42,45 |
| LightGBM duas partes | **48,71** | **35,52** | **42,65** |
| oráculo de nível | 40,42 | 23,57 | 48,64 |

**Os modelos batem a ingênua nas duas partes medidas em separado e empatam no
total.** Não há inconsistência: o erro de uma linha é a soma do erro de nível
com o de forma, e |a+b| não é |a|+|b|. MAE não é aditiva sobre essa separação.

## Resultado C — a ingênua só é imbatível a um dia

O mesmo desenho, com o alvo deslocado para D+1 e o portão inteiro deslocado
junto, roda como controle: o erro tem de crescer nos dois termos.

| horizonte | MAE do modelo | MAE da ingênua | habilidade | IC 95% |
|---|---|---|---|---|
| D | 48,71 | 49,09 | +0,76% | [−6,72; +7,70] |
| D+1 | 62,68 | 74,89 | **+16,31%** | **[+10,64; +21,87]** |

O controle passa — os dois erros crescem — e o resultado que ele traz junto é
maior que o controle. **A ingênua se degrada muito mais rápido que o modelo:**
perde 25,80 R$/MWh de um dia para o outro, contra 13,96 do modelo. A dois dias
o modelo ganha com IC inteiro acima de zero.

A leitura é a mesma do Resultado B por outro caminho. O que a ingênua tem de
melhor é o caminho realizado mais recente, e o valor dele cai depressa com a
distância. As covariáveis de estado do sistema não caem tão depressa, porque
descrevem condição hidrológica e de carga que muda em escala de semana.

## Resultado C2 — a ablação não identifica de onde vem a habilidade

Conjuntos encaixados, mesma origem móvel e mesma recalibração:

| conjunto | features | habilidade |
|---|---|---|
| A0 calendário + CMO próprio | 20 | −4,87% |
| A1 + CMO dos outros subsistemas | 28 | −1,01% |
| A2 + carga e intercâmbio | 36 | −9,50% |
| A3 + hidrologia (completo) | 41 | +0,76% |

**Os degraus não são interpretáveis, e a razão foi medida.** Com
`colsample_bytree` menor que 1 o LightGBM sorteia coluna por posição: permutar
as mesmas colunas é trocar de semente. A primeira corrida da ablação
concatenava as famílias na ordem em que as somava, e deu outro resultado para
o mesmo conjunto de features:

| conjunto | ordem da ablação | ordem canônica | diferença |
|---|---|---|---|
| A0 | −3,66% | −4,87% | 1,21 pt |
| A1 | −1,84% | −1,01% | 0,83 pt |
| A2 | −2,69% | −9,50% | **6,81 pt** |
| A3 | +4,40% | **+0,76%** | 3,64 pt |

A ordem canônica reproduz o passo 3 exatamente no A3 — +0,76% contra +0,76% —,
o que fecha a explicação: é ordem de coluna, e não outra diferença de código.

**As diferenças entre degraus vizinhos (3,86, −8,49 e 10,26 pontos) são da
mesma ordem que a variação induzida só por permutar coluna (0,83 a 6,81).** Com
uma semente e uma configuração, a ablação mede variância de ajuste junto com
efeito de família, e não separa as duas. Isso não invalida o Resultado A: a
faixa toda cabe dentro do IC de 14 pontos que o passo 3 já publica. Mas
significa que **nenhuma afirmação sobre qual fonte carrega a habilidade se
sustenta com este número de sementes**, e o passo 5 não faz nenhuma.

### Nulo por permutação

Embaralhar as features entre as linhas do treino, com o alvo intacto, leva a
habilidade a **−206,91%** — pior que a climatologia. A associação entre feature
e alvo é o que sustenta a previsão; sem ela o modelo vira preditor constante.

## Resultado D — a habilidade não é estável no tempo nem no espaço

Habilidade do modelo de duas partes sobre a ingênua sazonal, por subsistema:

| subsistema | MAE da ingênua | MAE do modelo | habilidade |
|---|---|---|---|
| N | 50,91 | 52,27 | −2,68% |
| NE | 51,90 | 51,44 | +0,89% |
| S | 47,53 | 45,82 | **+3,61%** |
| SE | 46,02 | 45,33 | +1,49% |

Por mês de teste, a habilidade vai de **−68,2%** (dez/2025) a **+38,7%**
(jan/2026), e fica acima de zero em **10 dos 15 meses**. Dois meses ruins
carregam o agregado: sem dez/2025 e mar/2026 o resultado mudaria de sinal.
É essa dispersão, e não o valor central, que produz o IC de 14 pontos de
largura do Resultado A.

A leitura conservadora é a do Resultado A: com 15 meses de teste, **a
habilidade média não se distingue de zero em MAE**. A instabilidade mensal é
grande demais para que a maioria de meses positivos sustente afirmação mais
forte.

## Limites declarados

- **O atraso de publicação é um ponto por fonte.** Os arquivos do ONS não
  trazem carimbo de publicação; a data de modificação do arquivo em disco é a
  única evidência disponível. O portão inteiro repousa sobre cinco observações.
- **O CMO é saída de modelo, não medição.** É o valor que o modelo de despacho
  do operador produz. Não existe segunda fonte para conferir contra, e nenhum
  controle aqui testa se o número publicado é o custo marginal realizado.
- **Sem feriado.** Não há tabela de feriado nacional ou regional no
  repositório. O efeito de feriado cai dentro do erro tanto do modelo quanto da
  ingênua, e a ingênua sazonal é justamente a base que mais sofre com isso.
- **Sem preço final.** O CMO não é o PLD. A CCEE, que publica o PLD, devolve
  HTTP 403 por três vias distintas — medido em 06/09/2026 e registrado em
  `report/tarefas-dados.tex`. Nada aqui é afirmação sobre preço de liquidação.
- **Uma configuração de hiperparâmetro e uma semente.** O IC cobre variação
  entre dias do teste; não cobre variância de ajuste, de semente, nem da data
  de corte entre treino e teste. O Resultado C2 dá uma medida parcial dessa
  variância — permutar a ordem das colunas move a habilidade de 0,83 a 6,81
  pontos — e ela é grande o bastante para engolir qualquer diferença entre
  conjuntos de feature.
- **Grão de subsistema.** O ONS não publica CMO nodal. O comparador direto da
  literatura (`maji2025`, ERCOT nó a nó) não é reproduzível com este dado, e
  isso é objeto de comparação inexistente, não validação pendente.

## Não testado

- Recalibração diária ou semanal em vez de mensal. A literatura de previsão de
  preço pede diária; 15 reajustes custaram 864 s, e 444 custariam ~7 h.
- Janela de treino deslizante em vez de expansiva. Os dois meses em que o
  modelo desaba (dez/2025 e mar/2026) sugerem mudança de regime, que janela
  curta trataria melhor — não medido.
- Modelo por subsistema em vez de um global com o subsistema como categoria.
- Mais de uma semente. É o teste que a ablação exige para virar leitura: com
  uma só, o Resultado C2 mede ruído de ajuste junto com efeito de família.
- Horizonte além de D+1. A habilidade cresce de +0,76% para +16,31% de um dia
  para dois, e não se sabe onde ela para.
- Previsão de densidade ou de quantil. O piso e a cauda pedem isso, e o
  Resultado B é o argumento: nenhum ponto único serve às duas regiões.
- `cvu-usitermica`, que define a ordem de mérito e é o insumo mais próximo do
  mecanismo que forma o CMO. Medido em 06/09/2026: 22 arquivos, 9,8 MB, HTTP
  200. Fora do painel por não estar em disco, não por indisponibilidade.
