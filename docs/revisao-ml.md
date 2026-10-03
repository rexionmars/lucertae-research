# Revisão da cadeia de ML — achados para triagem

Revisão de 06/09/2026 sobre `notebooks/ml/` (cinco scripts, 411 linhas) e o
`README.md` do diretório. Não cobre `notebooks/br/`.

Cada achado traz o controle que o produziu e a regra do
`docs/DEVELOPMENT_AND_RESEARCH_GUIDE.md` que ele viola. Os números vieram de
execução sobre `data/interim/painel_ml.parquet` e `auc_por_hora.parquet`, não
de leitura do código.

Referência dos valores em vigor, medidos nos arquivos:

    AUC dentro da hora    M1 0,6847   M2 0,7934   M3 0,7920   (4.540 horas)
    AUC global            M1 0,8872   M2 0,8958   M3 0,9028
    base comum            3.622.152 linhas · 174 conjuntos

---

## 1. As covariáveis de rede do M3 funcionam como identificador da usina

**Regra 2** — controle falsificável e independente do resultado pretendido;
igualdade que vale por construção não é controle.

As oito colunas de `_modelos.py:9` são atributos fixos por usina, mescladas por
`id_ons`. Medido: a 8-tupla assume **172 valores distintos em 174 usinas**
(98,9% identificadas univocamente); `cap_propria` sozinha separa 159.

Controle que faltava: permutar a tupla inteira ENTRE usinas. Preserva a
distribuição marginal e o fato de ser constante por usina; destrói só a
correspondência usina-estrutura. Cinco permutações, mesma configuração do
`_boot_ganho.py`:

    M3 real ....................... dentro da hora 0,7920   global 0,9029
    M3 com rede embaralhada ....... dentro da hora 0,7911   global 0,9002
    faixa do nulo (5 sementes) .... [0,7896; 0,7929]        [0,8968; 0,9059]

    fração do ganho do M2 recuperada:
      rede verdadeira ..... 98,7%
      rede embaralhada .... 97,8%   (faixa 96,5% a 99,5%)

O valor real cai DENTRO da faixa do nulo, a +0,6 desvio. O acréscimo das
covariáveis além de identificar a usina é indistinguível de zero.

CONSEQUÊNCIA para a redação: escrever que as covariáveis de rede recuperam o
ganho da identidade porque constituem um vetor constante por usina com 172
valores distintos. Não escrever que a topologia de rede explica qual usina é
cortada. A ressalva 2 do README ("tensão aparente com a Fig. 12") deixa de
existir: não havia tensão, e o resultado de ML não reverte nem contradiz a
Fig. 12.

Correção: incorporar a permutação aos três scripts, imprimindo o nulo ao lado
do valor real. Dez linhas.

    Rp = R.copy()
    Rp[REDE] = R[REDE].sample(frac=1.0, random_state=SEED).to_numpy()

## 2. O ganho da identidade é 86,4% uma tabela

**Regra 3** — declarar o que o controle não testa.

Linha de base sem modelo: ordenar as usinas dentro da hora pela taxa de corte
que cada uma teve no treino. Um `groupby`, zero árvores.

    M1 (só estado do sistema, LightGBM) ......... 0,6847
    taxa histórica por usina .................... 0,7786
    M2 (LightGBM + identidade) .................. 0,7934

A tabela entrega 86,4% do ganho do M2 sobre o M1. O LightGBM acrescenta
+0,0148 de AUC sobre ela.

A ressalva 1 do README já diz que o M2 é teto de persistência. Falta o número.
Sem a linha de base, +0,109 não tem escala de referência.

Correção: incluir a taxa histórica como quarta linha da tabela de resultados.

## 3. O intervalo de confiança supõe horas independentes

**Regra 15** — declarar sensibilidade a escolha de modelo quando o resultado
depender dela.

`_boot_ganho.py:47-51` reamostra as 4.540 horas individualmente. Autocorrelação
medida na própria tabela: a AUC-por-hora tem lag-1 de +0,66 (M1) e +0,72 (M2);
o ganho M2-M1 tem lag-1 de +0,61 e lag-24 de +0,16.

Bootstrap de bloco móvel sobre a mesma tabela:

    bloco     IC95% ganho identidade      IC95% razão M3/M2    largura
      1 h     [+0,1050; +0,1122]          [97,1%; 100,2%]      3,11 pp   <- em vigor
     24 h     [+0,1007; +0,1170]          [95,2%; 102,0%]      6,78 pp
    168 h     [+0,0940; +0,1205]          [93,4%; 103,1%]      9,70 pp

Reamostras com razão >= 100%: 5,3% no i.i.d., 21,2% com bloco de 24 h.

