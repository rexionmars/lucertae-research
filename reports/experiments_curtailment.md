# Experiments: improvements motivated by the literature

Hypotheses and references in `reports/literature_curtailment.md`. Code in
`src/terra_energy_research/experiments.py`; raw numbers in `reports/experiments_*.csv`.

**Terms.** A *curtailment event* is an interval of 30 min with a curtailment reason recorded by the ONS.
*Curtailment* as a quantity is the power (MW) or energy (GWh) that was not generated. *MAE MW* is the mean
absolute error of the forecast curtailment per interval. *Energy bias* is the forecast curtailed energy divided
by the realized curtailed energy, minus 1.

## Protocol

1. **Selection, without touching the test set.** Training Apr 2024–Jun 2025, early stopping on Jul–Aug 2025,
   comparison on validation (Sep 2025–Feb 2026). Nine configurations in the first round; the later
   rounds (weather, CMO, wind) added configurations under the same protocol.
2. **Test** (Mar–Aug 2026) only for the configurations chosen on validation. Early stopping on
   validation and retraining on training + validation, as in `baseline.py`.
3. **Monthly retraining (walk-forward)** on the test: for each month, training on the entire prior history,
   with the number of trees fixed in step 2.

The regression metrics use all rows with a defined fraction. For this reason the absolute numbers differ
slightly from `baseline_curtailment.md`, which evaluates on the subset shared with the climatology.

**Protocol limitations.**
- **The test set was consulted in several rounds** (sections 2 to 5). Each configuration was chosen
  on validation, but the decision to open a new round took the earlier test results into account.
  The test numbers in sections 3 to 5 are therefore less independent than those in section 2.
- **Each configuration was trained only once**, with the LightGBM default seed (`LGB_PARAMS` does not
  set `seed`). There is no estimate of variation across seeds or across months, and no significance
  test was run. Differences of 1–2% between configurations do not, on their own, support the claim that one
  is better than the other.

## 1. Selection (validation: Sep 2025–Feb 2026)

| configuration | variables | model | AUC | Brier ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|---|---|
| base | calendar + system + plan | direct | **0.944** | 0.111 | 20.7 | −14% |
| lit | base + all literature variables | direct | 0.942 | 0.118 | 20.6 | −18% |
| hurdle | lit | two-stage | 0.942 | 0.118 | 20.4 | −17% |
| recency | lit | direct, recency weighting | 0.943 | 0.113 | 20.3 | −14% |
| l1 | lit | L1 loss (median) | 0.942 | 0.118 | **20.2** | −26% |
| base_recency | base | direct, recency | 0.943 | 0.112 | 21.1 | −14% |
| **core** | base + H1, H2, H4 (without hydrology and interchange) | direct | 0.944 | **0.110** | 20.4 | −16% |
| **core_recency** | core | direct, recency | 0.943 | **0.110** | 20.4 | −14% |
| core_recency_hurdle | core | two-stage, recency | 0.943 | 0.110 | 20.5 | −16% |

**What the selection showed**
- **H1 + H2 + H4 (MMGD, NE, net load shape, whole-day plan)** reduced the error slightly, but
  in both tasks: Brier from 0.111 to 0.110 and MAE from 20.7 to 20.4 MW.
- **H3 (D-1 hydrology and interchange) worsened classification** (Brier 0.118). One possible
  explanation: these variables are highly seasonal and, with less than two years of data, act as a
  date marker; the model associates their values with the 2024–25 period. The explanation was not tested.
- **The two-stage model (H5) did not reduce the error** relative to direct regression with a
  cross-entropy loss.
- **The L1 loss** reduced MAE but underestimated energy by 26%. Discarded for energy use.
- **In all configurations, the model underestimated curtailment by 14–26%** on validation (14–18% without the
  L1 loss). Curtailment grew over the period, and the training set does not contain the most recent levels.

## 2. Test (Mar–Aug 2026)

| configuration | training | AUC | average precision | Brier ↓ | MAE fraction ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|---|---|---|
| base | single (training + validation) | 0.944 | 0.938 | 0.100 | 0.151 | 24.7 | −6.9% |
| core | single | 0.943 | 0.938 | 0.102 | 0.150 | 24.6 | −5.8% |
| core_recency | single | 0.944 | 0.938 | 0.100 | 0.150 | 24.8 | −5.1% |
| base | **monthly retraining** | 0.943 | 0.936 | **0.098** | 0.149 | 24.4 | −4.8% |
| core | monthly retraining | 0.943 | 0.939 | 0.099 | 0.149 | 24.3 | −4.0% |
| **core_recency** | **monthly retraining** | 0.943 | **0.939** | 0.099 | **0.146** | **24.1** | **−3.4%** |

