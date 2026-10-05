# E-marginal-emissions

Forecast the MCTI/SIRENE hourly Operating Margin emission factor 24 hours ahead, using persistence as the baseline.

## Research question

The Operating Margin factor is derived from dispatch, and the system-state features are also derived from dispatch. A contemporaneous model of the factor against those features would reproduce part of the MCTI calculation by construction. This experiment instead asks whether information available at hour `h` can forecast the factor at `h+24`.

The target is the hourly MCTI Operating Margin factor in `tCO2/MWh`. The main comparison is 24-hour persistence: the factor at the current hour used to predict the value at the same hour on the following day.

## Inputs

`_mo.py` downloads the MCTI/SIRENE dispatch workbooks for 2024, 2025, and 2026 when their cached copies are absent. Workbooks are cached under `data/raw/mcti_mo/`.

The hourly factor is stored in a rectangular day-by-hour-by-month worksheet. Invalid calendar dates, such as February 30, are encoded as zero by the source and are excluded by the reader. The reader also checks timestamp uniqueness, positive factors, the upper factor bound, and 24 records per day. Missing hours within the overall interval are reported.

`_experimento.py` also requires `data/interim/painel_sistema_limpo.parquet`. Its producer is outside this experiment directory; this README does not assume or generate that panel. Its index must align with the hourly factor timestamps, and its columns are used as system-state features.

## Run

Run both commands from the repository root:

```text
.venv/bin/python experiments/E-marginal-emissions/_mo.py
.venv/bin/python experiments/E-marginal-emissions/_experimento.py
```

The first command creates `data/interim/mo_horario.parquet`. The second reads that target and the required system-state panel, evaluates the forecast, and runs the C5 and C6 controls.

## Evaluation design

- Target: `MO(h+24)`; features include the state at `h` and the current factor `MO(h)`.
- Chronological split: training data before 2026-01-01; test data on or after that date.
- Baselines: 24-hour persistence and hour-by-month climatology fitted on training data only.
- Model: `HistGradientBoostingRegressor` with 400 iterations, learning rate 0.06, and random state 0.
- Metric: MAE in `tCO2/MWh`; skill is measured relative to 24-hour persistence.
- C4: 2,000 day-block bootstrap replicates for the skill interval.
- C5: positive control that predicts the contemporaneous factor from contemporaneous state; execution stops if its R-squared is at most 0.3.
- C6: alternative chronological cutoff at 2025-07-01, evaluated through the primary cutoff.

The contemporaneous positive control is not a forecasting result. It checks that the data join and modeling pipeline can recover a signal when one is expected.

## Outputs

| File | Description |
|---|---|
| `data/raw/mcti_mo/despacho_2024.xlsx` | Cached 2024 source workbook |
| `data/raw/mcti_mo/despacho_2025.xlsx` | Cached 2025 source workbook |
| `data/raw/mcti_mo/despacho_2026.xlsx` | Cached 2026 source workbook |
| `data/interim/mo_horario.parquet` | Hourly target series, indexed by `h`, value column `mo` |
| `data/interim/f14_teste.parquet` | Test timestamps, target, model forecast, persistence, and climatology |

## Limitations

- The hourly target is the MCTI dispatch-based factor, not a direct emissions measurement.
- The target workbook's calendar grid encodes nonexistent dates as zero; the reader filters these rows before building the series.
- The experiment depends on `painel_sistema_limpo.parquet`, which is not produced in this directory.
- The chronological split and 24-hour horizon do not establish availability of every feature at an operational issue time; publication-time validation is not implemented here.
- The model configuration is fixed. The script does not perform hyperparameter search or repeated-seed evaluation.
