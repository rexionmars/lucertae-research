# lucertae-research

Open series of the Brazilian power sector, treated as machine learning tasks
with a declared adversary and a control before the number.

Always run from the repository root. `data/`, `figures/`, `models/` and `logs/`
are outside git; `LUCERTAE_INTERIM` overrides the directory for intermediates.

Since 2026-10-02 this repository joins two that studied the same subject on the
same database: `lucertae` (report on photovoltaic curtailment, experiments with
blocking controls) and `terra-energy-research` (solar and wind curtailment
forecast by cluster). Both histories are preserved.

## Where things are

| | |
|---|---|
| `report/` | the report on photovoltaic curtailment in the SIN, and the standalone execution documents |
| `report/tarefas-dados.tex` | the 16 task families and the national source of each one (`tarefas-dados-en.tex` in en-US) |
| `experiments/` | experiments with numbered steps and blocking controls |
| `experiments/E-cluster-curtailment/` | curtailment forecast by cluster × 30 min, with its two notebooks and results |
| `notebooks/` | series 01 to 12 of the report, older than the `experiments/` convention |
| `src/lucertae/` | what the experiments share |
| `sql/` | tables of the `br` schema and the cleaning layer on top of it |
| `docs/methods/postgis.md` | how to build the `terra_br` database |
| `docs/methods/dataset_curtailment.md` | column dictionary, assumptions and limitations of the cluster dataset |
| `docs/product/` | specification of the map product for distribution utilities: ML views, platform, catalogue of 66 features, diagrams and mockup |

## The `lucertae` package

```
lucertae table    compare the models of every experiment
lucertae gate     repeat the publication-lag measurement of the sources
lucertae check    package controls
```

| Module | Content |
|---|---|
| `sources.series` | one reader per ONS series (CMO, load, interchange, EAR, ENA), with no gap interpolation |
| `gate` | the measured publication lag and the information gate derived from it |
| `evaluation` | loss, skill and block-bootstrap confidence interval |
| `registry` | the table of models, built by reading each experiment's artifact, with no transcribed number |
| `sources.ons`, `sources.weather` | download of ONS and Open-Meteo data and loading into PostGIS through `sources.db` |
| `viz` | figure style for the notebooks |

The cluster forecast has its own steps, described in
[`experiments/E-cluster-curtailment/README.md`](experiments/E-cluster-curtailment/README.md).

The package was called `tee` (terra energy engine) until 2026-10-02. The name
was dropped because it is also the name of the calculation engine of Solara,
which is another project.

## Experiment convention

```
_comum.py       paths, schema and reading. No analysis.
1_*.py          builds the panel and counts every discard
2_controles.py  falsifiable controls; a failure blocks the next step
3_*.py          the number
README.md       design, result, declared limits and what was not tested
```

A control runs before writing, with `raise` and not `assert`. A negative result
is a result. What was not tested is written down.

## Database

Everything that comes from the electrical registry is read from the local
PostGIS `terra_br`, loaded by [Solara](https://github.com/rexionmars/Solara).
See [`docs/methods/postgis.md`](docs/methods/postgis.md).
