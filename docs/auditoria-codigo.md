# Auditoria de funcionamento do código — 10/09/2026

Dos 82 arquivos auditados, 53 rodam e reproduzem o artefato em disco ou o
número registrado (N3). Há 1 quebrado (N0). Os outros 28 compilam, e todos têm
as entradas em disco, menos 4 (N1). Não foram executados até o fim: gravam fora
do scratchpad, passam de 10 min, ou param no próprio controle.

Quatro resultados registrados não saem do código atual:

- F1b, a concordância de 96,6%;
- o controle 1 do F6;
- a contagem de dias-usina do F6;
- a seção "Resultado" do `notebooks/ml/README.md`.

## Critério

| nível | significa |
|---|---|
| N0 | quebrado: import falha, API chamada não existe, entrada perdida |
| N1 | compila e importa |
| N2 | todas as entradas existem em disco, no banco ou na rede |
| N3 | executado até o fim, com a saída conferida contra o disco (byte a byte ou igualdade de DataFrame) ou contra o número do README / TAREFAS / report |

Condições de execução:

- Nenhuma execução escreveu em `data/`, `figures/` ou no banco. As saídas foram
  para o scratchpad, via `TEE_INTERIM` e `TERRA_PW_INTERIM`, por cópia do
  script com só o caminho de saída trocado, ou por árvore espelho.
- Limite de 10 min por execução.
- O pyflakes não acha nome indefinido nem import quebrado em nenhuma zona, só
  imports sem uso.

| zona | arquivos | N3 | N2 | N1 | N0 |
|---|---|---|---|---|---|
| `src/tee` | 7 | 7 | | | |
| `experiments/` | 22 | 17 | 4 | 1 | |
| `notebooks/` raiz (builders, `.ipynb`, auxiliares) | 25 | 12 | 12 | 1 | |
| `notebooks/{br,ml,despacho,emissao,risco}` | 28 | 17 | 8 | 2 | 1 |
| total | 82 | 53 | 24 | 4 | 1 |

## Resultados registrados que o código atual não reproduz

1. **F1b, concordância fixo/rastreador.**
   - `report/execucao-poa.tex:132` e o TAREFAS F1b registram 96,6%.
   - `notebooks/br/_forma_diurna.py:89` compara `geometria == por_forma`
     literalmente. O `poa_erro_por_usina.csv` agora tem três classes (139
     rastreador, 96 "sensor horizontal", mais o fixo), e o script dá 59,3%
     (140/236).
   - Contando "sensor horizontal" como fixo, dá 96,2%.
   - O laço mensal (`:100-106`) exige 5 fixas por mês e hoje há 2, então
     imprime vazio: a afirmação "estável nos 12 meses" não sai do código.
2. **F6, controle 1.**
   - `notebooks/br/_desempenho.py:120` aborta com a mensagem "1 usinas com PR
     realizado acima do potencial".
   - A usina é São Gonçalo 4 (`UFV.RS.PI.033844-3`): `pr_real` 0,840 contra
     `pr_pot` 0,816, acima da tolerância de 0,02.
   - O `data/processed/desempenho_por_usina.csv` publicado contém a mesma
     violação, portanto foi gravado antes de o controle existir.
   - Os agregados batem com o TAREFAS: PR 0,838 / 1,023 / 0,998 e lacunas
     0,227 / 0,031.
3. **F6, contagem.** `report/execucao-desempenho.tex:53` diz 69.297
   dias-usina. O rerun dá 67.150 em 236 usinas.
4. **ML.** A seção "Resultado" do `notebooks/ml/README.md` ainda traz os
   números anteriores à correção do M3: 0,885 / 0,899 / 0,898, +0,1114, 92,4%
   e a "Ressalva 4". Os números atuais, na mesma README, são
   0,8866 / 0,8980 / 0,9008 e 97,6%.

## Reprodutibilidade

1. **Mês incompleto.**
   - `notebooks/_build_notebook_10.py:267,287` e
     `_build_notebook_11.py:165-192,306` não aplicam `LAST_COMPLETE`.
   - O CKAN já lista 2026_09, que não está em disco. Rodar hoje baixa o mês
     parcial e muda a janela de quantis.
   - O 12 herda o problema.
2. **Insumos sem gerador no repositório.** Se forem perdidos, não se
   reconstroem.
   - `fig7_painel.csv`, `fig7_candidatos2.csv`, `fig7_membros.csv`,
     `s2/cenas.json` e `s2/jaiba_*.npy`, lidos pelo notebook 07.
   - `fc_pq/*.parquet` e `aneel/siga.csv`, lidos pelos notebooks 04 e 06.
   - `power_grid/`, lido por 06 e por `br/_etapa0.py:38`.
   - `alvo_siga.csv`, lido por `_aplicacao_expansao.py:26`.
   - `data/interim/pr_dia_2025.csv` e `corte_conj_2025.csv`, lidos por
     `br/_desempenho.py:42-43`. Saíram de SQL ad hoc que só está no transcript
     da sessão; a tabela `br.tmp_pr_dia` ainda existe no banco (78.560 linhas,
     418 usinas).
