# E-scheduled-curtailment

Estimate how much forecast wind and solar generation the ONS does not schedule, aggregated to the SIN by half-hourly step.

## Research question

The source dataset, `programacao_x_previsao`, contains forecast generation and scheduled generation for each plant and step. Their difference is a scheduling decision, not forecast error: it measures forecast output that the operator chose not to schedule one day ahead. The estimand is therefore constrained-off from the scheduling perspective, not from measured generation.

The forecast for the target day is an input because it is available when the schedule is produced. Scheduled generation for that target day is the outcome and is excluded from the features.

## Inputs

Place the source Parquet files in:

```text
data/raw/programacao_previsao/*.parquet
```

The directory must contain more than 600 files. Each file must include `dat_programacao`, `num_patamar`, `val_previsao`, and `val_programado`. The numeric values may be stored as text; the reader converts them and fails if any non-null value cannot be parsed.

`_corte.py` aggregates records by scheduling date and step. It calculates:

- `prev`: forecast generation summed across plants;
- `prog`: scheduled generation summed across plants;
- `corte`: `prev - prog`;
- `frac`: `corte / prev` when `prev > 0`, clipped at zero from below.

## Run

Run both commands from the repository root:

```text
.venv/bin/python experiments/E-scheduled-curtailment/_corte.py
.venv/bin/python experiments/E-scheduled-curtailment/_experimento.py
```

The first command writes `data/interim/corte_programado.parquet`. The second reads that panel, fits the model, reports evaluation metrics and confidence intervals, and writes the test predictions.

## Panel and features

The target panel has one row per date and half-hourly step. It includes the target fraction, D-1 and D-7 curtailment, previous-day mean curtailment, mean curtailment over the previous 28 days, forecast generation for the step and day, daily peak forecast, relative forecast, step number, day of week, and month.

The model uses a chronological split: training rows before 2026-01-01 and test rows from that date onward. It is a `HistGradientBoostingRegressor` with fixed settings: 200 iterations, learning rate 0.05, 15 leaf nodes, L2 regularization 1, minimum leaf size 80, and random state 0. Predictions are clipped to `[0, 1]`.

## Controls and comparison

- D-1 and D-7 persistence are reported alongside step climatology.
- Skill and the day-block bootstrap interval use the better of the two persistence baselines; climatology is reported separately.
- The in-sample result (C5) distinguishes failure to learn from failure to generalize.
- C6 stratifies test rows by the previous 28-day mean curtailment. Tercile thresholds are estimated from the training set only.
- Confidence intervals use 2,000 day-block bootstrap replicates so adjacent half-hourly steps remain together.

The experiment is evaluated at the SIN aggregate. It does not require a plant crosswalk because forecast and scheduled values are on the same source row before aggregation.

## Outputs

| File | Description |
|---|---|
| `data/interim/corte_programado.parquet` | Aggregated scheduled-curtailment panel from `_corte.py` |
| `data/interim/f12_teste.parquet` | Test rows with target fraction, model prediction, and persistence baseline |

The output field names (`prev`, `prog`, `corte`, `frac`, `patamar`, and related keys) are retained as the experiment data contract.

## Limitations

- The experiment predicts the scheduling decision represented by forecast minus scheduled generation; it does not measure realized forecast error or plant-level constrained-off against verified generation.
- Results are aggregated to the SIN and do not establish plant- or subsystem-level performance.
- Model parameters are fixed in the script. This implementation does not run an internal hyperparameter search, despite the original C3 description referring to validation-based selection.
- The 28-day state feature and forecast inputs are treated as available when the next-day schedule is made; source publication-time validation is not implemented here.
