# lucertae-research

Séries abertas do setor elétrico brasileiro, tratadas como tarefas de
aprendizado de máquina com adversário declarado e controle antes do número.

Rodar sempre da raiz do repositório. `data/`, `figures/`, `models/` e `logs/`
estão fora do git; o intermediário é sobrescrevível por `LUCERTAE_INTERIM`.

Este repositório junta, desde 02/10/2026, dois que estudavam o mesmo assunto
sobre o mesmo banco: `lucertae` (relatório do corte fotovoltaico, experimentos
com controle bloqueante) e `terra-energy-research` (previsão do corte solar e
eólico por cluster). Os dois históricos estão preservados.

## Onde está o quê

| | |
|---|---|
| `docs/DEVELOPMENT_AND_RESEARCH_GUIDE.md` | as 53 regras que valem para código, medição e escrita |
| `TAREFAS.txt` | estado de cada experimento, com aberta / fechada / impossível |
| `report/` | o relatório do corte fotovoltaico no SIN e os documentos avulsos de execução |
| `report/tarefas-dados.tex` | as 16 famílias de tarefa e a fonte nacional de cada uma |
| `experiments/` | experimentos com passos numerados e controle bloqueante |
| `notebooks/` | a série 01 a 12 do relatório, anterior à convenção de `experiments/`, e os dois notebooks do corte por cluster (`01_eda_curtailment`, `02_system_drivers`) |
| `src/lucertae/` | o que os experimentos partilham |
| `src/lucertae/corte/` | previsão do corte por cluster × 30 min, com `sql/`, `reports/` e `docs/corte.md` |
| `docs/postgis.md` | como montar o banco `terra_br` |

## O pacote `lucertae`

```
lucertae tabela      compara os modelos de todos os experimentos
lucertae portao      refaz a medida de atraso de publicação das fontes
lucertae conferir    controles do pacote
```

`fontes` traz um leitor por série do ONS — CMO, carga, intercâmbio, EAR, ENA —
sem interpolar buraco. `portao` guarda o atraso de publicação medido e o portão
de informação que dele decorre. `avaliacao` traz perda, habilidade e IC por
bloco. `registro` monta a tabela dos modelos lendo o artefato de cada
experimento, sem transcrever número.

`corte` tem os seus próprios passos (`python -m lucertae.corte.ons`, `.weather`,
`.dataset`, `.baseline`, `.experiments`, `.model`), descritos em
[`docs/corte.md`](docs/corte.md).

O pacote se chamava `tee` (terra energy engine) até 02/10/2026. O nome saiu
porque é também o do motor de cálculo do Solara, que é outro projeto.

## Convenção de experimento

```
_comum.py       caminho, esquema e leitura. Sem análise.
1_*.py          monta o painel e conta todo descarte
2_controles.py  controles falsificáveis; reprovação bloqueia o passo seguinte
3_*.py          o número
README.md       desenho, resultado, limites declarados e não testado
```

Controle roda antes de gravar, com `raise` e não `assert`. Resultado negativo é
resultado. O que não foi testado está escrito.

## Banco

Tudo o que vem do registro elétrico sai do PostGIS local `terra_br`, carregado
pelo [TERRA](https://github.com/rexionmars/TERRA). Ver `docs/postgis.md`.