3. **`psycopg` fora do `pyproject.toml`.**
   - `store.connect` levanta `MissingDependency` no `uv run`.
   - Rodam só com o `.venv` do geosense-infer: `_latitude`, `_sazonalidade`,
     `_piso_corte`, `_tilt_pareado`, `_power_h_todas`, `_carga_postgis`,
     `_carga_rede` e `_bench_store`.
4. **Caminho absoluto do sidecar.**
   - `/Users/fox/estudos/UTFPr/geosense/geosense-infer/sidecar` está em 8
     arquivos de `notebooks/br/`: `_bench_store:1`, `_carga_postgis:2`,
     `_carga_rede:3`, `_latitude:1`, `_piso_corte:12`, `_power_h_todas:2`,
     `_sazonalidade:1` e `_tilt_pareado:16`.
   - O caminho existe e `terra.grid` importa.
5. **Figura depende do ambiente.** A última célula dos 12 notebooks chama
   `~/.claude/skills/nature-figure/scripts` com o `python` do PATH, não o do
   venv. Exemplos: `_build_notebook.py:678` e `_build_notebook_12.py:545`.
6. **Cache anual envelhece.** `CURVA_CARGA_2026.csv` e
   `INTERCAMBIO_NACIONAL_2026.csv`, usados por 08 e 09, ficam em cache pelo
   teste `exists()` e não se atualizam.
7. **Notebooks sem builder.** 05 e 06: o `.ipynb` é a única fonte.
8. **Log de `_modelos.py` perdido.** `notebooks/ml/_modelos.py` roda 7 min e
   imprime sem `flush`; morto por tempo, não deixa saída.

## `src/tee`

1. `registro.py:118`: `_nowcasting` declara `como="recomputado"`, mas só lê os
   dois CSVs e confere a habilidade contra os RMSE gravados. Além disso, o RMSE
   do adversário é a média dos três horizontes.
2. `registro.py:125-126`: a linha "adversario" da vizinhança recebe
   `hab_proprio.iloc[0]`, a habilidade de 30 min do modelo próprio, e ignora os
   outros horizontes.
3. `registro.py:230-238`: falta adaptador para E-despacho-termico, embora o
   `resultado.json` dele tenha habilidade e IC. `cli.py:3` diz "todos os
   experimentos".
4. Sem chamador: `avaliacao.py:76` (`dobras_expansivas`), `avaliacao.py:86`
   (`meses_de_teste`), `fontes.py:122` (`dias_ausentes`), `portao.py:33`
   (`MEDIDO`, nenhum controle compara contra ele) e `caminhos.py:19`
   (`RELATORIO`).

## Duplicação remanescente em relação a `tee`

A docstring de `src/tee/avaliacao.py:1-6` diz que as cópias do bootstrap foram
recolhidas. Não foram:

| o quê | onde |
|---|---|
| MAE e bootstrap de habilidade | `E-preco-cmo/3_modelos.py:53-58,118-135`, `5_ablacao.py:136-144`, `E-despacho-termico/3_medida.py:122,126`, `notebooks/despacho/_experimento.py:37,65`, `notebooks/emissao/_experimento.py:31`, `notebooks/risco/_interrupcao.py:92` |
| E-nowcasting-poa inteiro | não usa `tee`. `ceu_claro` está em 1 e 4; `monta`, `dobras`, `ajusta`, `rmse` e o bootstrap estão em 2, 3 e 5. Saída fixa relativa ao cwd; `TEE_INTERIM` não o redireciona |
| raiz e intermediário | `E-despacho-termico/_comum.py:9-11`; `notebooks/_caminhos.py:11` (`TERRA_PW_INTERIM`, relativo ao cwd, cria a pasta no import) com 11 importadores; `ROOT = Path.cwd()...` em 14 arquivos da raiz de `notebooks/` |
| cliente do CKAN | `ckan_resources` / `ckan_csv` / `fetch` em 01, 08, 09, 10, 11 e 12, com três variantes |
| leitores crus do ONS | `_build_notebook_03.py:226`, `_08:357,365`, `_09:275,284`, `_aplicacao_expansao.py` (7º leitor do COFF) |
| POA por tilt | `serie` e `poa_por_tilt` em `_transpor`, `_otimo`, `_tilt_pareado` e `_poa_erro` |
| preparo do ML | linhas 7–25 de `ml/_modelos.py`, `_dentro_hora.py` e `_boot_ganho.py` |