**Reading**
- **Among the configurations in this section, core_recency with monthly retraining had the lowest MAE and the lowest
  bias.** Relative to base with single training, MAE fell 2.5% (24.7 to 24.1 MW), Brier fell 1.2% and the
  energy bias went from −6.9% to −3.4%.
- **The differences are small and have no estimated uncertainty** (see *Protocol limitations*). The
  most consistent result is the bias reduction with monthly retraining, observed in all three configurations.
- **Monthly retraining and recency weighting reduced the error more than the new variable groups.**
  This result is consistent with a regime that changes over the period, such as the growth in curtailment
  in 2026. The structural break described by Vieira et al. (August 2023 blackout) predates the data
  (Apr 2024) and is not tested here.
- **AUC stayed at ~0.94 in all configurations with day-ahead information**, and the ceiling with verified
  values (oracle) was 0.947 (`baseline_curtailment.md`). This result is consistent with a
  limit imposed by the available information rather than by the model: 43% of curtailment events are not in the D-1
  plan (`notebooks/02_system_drivers.ipynb`), which indicates decisions made after the daily schedule.

## 3. Archived weather forecast and two days ahead (D+2) horizon

Source: ECMWF IFS 0.25° via the Open-Meteo Previous Runs API (`weather.py`), with forecasts issued 24h
(`wx1_*`) and 48h (`wx2_*`) before the valid time, at the cells of the 87 solar clusters and the 153
wind farms. Timing checked against measured irradiance: correlation of 0.89 over the whole day,
with zero shift; between 9:00 and 15:00, 0.56, probably because cloud cover is difficult to forecast.

**D+2** = forecast issued at the end of D-2. No ONS plan, no scheduled load and no D-1 lags
(see `docs/dataset_curtailment.md`).

**Validation (Sep 2025–Feb 2026)**

| configuration | AUC | Brier ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|
| core_recency (day ahead) | 0.943 | 0.110 | 20.4 | −14% |
| core_recency_wx (day ahead) | **0.945** | **0.108** | 20.4 | −12% |
| d2_recency | 0.913 | 0.141 | 25.5 | −23% |
| d2_recency_wx | **0.930** | **0.135** | **23.6** | −18% |

**Test (Mar–Aug 2026)**

| configuration | training | AUC | average precision | Brier ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|---|---|
| core_recency | monthly retraining | 0.943 | 0.939 | 0.099 | **24.1** | **−3.4%** |
| core_recency_wx | monthly retraining | **0.945** | **0.940** | **0.097** | 24.2 | −4.9% |
| d2_recency | single | 0.927 | 0.917 | 0.115 | 28.3 | −13.6% |
| d2_recency_wx | single | 0.936 | 0.928 | 0.116 | 26.7 | −22.0% |
| d2_recency | monthly retraining | 0.930 | 0.917 | 0.109 | 27.8 | **−9.0%** |
| d2_recency_wx | monthly retraining | **0.938** | **0.930** | **0.107** | **26.0** | −15.7% |

**Reading**
- **Day ahead, the weather forecast added little.** Brier fell 2% and AUC rose by 0.002, but
  MAE did not fall and the bias went from −3.4% to −4.9%. One possible explanation is that the D-1 plan and the
  ONS wind and solar forecasts already contain this information.
- **At D+2, the weather forecast reduced the error:** AUC from 0.930 to 0.938 and MAE from 27.8 to
  26.0 MW (−6.5%). This reduction corresponds to 49% of the difference between D+2 without weather (27.8 MW) and
  the day-ahead model (24.1 MW).
- **At D+2, the energy underestimation increased** (−9.0% to −15.7%). The model with weather had a
  higher AUC but forecast smaller fractions. Section 4 tests the calibration of this bias.
- Monthly retraining reduced MAE in both D+2 configurations.

## 4. Bias calibration (monthly retraining, test)

With `walk --calibrate`, each test month is corrected using the previous 60 days
(`CALIB_WINDOW_DAYS`), forecast by a model that had not seen them: a multiplicative factor on the curtailed fraction,
shrunk halfway toward 1 (`CALIB_DAMPING`), and isotonic regression on the probability.

| configuration | calibration | AUC | average precision | Brier ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|---|---|
| core_recency | no | **0.943** | **0.939** | 0.099 | **24.1** | −3.4% |
| core_recency | yes | 0.941 | 0.934 | 0.099 | 24.3 | +3.5% |
| core_recency_wx | no | **0.945** | **0.940** | **0.097** | **24.2** | −4.9% |
| core_recency_wx | yes | 0.942 | 0.935 | 0.098 | 25.3 | +6.2% |
| d2_recency_wx | no | **0.938** | **0.930** | 0.107 | **26.0** | −15.7% |
| d2_recency_wx | yes | 0.933 | 0.923 | **0.105** | 26.3 | **−3.4%** |

