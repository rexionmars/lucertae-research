# lucertae-research

Machine learning on the open data of the Brazilian power sector, with one rule:
a model is only reported against a declared adversary, and only after a control
that could have failed.

The repository holds nine experiments on the National Interconnected System
(SIN), the Python package they share, a report on photovoltaic curtailment and
the specification of a map product built on the same data. The data window is
April 2024 to August 2026.

## Contents

- [Method](#method)
- [Results](#results)
- [Experiments](#experiments)
- [Getting started](#getting-started)
- [The `lucertae` package](#the-lucertae-package)
- [Repository layout](#repository-layout)
- [Data and database](#data-and-database)

## Method

Four practices apply to every experiment.

| Practice | What it means here |
|---|---|
| Declared adversary | Each model is compared with the strongest naive forecast for its task: persistence, seasonal naive or climatology. Skill is `1 - model_loss / adversary_loss`. Negative skill is a result and is reported as one. |
| Control before the number | Every script that produces a number carries a falsifiable control that runs before anything is written, with `raise` and not `assert`. A failed control blocks the next step. |
| Information gate | A feature only enters a forecast if its source had published it by the time the forecast is issued. The publication lag of each source is measured from the files on disk, and `lucertae gate` repeats the measurement. |
| Block bootstrap | Confidence intervals resample whole days, not rows. Half-hours of the same day are dependent, and resampling rows would return an interval that is too narrow. |

## Results

Output of `lucertae table` on 2026-10-03. Each row is read from the artifact its
experiment wrote; the command is the source of these numbers. Skill is relative
to the adversary of the same row, with a 95% interval from a bootstrap over day
blocks (1,000 or 2,000 resamples, depending on the experiment).

| Experiment | Target | Loss | Adversary | Model | Skill (95% CI) | Verdict |
|---|---|---|---|---|---|---|
| E-cmo-price | half-hourly CMO of day D | MAE | seasonal naive | LightGBM, two-part | +0.8% (−6.7% to +7.7%) | ties |
| E-nowcasting-poa | plane-of-array irradiance, 30 min ahead | RMSE | clear-sky index persistence | LightGBM | +7.3% (+6.7% to +7.8%) | beats |
| E-nowcasting-poa | same, 1 h ahead | RMSE | clear-sky index persistence | LightGBM | +8.0% (+7.3% to +8.6%) | beats |
| E-nowcasting-poa | same, 3 h ahead | RMSE | clear-sky index persistence | LightGBM | +9.9% (+8.4% to +11.6%) | beats |
| E-scheduled-curtailment | fraction of wind and solar curtailed, D+1 | MAE | persistence D-7 | LightGBM | +10.2% (−3.3% to +21.2%) | ties |
| E-marginal-emissions | marginal emission factor, 24 h ahead | MAE | 24 h persistence | LightGBM + system state | −28.1% (−38.0% to −19.5%) | loses |

Three results do not fit that table:

- **E-nowcasting-poa, neighbouring plants.** Adding the four nearest plants to a
  plant's own past gains +2.3% at 30 min and +1.3% at 1 h, both with intervals
  above zero. At 3 h the gain is +0.5% (−0.3% to +1.2%), not distinguishable
  from zero.
- **E-when-which.** Three nested classifiers of curtailment by plant and hour
  reach AUC 0.887 (system state), 0.898 (plus plant identity) and 0.901 (plus
  network covariates). There is no naive adversary and no interval; the reading
  is the contrast between the three.
- **E-load-risk.** Mean average precision over four folds is 0.0186 for the
  model and 0.0216 for the subsystem × hour table. No skill is derived: the
  published number comes from stacked out-of-fold predictions that are not
  written to disk, so it cannot be recomputed.

The losses differ in nature. Skill is only comparable within the same target.

## Experiments

| Folder | Question |
|---|---|
| [`E-cmo-price`](experiments/E-cmo-price/) | Is the next-day marginal operating cost predictable from the system state, or is repeating the previous day the best available? |
| [`E-nowcasting-poa`](experiments/E-nowcasting-poa/) | How far does a model beat clear-sky index persistence on plane-of-array irradiance at 30 min, 1 h and 3 h? |
| [`E-poa-validation`](experiments/E-poa-validation/) | Stage 0: is the measured irradiance in the ONS curtailment detail usable, and what corrections does it need? |
| [`E-scheduled-curtailment`](experiments/E-scheduled-curtailment/) | Is the curtailment that ONS will schedule for tomorrow predictable from tomorrow's forecast and the curtailment history? |
| [`E-cluster-curtailment`](experiments/E-cluster-curtailment/) | Curtailment forecast by cluster × 30 min, solar and wind, with selection on validation, a test set and monthly retraining. |
| [`E-when-which`](experiments/E-when-which/) | How much of curtailment is explained by when it happens (system state) and how much by which plant it hits? |
| [`E-thermal-dispatch`](experiments/E-thermal-dispatch/) | How much of the thermal generation of the SIN is a decision rather than a price outcome, and does the day-ahead schedule hold? |
| [`E-marginal-emissions`](experiments/E-marginal-emissions/) | Can the marginal emission factor be forecast 24 h ahead better than persistence? |
| [`E-load-risk`](experiments/E-load-risk/) | Does the system state in one hour predict a load interruption in the next? |

An experiment written under the current convention has this shape:

```
_comum.py       paths, schema and reading. No analysis.
1_*.py          builds the panel and counts every discard
2_controles.py  falsifiable controls; a failure blocks the next step
3_*.py          the number
README.md       design, result, declared limits and what was not tested
```

`E-cmo-price` and `E-thermal-dispatch` follow it. `E-nowcasting-poa` has
numbered steps with the controls after the models, and the others predate the
convention and keep their original scripts.

## Getting started

Requirements: Python 3.12 or later and [uv](https://docs.astral.sh/uv/). The
experiments that read the electrical registry also need a local PostgreSQL with
PostGIS (see [Data and database](#data-and-database)).

```sh
git clone https://github.com/rexionmars/lucertae-research.git
cd lucertae-research
uv sync
```

Always run from the repository root. With the raw data in place:

```sh
uv run lucertae check     # repository root, information gate, registry
uv run lucertae gate      # measured publication lag of each source
uv run lucertae table     # models of every experiment against their adversaries
```

An experiment runs step by step, in order:

```sh
uv run python experiments/E-cmo-price/1_painel.py
uv run python experiments/E-cmo-price/2_controles.py   # blocks step 3 if a control fails
uv run python experiments/E-cmo-price/3_modelos.py
```

Outputs go to `data/interim/<experiment>/`. Set `LUCERTAE_INTERIM` to write
intermediates somewhere else.

## The `lucertae` package

`src/lucertae/` holds what the experiments share, so that every experiment
reads the same series and computes skill the same way.

| Module | Content |
|---|---|
| `sources.series` | one reader per ONS series: CMO, load, net interchange, stored energy (EAR), natural inflow energy (ENA). Each series comes on the regular grid of its native step, with gaps as explicit NaN and no interpolation. |
| `gate` | the measured publication lag of each source and the gate, in days, derived from it |
| `evaluation` | MAE, RMSE, skill, block-bootstrap confidence interval, expanding folds |
| `registry` | one result schema and one adapter per experiment; builds the comparison table by opening each artifact |
| `paths` | repository root, `data/raw`, `data/processed` and the intermediate directory |
| `sources.ons`, `sources.weather` | download of ONS and Open-Meteo data and loading into PostGIS through `sources.db` |
| `viz` | figure style for the notebooks |

```python
from lucertae.evaluation import mae, skill, skill_ci
from lucertae.gate import GATE_DAYS
from lucertae.sources import series

cmo = series.cmo()               # DataFrame, 30 min step, one column per subsystem
series.missing_days(cmo)         # days with no CMO at all, as a list of dates
GATE_DAYS["load"]                # 2: load is usable up to the end of day D-2

skill(y_true, model, adversary, loss=mae)
skill_ci(y_true, model, adversary, blocks=days, loss=mae)
```

Column names that come from ONS files (`din_instante`, `id_subsistema`,
`val_*`) and keys read from experiment artifacts stay as published.

## Repository layout

| Path | Content |
|---|---|
| `src/lucertae/` | the shared package and its command line |
| `experiments/` | the nine experiments |
| `notebooks/` | series 01 to 12 of the curtailment report, older than the `experiments/` convention |
| `sql/` | tables of the `br` schema for system data, and the `clean` layer on top of it |
| `report/` | the report on photovoltaic curtailment in the SIN and the standalone execution documents |
| `report/tarefas-dados.tex` | the 16 task families and the national source of each one (`tarefas-dados-en.tex` in en-US) |
| `docs/methods/` | how to build the database, and the column dictionary of the cluster dataset |
| `docs/product/` | specification of the map product for distribution utilities: ML views, platform, catalogue of 66 features, diagrams and mockup |

`data/`, `figures/`, `models/` and `logs/` are outside git.

## Data and database

**Raw files.** The raw data is not distributed with the repository. The series
readers expect the ONS open-data CSV files under `data/raw/`, one folder per
dataset: `cmo/`, `curva_carga/`, `intercambio/`, `ear_subsistema/` and
`ena_subsistema/`. The files come from the
[ONS open data portal](https://dados.ons.org.br/).

**Database.** Everything that comes from the electrical registry (plants, ONS
units, network, curtailment by plant) is read from a local PostGIS database
named `terra_br`. Its base tables are loaded by
[Solara](https://github.com/rexionmars/Solara), a separate project; the system
tables and the cleaning layer are loaded from here:

```sh
uv run python -m lucertae.sources.ons download --start 2024-04-01 --end 2026-08-31
uv run python -m lucertae.sources.ons load     --start 2024-04-01 --end 2026-08-31
uv run python -m lucertae.sources.weather download
uv run python -m lucertae.sources.weather load
```

[`docs/methods/postgis.md`](docs/methods/postgis.md) has the installation steps
and the loading order.

**Sources.**

| Source | Used for |
|---|---|
| [ONS open data](https://dados.ons.org.br/) | CMO, load, interchange, hydrology, thermal dispatch, daily schedule, wind and solar curtailment |
| [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) | archived ECMWF IFS 0.25° forecasts at the solar and wind clusters; free for non-commercial use |
| [NASA POWER](https://power.larc.nasa.gov/) | hourly irradiance for the validation of measured irradiance |
| ANEEL plant register | plant location and capacity, through the Solara base tables |
