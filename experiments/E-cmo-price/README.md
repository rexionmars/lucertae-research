# E-cmo-price

Can next-day marginal operating cost be forecast from system state, or is
repeating the previous day already the strongest available baseline?

**At one day ahead the model ties; at two days it gains.** Against the seasonal
naive baseline used in price forecasting, the best model has +0.76% MAE skill
(95% CI [-6.72%, +7.70%]), which is not distinguishable from zero, and +16.2%
RMSE skill. When the target is shifted to D+1 and the information gate moves
with it, skill reaches +16.31% (95% CI [+10.64%, +21.87%]). The naive baseline
uses the most recent realized price and predicts the CMO floor exactly. That
advantage holds one day ahead but not two.

This experiment addresses task family 11, price and marginal operating cost,
in the [energy task and data-source report](../../docs/product/data_taks.tex).
It uses `data/raw/cmo/`, a source that was on disk but had not yet been read by
code.

```text
.venv/bin/python experiments/E-cmo-price/1_painel.py
.venv/bin/python experiments/E-cmo-price/2_controles.py   # blocks step 3
.venv/bin/python experiments/E-cmo-price/3_modelos.py
.venv/bin/python experiments/E-cmo-price/4_decomposicao.py
.venv/bin/python experiments/E-cmo-price/5_ablacao.py
```

Outputs are written to `data/interim/E-cmo-price/` (overridable with
`LUCERTAE_INTERIM`).

| Script | Purpose | Output |
|---|---|---|
| `1_painel.py` | Subsystem-by-half-hour panel with 40 numeric features within the information gate | `painel.parquet`, `janelas.json` |
| `2_controles.py` | Six blocking controls | `controles.json` |
| `3_modelos.py` | Four baselines, three models, and one oracle; rolling origin with monthly recalibration | `previsoes.parquet`, `resultado.json` |
| `4_decomposicao.py` | Error quantiles, behavior at the floor, daily level versus intraday shape | `decomposicao.json` |
| `5_ablacao.py` | Feature-family ablation, permutation null, and horizon control | `ablacao.json` |

## Input

ONS half-hourly CMO: three annual files, **184,704 records**, four subsystems
by 46,176 half-hours, from 2024-01-01 to 2026-08-27, with no missing values.
Covariates are hourly load, hourly national interchange, and daily EAR and ENA
by subsystem.

Two target properties determine the design:

- **Mass at the floor.** 20.5% of half-hours have CMO <= 1 R$/MWh, indicating
  zero marginal cost and excess supply. The observed minimum is -39.24.
- **Heavy tail.** The maximum is 4,870.95 R$/MWh, and the p99 ranges from 614
  to 1,082 across subsystems.

**Eight full CMO days are missing** from the window. They remain absent from
the grid, are counted, and are never interpolated: interpolation would invent
targets the operator did not publish.

**Each gap removes three panel days.** In addition to the missing day, the next
day loses D-1 persistence, and the day seven days later loses D-7 persistence.
The 8 gaps remove **24 panel days**, plus the first 7 days of the series, which
have no D-7. In total, 1,536 rows without targets and 4,416 rows without a
baseline are excluded from the complete grid of 186,240 rows.

## Information gate

The forecast is issued at 12:00 on D-1 for all 48 half-hours of day D.
Availability at issue time was measured source by source from the last record
in each file and its modification time:

| Source | Downloaded | Last record | Lag |
|---|---|---|---:|
| Half-hourly CMO | 2026-08-27 10:08 | 2026-08-27 23:30 | **-0.6 days** |
| Load curve | 2026-09-02 04:25 | 2026-08-31 23:00 | 1.2 days |
| Interchange | 2026-09-02 04:44 | 2026-08-31 23:00 | 1.2 days |
| Daily EAR | 2026-09-02 04:25 | 2026-08-31 | 2.2 days |
| Daily ENA | 2026-09-06 11:22 | 2026-09-04 | 2.3 days |

**CMO is published in advance.** The file downloaded at 10:08 on August 27
already contained all 48 half-hours for that day. It is dispatch-model output,
not an ex-post measurement. This does not make the task tautological: at 12:00
on D-1, the operator's value for D has not yet been published. The information
gate is:

```text
CMO ................ through the end of D-1
load, interchange .. through the end of D-2
EAR, ENA ............ through D-3
calendar for D ...... deterministic and available
```

