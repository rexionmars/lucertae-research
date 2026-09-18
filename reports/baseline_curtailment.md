# Baselines — solar curtailment forecasting (30 min, per cluster)

Produced by `uv run python -m terra_energy_research.baseline` on
`data/processed/curtailment_halfhour.parquet` (see `docs/dataset_curtailment.md`).
Full metrics, including validation, in `reports/baseline_metrics.csv`.

**Protocol.** Training Apr 2024–Aug 2025, validation Sep 2025–Feb 2026, test Mar–Aug 2026. The number
of trees is chosen on validation; for the test, the models and the climatology are refit on
training + validation. All models are evaluated **on the same rows**.

**Variable groups (cumulative)**

| group | what goes in | available the day ahead? |
|---|---|---|
| calendar + lags | hour, day of week, holiday, cluster attributes, curtailment on D-1/D-7 | yes |
| + system | scheduled load, wind and solar forecast, forecast net load (subsystem and SIN), verified D-1 values | yes |
| + plan | ONS day-ahead (D-1) plan: scheduled curtailment of the cluster and the system, scheduled hydro and thermal | yes |
| + oracle | verified load, wind, irradiance and reference at the same instant | **no** (ceiling) |

## Test: Mar–Aug 2026

**Classification: will there be curtailment?** (n = 402,960)

| model | AUC | average precision | Brier ↓ |
|---|---|---|---|
| D-1 persistence | 0.835 | 0.774 | 0.165 |
| climatology (cluster × hour × day of week) | 0.916 | 0.898 | 0.136 |
| LightGBM calendar + lags | 0.938 | 0.931 | 0.104 |
| LightGBM + system | 0.941 | 0.934 | 0.102 |
| **LightGBM + plan** | **0.944** | **0.939** | **0.100** |
| LightGBM + oracle | 0.947 | 0.943 | 0.098 |

**Regression: curtailed fraction of the reference** (n = 290,225; actual curtailment 6,555 GWh)

| model | MAE fraction ↓ | MAE MW ↓ | forecast curtailed energy |
|---|---|---|---|
| D-1 persistence | 0.203 | 37.0 | 6,443 GWh |
| climatology | 0.192 | 33.1 | 4,401 GWh |
| LightGBM calendar + lags | 0.165 | 28.0 | 5,959 GWh (−9%) |
| LightGBM + system | 0.158 | 27.0 | 6,278 GWh (−4%) |
| **LightGBM + plan** | **0.154** | **25.9** | 6,072 GWh (−7%) |
| LightGBM + oracle | 0.142 | 24.5 | 6,366 GWh (−3%) |

**The ONS D-1 plan as a predictor** (only clusters with a linked plan, n ≈ 300 thousand)

| model | AUC | MAE fraction | MAE MW | forecast energy (actual: 6,540 GWh) |
|---|---|---|---|---|
| ONS D-1 plan (scheduled curtailment fraction) | 0.787 | 0.164 | 28.4 | 3,887 GWh (−41%) |
| LightGBM + plan | 0.904 | 0.155 | 26.2 | 6,065 GWh (−7%) |

## Reading

- **On the test, each group of ex-ante variables reduced the error in both tasks.** From the model with
  calendar only to the model with system and plan, MAE fell from 28.0 to 25.9 MW (−7.4%) and Brier from
  0.104 to 0.100. On validation, the ordering repeated for Brier and MAE, but not for average precision
  (0.938 with system, 0.937 with plan). Each model was trained only once, with no uncertainty
  estimate. The ceiling with verified values (oracle) was 24.5 MW.
- **Variables with the highest gain** (+plan): in classification, curtailment on D-1 (34% of the gain) and the
  **share of SIN load met by forecast wind and solar** (19%). In regression, curtailed fraction
  on D-1 (24%), planned solar curtailment in the subsystem (17%) and planned curtailment of the cluster itself (12%).
  Gain measures the model's use of the variable, not the variable's effect on curtailment.
- **The ONS plan alone discriminates occurrence but underestimates magnitude**: AUC 0.79 and 41% less
  curtailed energy than realized. With the plan as a variable, LightGBM reduced the bias to −7%.
- All LightGBM models **underestimated** curtailed energy on the test (−3% to −9%); climatology
  underestimated it by 33% and D-1 persistence by 2%. One possible explanation is the growth in curtailment: from Mar to
  Aug, curtailed energy went from 5.42 TWh in 2025 to 6.90 TWh in 2026 (+27%).

## Next steps

Steps 1, 2 and 4 and the verified D-1 interchange (step 3) were tested in `reports/experiments_curtailment.md`.

1. Monthly *walk-forward* validation (retraining every month), closer to operation.
2. Actual weather forecasts instead of verified irradiance (ERA5 for the history; GFS/ECMWF or
   GraphCast in operation).
3. Interchange between subsystems and transmission limits (CNF/REL curtailment) as variables.
4. Two-stage model (probability × magnitude) and probability calibration.