**Reading**
- **Day ahead, calibration worsened all metrics** and reversed the sign of the bias (from −3.4% to
  +3.5% and from −4.9% to +6.2%). One possible explanation: the factor is estimated with a model that did not see the
  calibration window, but it is applied to a model retrained with that window, which has already corrected part of the bias.
- **At D+2, calibration reduced the bias from −15.7% to −3.4%**, with MAE 0.3 MW higher and AUC 0.005 lower.
- **AUC fell in all calibrated configurations.** Isotonic regression is monotonic, but not
  strictly: it groups probabilities into steps and creates ties.
- `model.py` applies calibration by default (`predict(..., calibrate=True)`) also to the day-ahead
  configurations, where it worsened the result on the test.

## 5. CMO and wind curtailment

**CMO** (SIN marginal operating cost on D-1: level, daily minimum and share of intervals at the floor)
was added to core_recency_wx. **Wind**: the same configurations, with forecast wind in place
of irradiance in the cluster variables (`reports/wind_curtailment.md`). The wind metrics are not
comparable to the solar ones: the base, the daily period and the curtailment rate differ.

**Validation (Sep 2025–Feb 2026)**

| configuration | AUC | Brier ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|
| core_recency_wx | 0.945 | 0.108 | 20.4 | −12% |
| core_recency_wx_cmo | 0.945 | 0.108 | 20.4 | −11% |
| wind_base | 0.942 | 0.109 | 13.9 | −29% |
| wind_core_recency | 0.945 | **0.103** | 13.7 | −31% |
| wind_core_recency_wx_cmo | **0.948** | 0.106 | **13.6** | −29% |
| wind_d2_recency_wx_cmo | 0.932 | 0.123 | 15.7 | −32% |

**Test (Mar–Aug 2026)**

| configuration | training | AUC | average precision | Brier ↓ | MAE fraction ↓ | MAE MW ↓ | energy bias |
|---|---|---|---|---|---|---|---|
| core_recency_wx_cmo | single | 0.945 | 0.940 | 0.100 | 0.149 | 24.6 | −6.9% |
| core_recency_wx_cmo | monthly retraining | 0.945 | 0.940 | 0.098 | 0.146 | 24.0 | −5.7% |
| wind_base | single | 0.927 | 0.904 | 0.106 | 0.132 | 11.9 | −13.8% |
| wind_base | monthly retraining | 0.928 | 0.905 | 0.104 | 0.132 | 11.8 | −11.7% |
| wind_core_recency_wx_cmo | single | 0.931 | 0.909 | 0.103 | 0.127 | 11.5 | −14.3% |
| wind_core_recency_wx_cmo | monthly retraining | **0.934** | **0.911** | **0.100** | **0.127** | **11.4** | **−11.3%** |
| wind_d2_recency_wx_cmo | single | 0.913 | 0.885 | 0.119 | 0.139 | 12.7 | −23.1% |
| wind_d2_recency_wx_cmo | monthly retraining | 0.917 | 0.891 | 0.114 | 0.138 | 12.5 | −19.8% |

**Reading**
- **Solar: with the CMO, validation AUC, Brier and MAE did not change at the reported precision**; the bias went
  from −12% to −11%. On the test, with
  monthly retraining, MAE was 24.0 MW, versus 24.1 (core_recency) and 24.2 MW (core_recency_wx), and the bias
  was −5.7%, versus −3.4% (core_recency). None of the differences has an estimated uncertainty.
- **Wind: wind_core_recency_wx_cmo had the highest AUC and the lowest MAE on validation, but not the lowest
  Brier** (0.106, versus 0.103 for wind_core_recency). wind_core_recency was not evaluated on the test.
- **On the test, wind underestimated energy by 11–23%**, more than solar, in all configurations.
- `model.py` uses core_recency_wx_cmo (solar) and wind_core_recency_wx_cmo (wind) as defaults. For
  solar, the results above do not distinguish this choice from core_recency.

## What was not tested and may reduce the error

1. **Intraday forecasts** (ONS rescheduling over the day): they contain information about part
   of the 43% of curtailment events absent from the D-1 plan, but they change the forecast horizon.
2. **Calibration estimated under the same retraining scheme** as the calibrated model, to avoid the double
   correction discussed in section 4.
3. **Scheduled interchange limits** (not verified) and published electrical constraints, instead
   of the verified D-1 flow.
4. **Probabilistic forecasting** (quantiles or conformal prediction) for users who use curtailment in risk decisions.
5. **Significance testing** by bootstrap over blocks of days and **variation across seeds**.