The same gate applies to the models and baselines. Giving the naive baseline
D-1 information while limiting the model to D-2 would bias the comparison
against the model.

Each lag is **one observation per source**, a stated limitation: ONS files do
not include publication timestamps, and file modification time is the only
evidence available on disk.

## Design

**Estimand.** CMO in R$/MWh for each half-hour on day D across four subsystems.

**Baseline.** The canonical seasonal naive baseline in the price-forecasting
literature: Tuesday through Friday repeat D-1; Saturday, Sunday, and Monday
repeat D-7. This is not simple persistence. In price series, the previous day
already carries the level and intraday shape that a model must improve upon.

**Loss.** MAE, selected before looking at the results for two reasons reported
in the literature: it supports comparisons across price studies, and the CMO
tail would make RMSE focus on a handful of hours. RMSE is secondary.

**Monthly recalibration with an expanding window.** The model is refit on the
first day of each test month using all available history. There are 15
recalibrations. Without them, one fit would span 14 months while the naive
baseline updates every day, favoring the baseline by design.

**Three models on the same inputs.** `direto` predicts the price level;
`residual` predicts a correction to the naive baseline; `duas_partes` classifies
whether a half-hour is at the floor and regresses the remaining values, using
the decision rule that minimizes MAE under this model.

**Day-block confidence intervals.** The 2,000 bootstrap replicates keep all four
subsystems together in each daily block. Half-hours within a day have
correlated errors; resampling individual rows would produce an overly narrow
interval.

## Controls

Controls run before results are produced; a failure blocks step 3.

| Control | Result |
|---|---|
| C1: grid, unique key, missing days remain absent | 0 duplicates, 0 incomplete days, 24 missing days; pass |
| C2: CMO within physical range and target has no missing values | 0 out of range; min -39.24, max 4,870.95; pass |
| C3: **information gate**, rebuild features with sources masked at issue time | 40 sampled days, 307,200 cells, 0 mismatches; pass |
| C4: feature coverage >= 97% | minimum 99.15% (`cmo_l2`); pass |
| C5: baseline ranking, D-1 beats climatology and seasonal naive beats D-7 | 43.93 < 136.40 and 42.47 <= 61.75; pass |
| C6: four subsystems are distinct series | maximum correlation 0.933; pass |

**C1 failed once** when the threshold was set to 8, the number of missing source
days. The panel loses 24 days, as described above. The threshold is fixed at
24 rather than calculated from the source: if a source change alters the count,
the control fails and requires investigation instead of silently absorbing the
change.

**C3 tests the design, not the source data.** It masks all source values after
the issue time, rebuilds features for sampled days with the same function used
in step 1, and requires cell-by-cell equality. A single feature using future
information fails the control.

### Positive control and its correction

The level oracle receives the true median daily residual and shifts the naive
baseline by it. The first version used the **mean** and showed only **+0.9%**
skill, with a confidence interval crossing zero. The design would then appear
unable to detect gains, making negative model results uninformative.

This was a statistical issue, not a data issue: MAE is the declared loss, and
the median minimizes MAE. Replacing the mean with the median on the same days
and data raises oracle skill to **+17.66%**, with a 95% CI of [+15.28%, +20.21%].
The same rule is used in `E-thermal-dispatch`, where it is applied to a baseline
rather than an oracle.

## Result A: no model is distinguishable from the seasonal naive in MAE

Test period: 2025-06-01 to 2026-08-27, **85,248 rows, 444 days, 15
recalibrations, 41 features**.

| Predictor | MAE | RMSE | MAE skill | 95% CI |
|---|---:|---:|---:|---|
| D-1 naive | 52.70 | 129.33 | -7.36% | [-14.08%, -1.16%] |
| D-7 naive | 69.82 | 140.19 | -42.24% | [-53.71%, -32.04%] |
| **Seasonal naive** | **49.09** | **122.02** | baseline | |
| Half-hour climatology | 125.18 | 162.89 | -155.02% | [-176.41%, -136.05%] |
| LightGBM direct | 51.32 | 103.38 | -4.54% | [-12.39%, +2.74%] |
| LightGBM residual | 50.04 | 115.42 | -1.94% | [-6.50%, +2.26%] |
| **LightGBM two-part** | **48.71** | **102.31** | **+0.76%** | [-6.72%, +7.70%] |
| Level oracle | 40.42 | 112.69 | +17.66% | [+15.28%, +20.21%] |