A frase do README "o intervalo de confiança encosta em 100%" depende da
hipótese de independência.

O IC também cobre uma fonte de variância de três: reamostra horas, mas o ajuste
roda uma vez, com `random_state=42` e um único corte temporal. Sem variância de
ajuste nem de data de split.

Correção: bloco de 24 h no bootstrap, e declarar as duas fontes não cobertas.

## 4. `ml_modelos.csv` combina duas configurações de modelo na mesma linha

**Regra 33** — número que aparece em mais de um lugar tem uma fonte.

`_exportar.py:25-29` monta cada linha com `auc_global` vindo de
`ml_resultados.csv` e `auc_dentro_hora` de `auc_por_hora.parquet`. As duas
cadeias usam hiperparâmetros diferentes:

    _modelos.py:35-37       400 árvores, lr 0,06, min_child_samples 200, subsample 0,8
    _dentro_hora.py:28-29   300 árvores, lr 0,08, min_child_samples 300, sem subsample
    _boot_ganho.py:28-29    idem

Verificado: os valores exportados batem com cada fonte. Nenhum número está
errado; a linha é que não descreve um objeto único.

Correção: uma configuração, num módulo, importada pelos três.

## 5. O README traz duas versões dos mesmos números

**Regras 32, 33, 36** — cabeçalho desatualizado é defeito; uma fonte por
número; duas versões do mesmo documento não coexistem.

A seção que documenta o conserto do M3 traz +0,1087 / +0,1072 / 98,7%. As
seções "Resultado" e "Ressalvas", abaixo, ainda trazem os valores anteriores ao
conserto: AUC 0,885/0,899/0,898 global, 0,679/0,790/0,782 dentro da hora, ganho
+0,1114, fração 92,4%. Os valores em disco são 0,8872/0,8958/0,9028 e
0,6847/0,7934/0,7920.

A ressalva 4 ainda diz "o teste limpo restringiria os três às 174" — o que o
código já faz desde o conserto.

Correção: pela regra 37, levantar o inventário e editar de uma vez.

## 6. `assert` como portão de controle nos cinco scripts

**Regra 4** — o controle roda antes de gravar; usar `raise`, não `assert`.

Todos os controles da cadeia usam `assert`, que desaparece sob `python -O`. Os
controles em si são bem escolhidos e falsificáveis.

Além disso `_boot_ganho.py:43` grava `auc_por_hora.parquet` antes dos controles
das linhas 59-72. Os outros quatro scripts gravam depois.

`notebooks/br/_poa_erro.py` já foi corrigido nesse ponto e serve de referência.

## 7. Associação contemporânea descrita como previsão

**Regra 27** — a força da afirmação corresponde ao desenho do estudo.

Todas as features são da mesma hora do alvo, inclusive `t_fora`, `carga` e
`flx`. A ressalva 2 do README diz "em conjunto e prevendo o intervalo". O
desenho não é de previsão: é associação simultânea, adequada a decomposição e
atribuição.

Correção: substituir "prevendo" por termo que descreva o desenho.

## 8. Nome da variável de ambiente diverge entre três lugares

**Regras 33, 38.**

    docs/DEVELOPMENT_AND_RESEARCH_GUIDE.md, regra 38 ... TERRA_PW_INTERIM
    notebooks/ml/README.md .......................... TERRA_PW_INTERIM
    notebooks/_caminhos.py .......................... <nome do repositório>_INTERIM

O código é o divergente. Hoje `notebooks/_caminhos.py` lê `TERRA_PW_INTERIM`.

## 9. `ffill().bfill()` antes do split temporal

**Regra 4**, preventivo. `_juntar.py:18`. O `bfill` propaga valor futuro para
trás e vazaria para o treino.

Medido: **zero células** são preenchidas por `bfill` hoje — o `ffill` cobre
todas as 1.374 ausentes. O padrão está inerte.

Correção: `ffill()` apenas, mais um controle sobre o resíduo.

## 10. Categorias derivadas separadamente em treino e teste

`_modelos.py:29` recategoriza `fonte` e `id_subsistema` em `tr` e `te`
isoladamente, enquanto `id_cat` é criado em `D` antes do split. Com 2 fontes e
4 subsistemas os códigos não divergem hoje. O padrão é que está invertido.

## 11. `cmo` está em disco e não entra no estado do sistema

`data/raw/cmo/` traz três arquivos anuais, 6,2 MB, custo marginal de operação
horário por subsistema (`id_subsistema`, `din_instante`, `val_cmo`).
`_sistema.py` monta 49 features de térmica, carga, intercâmbio e EAR, e não o
usa. O CMO é o sinal que codifica quando a restrição passa a valer.