A variável do intermediário tem dois nomes: `TEE_INTERIM` no pacote e no
CLAUDE.md, `TERRA_PW_INTERIM` na regra 38 do guia, em `notebooks/_caminhos.py`
e em `notebooks/ml/README.md`.

## Documentação desatualizada

- `E-nowcasting-poa/README.md:9-11` e as docstrings dos cinco passos: o comando
  está sem o prefixo `experiments/`. O README lista só os passos 1 a 3.
- `E-nowcasting-poa/4_preparo_viz.py:5` diz "ligação de 25 km"; o código usa
  `LIGACAO_KM = 60` (`:29`).
- `E-nowcasting-poa/README.md:202-203` cita um controle que exige que toda
  usina tenha intervalo de análise. Ele não existe em `4_preparo_viz.py`.
- ENA "~2,3 dias" em `E-preco-cmo/_comum.py:21` e `README.md:76`;
  `tee-engine portao` mede 2,47 d.
- `E-preco-cmo/2_controles.py:15-16`: o atraso está em `tee.portao`, não em
  `_comum`. `_painel.py:3` diz "(C4)", mas é C3. `_painel.py:32` cita um
  controle C9 que não existe.

## Órfãos

- Nada no report nem no TAREFAS cita estes scripts: `notebooks/br/_bench_store`
  (N0: chama `ons.read`, que não existe mais no terra, e o `CACHE` da linha 4
  aponta para o scratchpad apagado da sessão 149f9785), `_carga_postgis`,
  `_carga_rede`, `_etapa0`, `_latitude`, `_sazonalidade` e `_piso_corte`.
- `_transpor` e `_otimo` estão declarados como substituídos no README de `br/`.
- Funções sem chamador: `E-despacho-termico/_comum.py:58`
  (`colunas_valor`).

## Por arquivo

### `src/tee` — 7 de 7 em N3

| arquivo | evidência |
|---|---|
| `cli.py` | `conferir` passa, com 7 experimentos coletados e 0 falhas; `tabela --tudo` e `portao` saem com rc 0 |
| `caminhos.py` | `conferir_raiz` passa; `TEE_INTERIM` redirecionou todas as escritas de despacho, osciloscópio e preco-cmo |
| `fontes.py` | osciloscópio e painel preco-cmo refeitos por `tee.fontes` saem idênticos |
| `portao.py` | atrasos: cmo −0,56 d, carga 1,23, intercâmbio 1,24, EAR 2,18, ENA 2,47 |
| `avaliacao.py` | o `ic_habilidade` sobre `previsoes.parquet` dá [−6,72; +7,70] e [+15,28; +20,21], igual ao `resultado.json` |
| `registro.py` | a tabela bate com os READMEs (preco-cmo +0,76%; nowcast +7,3 / +8,0 / +9,9%); rótulos com defeito, ver acima |
| `__init__.py` | importa |

### `experiments/`

| arquivo | nível | evidência |
|---|---|---|
| E-despacho-termico `1_painel` | N3 | 131 s; 2.601.600 linhas, 186 usinas |
| E-despacho-termico `2_controles` | N3 | LIBERADO; `controles.json` idêntico |
| E-despacho-termico `3_medida` | N3 | B1 −4,55% [−7,38; −1,92]; `resultado.json` idêntico |
| E-despacho-termico `_comum` | N3 | usado pelos três passos |
| E-osciloscopio `1_exportar`, `2_controles`, `3_montar`, `_comum` | N3 | `sinais.bin` idêntico; 6 de 6 controles passam; HTML de 4,07 MB |
| E-osciloscopio `_ui.html` | N3 | Chrome headless: "Controles Python 6/6" e "Pico-detector JS confere com o gabarito" |
| E-preco-cmo `1_painel`, `2_controles`, `_painel`, `_comum` | N3 | painel e `janelas.json` idênticos; 6 de 6 controles passam, C3 com 0 divergências em 307.200 células |
| E-preco-cmo `4_decomposicao` | N3 | `decomposicao.json` idêntico |
| E-preco-cmo `3_modelos` | N2 | morto em 600 s (README: 864 s de ajuste); o `resultado.json` se recompõe do `previsoes.parquet` |
| E-preco-cmo `5_ablacao` | N2 | não executado (7 origens × 15 meses); o `ablacao.json` existente bate com o README |
| E-preco-cmo `_modelos_comum` | N1 | importa |
| E-nowcasting-poa `1_preparo` | N3 | 231 s; parquet igual (857.376 linhas) |
| E-nowcasting-poa `2_modelos` | N3 | `nowcast_habilidade.csv` idêntico |
| E-nowcasting-poa `4_preparo_viz` | N3 | `viz_usinas.csv` e `viz_dist.npy` idênticos |
| E-nowcasting-poa `3_controles` | N2 | morto em 600 s no horizonte de 3 h; 30 min e 1 h batem com o README ao decimal |
| E-nowcasting-poa `5_vizinhanca` | N2 | morto no horizonte de 3 h; 30 min bate (+7,38 / +9,73 / +11,02, IC [1,73; 2,99]) |