**All three models have MAE confidence intervals that cross zero; none is
distinguishable from repeating the previous day.** The best model ties at
+0.76%, with an interval 14 percentage points wide.

**In RMSE, the same models beat the naive baseline:** +16.2% for the two-part
model and +15.3% for the direct model. This difference between metrics is not
noise; step 4 shows where it comes from.

The positive control passes: the oracle's confidence interval is entirely above
zero. The experiment detects a gain when one is present, so the tie above is a
measured result rather than a limitation of the design.

## Result B: the naive baseline wins at the floor and loses in the tail

The CMO is at the floor in 14.0% of test-period half-hours.

| Predictor | Predicts floor when target is at floor | Median error there | Median error outside |
|---|---:|---:|---:|
| Seasonal naive | **71.6%** | 0.00 | 15.10 |
| LightGBM direct | 19.2% | 16.65 | 22.86 |
| LightGBM residual | 18.6% | 13.06 | 19.48 |
| LightGBM two-part | **66.0%** | 0.01 | 22.03 |

**The naive baseline uses the most recent realized value, so it predicts the
floor exactly.** A single regressor returns the conditional median, which
rarely lands exactly on zero, and incurs 13 to 17 R$/MWh median error on 14% of
rows. Explicitly modeling the floor recovers that behavior and moves skill from
-4.54% to +0.76%.

Absolute-error quantiles on the same test set:

| Predictor | q25 | q50 | q90 | q95 |
|---|---:|---:|---:|---:|
| Seasonal naive | **2.25** | **12.10** | 157.62 | 222.46 |
| LightGBM direct | 7.73 | 22.06 | 136.53 | 179.90 |
| LightGBM two-part | 5.13 | 19.78 | **131.75** | **184.86** |

**The trade-off is consistent:** the naive baseline has lower error on easy rows
and higher error on difficult rows. The two-part model has lower error than
the baseline on only **40.7%** of rows and still has 16.2% lower RMSE. MAE
weights all rows equally and selects the naive baseline; RMSE emphasizes the
tail and selects the model. **Choosing the loss determines the winner, so
choosing it after seeing results would amount to choosing the result.**

### Daily level and intraday shape

Separate CMO into the daily level and each half-hour's deviation from that
level:

| Predictor | Overall | Level | Shape |
|---|---:|---:|---:|
| Seasonal naive | 49.09 | 40.21 | 48.64 |
| LightGBM direct | 51.32 | 37.80 | 42.45 |
| LightGBM two-part | **48.71** | **35.52** | **42.65** |
| Level oracle | 40.42 | 23.57 | 48.64 |

**The models beat the naive baseline on each component measured separately and
tie on the total.** There is no inconsistency: row error is the sum of level
and shape errors, and |a+b| is not |a|+|b|. MAE is not additive over this
decomposition.

## Result C: the naive baseline is only unbeatable at one day

The same design is run with the target shifted to D+1 and the entire information
gate shifted with it. As a control, both errors should increase.

| Horizon | Model MAE | Naive MAE | Skill | 95% CI |
|---|---:|---:|---:|---|
| D | 48.71 | 49.09 | +0.76% | [-6.72%, +7.70%] |
| D+1 | 62.68 | 74.89 | **+16.31%** | **[+10.64%, +21.87%]** |

The control passes because both errors increase, and it also provides a result:
**the naive baseline degrades much faster than the model.** Its MAE increases
by 25.80 R$/MWh from one day to two; the model's increases by 13.96. At two
days, the model wins with a confidence interval entirely above zero.

This is the same pattern as Result B from another perspective. The naive
baseline's main advantage is the latest realized value, and that value loses
predictive value quickly with horizon. System-state covariates decay more
slowly because hydrological and load conditions change on a weekly scale.

## Result C2: the ablation does not identify the source of skill

Nested feature sets use the same rolling-origin design and monthly
recalibration:

| Set | Features | Skill |
|---|---:|---:|
| A0: calendar + own-subsystem CMO | 20 | -4.87% |
| A1: + CMO from other subsystems | 28 | -1.01% |
| A2: + load and interchange | 36 | -9.50% |
| A3: + hydrology (full set) | 41 | +0.76% |

**The increments are not interpretable, and the reason was measured.** With
`colsample_bytree` below 1, LightGBM samples columns by position; permuting
the same columns acts like changing the seed. The first ablation concatenated
feature families in the order they were added and produced a different result
for the same feature set:

| Set | Ablation order | Canonical order | Difference |
|---|---:|---:|---:|
| A0 | -3.66% | -4.87% | 1.21 points |
| A1 | -1.84% | -1.01% | 0.83 points |
| A2 | -2.69% | -9.50% | **6.81 points** |
| A3 | +4.40% | **+0.76%** | 3.64 points |

Canonical ordering reproduces step 3 exactly for A3 (+0.76% in both runs),
which identifies column order, not a different implementation, as the cause.

**Differences between adjacent sets (3.86, -8.49, and 10.26 points) are on the
same scale as variation induced solely by column permutation (0.83 to 6.81
points).** With one seed and one parameter configuration, the ablation mixes
fitting variance with family effects. This does not invalidate Result A: all
sets fall within the 14-point interval reported in step 3. It does mean that
**the current number of seeds does not support a claim about which source
contributes the skill.**

### Permutation null

Shuffling training features across rows while keeping the target intact yields
**-206.91%** skill, worse than climatology. The feature-target association
supports prediction; without it, the model becomes a constant predictor.

## Result D: skill is not stable over time or space

Two-part model skill over the seasonal naive baseline by subsystem:

| Subsystem | Naive MAE | Model MAE | Skill |
|---|---:|---:|---:|
| N | 50.91 | 52.27 | -2.68% |
| NE | 51.90 | 51.44 | +0.89% |
| S | 47.53 | 45.82 | **+3.61%** |
| SE | 46.02 | 45.33 | +1.49% |

By test month, skill ranges from **-68.2%** (Dec 2025) to **+38.7%** (Jan
2026) and is positive in **10 of 15 months**. Two poor months drive the
aggregate: removing December 2025 and March 2026 would change its sign. This
dispersion, rather than the central estimate, produces the 14-point-wide
interval in Result A.

The conservative interpretation remains that of Result A: over 15 test
months, **mean MAE skill is not distinguishable from zero**. Monthly
instability is too large for a majority of positive months to support a
stronger claim.

## Stated limitations

- **Publication lag is one observation per source.** ONS files have no
  publication timestamp; file modification time is the only available
  evidence. The entire gate rests on five observations.
- **CMO is model output, not a measurement.** It is produced by the operator's
  dispatch model. There is no independent source for comparison, and no
  control here tests whether published CMO equals realized marginal cost.
- **No holiday calendar.** The repository has no national or regional holiday
  table. Holiday effects are included in both model and baseline error, and the
  seasonal naive baseline is particularly affected.
- **No settlement price.** CMO is not PLD. CCEE, which publishes PLD, returned
  HTTP 403 through three separate routes, as measured on 2026-09-06 and
  documented in `docs/product/data_taks.tex`. These results make no claim about
  settlement prices.
- **One parameter configuration and one seed.** The confidence interval covers
  test-day variation, not fitting variance, seed variance, or train/test cutoff
  variation. Result C2 gives a partial estimate: column order alone moves skill
  by 0.83 to 6.81 points, enough to obscure differences between feature sets.
- **Subsystem-level resolution.** ONS does not publish nodal CMO. The direct
  comparison in the literature (`maji2025`, ERCOT node by node) cannot be
  reproduced with these data; the comparison target is unavailable, not an
  outstanding validation task.

## Not tested

- Daily or weekly rather than monthly recalibration. Price-forecasting
  literature motivates daily updates; 15 refits took 864 seconds, while 444
  would take about 7 hours.
- A rolling rather than expanding training window. The two months with severe
  model degradation (Dec 2025 and Mar 2026) suggest regime change, which a
  shorter window might handle better; this was not measured.
- Separate models by subsystem rather than one global model with subsystem as
  a category.
- More than one seed. This is required for the ablation: with one seed, Result
  C2 mixes fitting noise with feature-family effects.
- Horizons beyond D+1. Skill increases from +0.76% to +16.31% between one and
  two days; the later behavior is unknown.
- Density or quantile forecasts. The floor and tail motivate them; Result B
  shows that no single point forecast serves both regions.
- `cvu-usitermica`, which defines merit order and is the input closest to the
  mechanism that forms CMO. Measured on 2026-09-06: 22 files, 9.8 MB, HTTP 200.
  It is not in the panel because it is not on disk, not because it is
  unavailable.