Ressalva: para atribuição, o CMO verificado serve. Para previsão (F2), seria
preciso o programado — o verificado não é conhecido no instante da decisão.

Também em disco e sem uso: `fator_capacidade` (80 MB), `coff_fv_detail`.
`data/raw/disponibilidade/` e `data/raw/teif/` existem vazios.

---

## Remedição de 10/09/2026, painel de 51 features

Nenhuma das onze correções acima entrou no código. Depois desta revisão, o
README, o TAREFAS e `report/modelos-metodos.tex:155` passaram a afirmar que "a
rede recupera 97,6% do ganho da identidade, e o IC exclui 100%". As medidas
abaixo não sustentam essa frase.

Todas as medidas usam a mesma base comum de `_boot_ganho.py`: 3.622.152
linhas, 174 conjuntos, 4.540 horas de teste. As AUC por hora vêm de
`data/processed/ml_auc_por_hora.csv`.

**Achado 1 refeito: permutação da tupla de rede entre usinas.** Cinco sementes,
mesmos hiperparâmetros de `_boot_ganho.py`.

| | AUC dentro da hora | fração do ganho do M2 |
|---|---|---|
| M3 publicado | 0,7916 | 97,6% |
| rede embaralhada, 5 sementes | 0,7817 · 0,7885 · 0,7889 · 0,7909 · 0,7903 | 88,5% a 96,9%, média 94,4% |

O valor real fica acima das cinco permutações. O conteúdo de rede além de
identificar a usina é de +0,0035 de AUC, ou 3,2 pp do ganho. Com cinco
permutações, o menor p atingível é 1/6, de modo que esse resíduo não está
estabelecido. A tupla assume 172 valores distintos em 174 usinas, e
`cap_propria` sozinha separa 159.

**Achado 2 refeito: linha de base de tabela, sem modelo.**

| | AUC dentro da hora | fração do ganho do M2 |
|---|---|---|
| M1, só sistema | 0,6853 | — |
| taxa de corte da usina no treino | 0,7786 | 85,7% |
| taxa da usina por hora do dia, no treino | 0,7912 | 97,2% |
| M3 | 0,7916 | 97,6% |
| M2, com identidade | 0,7942 | 100% |

A tabela usina × hora empata com o M3 sem nenhuma covariável de rede.

**Achado 3 refeito: bootstrap de bloco sobre as horas publicadas.**

| bloco | IC95% do ganho da identidade | IC95% da fração | reamostras com fração ≥ 100% |
|---|---|---|---|
| 1 h (em vigor) | [+0,1052; +0,1128] | [96,1%; 99,2%] | 0,2% |
| 24 h | [+0,1012; +0,1164] | [94,5%; 100,8%] | 7,0% |
| 168 h | [+0,0953; +0,1206] | [92,8%; 102,3%] | 16,3% |

"O IC exclui 100%" vale só sob independência entre horas.

**Noite solar no painel.** 14,9% das linhas da base comum são horas solares com
geração 0 e corte 0, corte impossível por construção. Esse é o caso de 45,6%
das linhas solares. Sem elas, a prevalência vai de 0,293 a 0,344. Essas linhas
inflam a AUC global. Dentro da hora, a fração é de 99,2% entre 6h e 17h (2.796
horas) e de 95,8% entre 18h e 5h (1.744 horas).

**O que o resultado sustenta.**

- Dentro da hora, o estado do sistema quase não separa qual usina é cortada:
  AUC 0,685.
- A taxa de corte que a própria usina teve no treino, por hora do dia, sobe
  para 0,791. É uma tabela, sem modelo.
- O LightGBM com identidade chega a 0,794.
- Conclusão: qual usina é cortada é persistente no tempo, e a persistência
  sozinha prevê isso.

**O que o resultado não sustenta.** Que a topologia de rede explique qual usina
é cortada, e que o IC exclua 100%.

Scripts: `base.py`, `baratos.py` e `permuta.py`, no scratchpad da sessão
6aca9a5e (`scratchpad/ml/`), só leitura sobre `data/`.

## O que esta revisão não testou

- Não repetiu o ajuste dos modelos em vigor: os valores de AUC vieram dos
  arquivos gravados. Só o M3 permutado foi ajustado nesta revisão.
- O nulo de permutação tem 5 sementes. Isso estabelece que o valor real cai
  dentro da faixa, não o tamanho exato do resíduo.
- Não avaliou a escolha de hiperparâmetro, ausência de conjunto de validação
  nem de early stopping. Dado o achado 1, é secundário.
- Não verificou a afirmação do README de que o drift de prevalência
  (0,270 -> 0,341) deprime os três modelos igualmente.
- Não cobriu `notebooks/br/` nem os notebooks numerados.