### `notebooks/` raiz

| arquivo | nível | evidência |
|---|---|---|
| `_build_notebook*.py` (10) | N3 | cópia no scratchpad regenera células idênticas às do `.ipynb` |
| `_aplicacao_expansao.py` | N3 | os 4 `aplicacao_*.csv` saem idênticos (`cmp`) |
| `_fig_aux_geopera.py` | N3 | PNG com diferença máxima de pixel 0 |
| `_caminhos.py` | N1 | compila |
| `01`–`09`, `12` `.ipynb` | N2 | JSON válido, células compilam, outputs presentes, 0 outputs de erro; não executados porque gravam em `data/processed` e `figures/` |
| `10`, `11` `.ipynb` | N2 com defeito | idem, mais o mês incompleto (Reprodutibilidade, item 1) |

### `notebooks/br/`

| arquivo | nível | evidência |
|---|---|---|
| `_poa_erro` | N3 | 237 usinas, 66.917 dias; CSV e parquet idênticos |
| `_tilt_pareado` | N3 | 174 usinas; mediana +0,0°, p10 −12,5°, p90 +10,0° |
| `_sazonalidade` | N3 | 104 usinas; amplitude 1,149 |
| `_otimo`, `_transpor` | N3 | CSVs idênticos (substituídos) |
| `_etapa0` | N3 com ressalva | viés −0,989 (−14,8%) bate; 149.991 dias contra 148.575, porque o bruto cresceu |
| `_poa_medida` | N2 | não rodado (`CREATE TEMP TABLE`); a mesma lógica como CTE reproduz 69.550 de 69.550 linhas |
| `_forma_diurna` | N2, diverge | 59,3% contra 96,6% |
| `_desempenho` | N2, controle falha | São Gonçalo 4 |
| `_latitude` | N2 | consulta passou de 600 s |
| `_piso_corte` | N2 | roda em 28 s; sem número registrado para conferir |
| `_power_h`, `_power_h_todas` | N2 | células em cache; rodar inteiro baixaria 1 célula |
| `_carga_postgis`, `_carga_rede` | N1 | escrevem no banco; não rodados |
| `_bench_store` | N0 | `ons.read` não existe |

### `notebooks/ml/`, `despacho/`, `emissao/`, `risco/`

Cadeia do ML: `_painel` → `_sistema` → `_juntar` → `_modelos` →
`_dentro_hora` → `_boot_ganho` → `_exportar`, lida por
`src/tee/registro.py:141`. Reconstrói bit-idêntica até `painel_ml`.

| arquivo | nível | evidência |
|---|---|---|
| `ml/_painel` | N3 | 8.017.488 linhas, idêntico |
| `ml/_sistema` | N3 | 56 colunas × 21.192 h, idêntico |
| `ml/_juntar` | N3 | `painel_ml` idêntico |
| `ml/_modelos` | N3 | AUC 0,8872 / 0,8957 / 0,8866 / 0,8980 / 0,9008, idênticos |
| `ml/_dentro_hora` | N3 | AUC 0,6853 / 0,7942 / 0,7916 |
| `ml/_exportar` | N3 | três saídas idênticas a `data/processed` |
| `ml/_boot_ganho` | N2 | interrompido no encerramento |
| `despacho/_corte` | N3 | 304,20 / 278,23 / 25,99 TWh; parquet idêntico |
| `despacho/_experimento` | N3 | +10,2% [−3,0; +21,5]; `f12_teste` idêntico |
| `emissao/_mo` | N3 | 22.632 h; `mo_horario` idêntico |
| `emissao/_experimento` | N3 | −28,1% [−38,0; −19,1]; `f14_teste` idêntico |
| `risco/_interrupcao` | N3 | AP 0,0147 contra 0,0190, IC [−0,0178; +0,0002]; saídas idênticas |

## O que ficou sem teste

- **Quatro passos longos:** `E-preco-cmo/3_modelos` e `5_ablacao`, e os
  horizontes de 3 h de `E-nowcasting-poa/3_controles` e `5_vizinhanca`. Pedem
  execução sem limite de tempo e com a CPU livre.
- **Os 12 notebooks:** executá-los exige a sandbox com `ROOT` apontado para o
  scratchpad. 10 e 11 gravariam 2026_09 em `data/raw` enquanto o item 1 de
  Reprodutibilidade não for corrigido.
- **Scripts que escrevem no banco:** `_carga_postgis` e `_carga_rede`.

Logs e saídas das execuções ficaram no scratchpad da sessão 6aca9a5e
(`auditoria/`, `auditoria-nb/`, `auditoria-sub/`).
