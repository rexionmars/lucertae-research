# Dataset: curtailment by cluster × 30 min (solar and wind)

Files: `data/processed/curtailment_halfhour.parquet` (solar) and
`curtailment_wind_halfhour.parquet` (wind), built by
`uv run python -m terra_energy_research.dataset [--tech wind]` from the `clean` layer.

Differences in the wind version: it uses `clean.wind_curtail`, covers all 24 hours (the solar one runs from
05:00 to 19:30), has no irradiance or per-plant aggregates (`poa_mean`, `n_plants`, `oracle_poa_mean`), and
the cluster weather variables are wind (`wx{1,2}_wind_speed`) instead of irradiance.

## Grain and coverage

- One row = one ONS photovoltaic cluster (`id_ons`) at one 30 min instant.
- Only from 05:00 to 19:30. Outside this window there is no generation and no curtailment.
- Period: Apr 2024 – Aug 2026. Clusters enter over time (57 → 83).

## Time split (`split`)

| split | period |
|---|---|
| train | 2024-04-01 – 2025-08-31 |
| valid | 2025-09-01 – 2026-02-28 |
| test  | 2026-03-01 – 2026-08-31 |

Use `valid` for *early stopping* and hyperparameter choice; use `test` only for the final number.

## Targets

| column | definition |
|---|---|
| `y_is_curtailed` | 1 if the ONS recorded a curtailment reason in the interval |
| `y_curtailed_mw` | `reference − generation` (≥ 0) when there is a reason; 0 without a reason; null if the reference is invalid |
| `y_curtailed_frac` | `y_curtailed_mw / reference`, in [0, 1]; null when the reference is invalid or < 1 MW |

Invalid reference: `reference = 0` with generation > 1 MW (≈ 96 thousand rows, concentrated in 2024).

## Variables

**Static** — `id_ons`, `uf`, `subsystem` (corrected via `ons_unit`), `lon`/`lat` of the connection
point, `conn_voltage_kv` (from the ONS connection code; if missing, the nearest substation),
`capacity_mw_est` (ONS capacity; for the 4 clusters without a register entry, p99 of the reference).

**Calendar** — `hour` (fractional), `dow` (0 = Monday), `month`, `doy`, `is_weekend`,
`is_holiday` (national holidays), `trend_days`.

**Lags (ex-ante)** — assumption: the forecast for day D is issued after D-1 closes.
- `lag1d_*`, `lag7d_*`: the same cluster and time of day on D-1 and D-7.
- `lag1d_sys_share_curtailed`, `lag1d_sys_curtailed_frac`: share of clusters with curtailment and system
  curtailed fraction at the same time of day on D-1.
- `roll7d_curtailed_frac`, `sys_roll7d_curtailed_frac`: daily curtailed fraction, mean from D-7 to D-1.

**Oracle (ex-post)** — values for the same instant that are only known after the fact. They are here
as stand-ins for weather and generation forecasts. With them, performance is a **ceiling**, not
what would be obtained in operation.
- `oracle_poa_mean`: mean irradiance of the cluster's plants (already cleaned).
- `oracle_reference_cf`: reference / capacity.
- `oracle_sys_reference_mw`, `oracle_sub_reference_mw`: sum of the reference over the system and over the subsystem.

**System (ex-ante, published the day ahead)** — from `clean.system_halfhour`, for the cluster's
subsystem (`sub_`) and for the SIN (`sin_`):
- `*_load_programmed`: scheduled load (ONS load API).
- `*_wind_forecast`, `*_solar_forecast`: centralized wind and solar forecast of the schedule units.
- `*_solar_distributed_programmed`: scheduled distributed solar (MMGD, Type III).
- `*_net_load_forecast`: load − wind − centralized solar − distributed solar.
- `*_vre_share_forecast`: share of load met by forecast wind and solar.
- `lag1d_sub_*`, `lag1d_sin_*`: verified load, wind, net load and **CMO** at the same time of day on D-1
  (also on D-2, with the prefix `lag2d_`).
- `lag1d_sin_cmo`, `lag1d_sin_cmo_daymin`, `lag1d_sin_cmo_floor_share`: SIN marginal operating cost on
  D-1 — level, daily minimum and share of intervals at the floor (≤ 20 R$/MWh), an indicator of
  oversupply. Used only lagged because the publication date of the consolidated version is not guaranteed.

**ONS D-1 plan (ex-ante, but already embeds the curtailment decision)** — `programacao_x_previsao`:
- `plan_forecast_mw`, `plan_programmed_mw`, `plan_cut_mw`, `plan_cut_frac`: forecast, scheduled and
  planned curtailment of the cluster itself. They exist only for clusters linked to a PDP code
  (`br.program_unit`) and from Oct 2024 onward.
- `plan_sub_*`, `plan_sin_*`: planned curtailment fraction for wind and solar, and scheduled hydro and thermal generation.

**System oracle (ex-post)** — `oracle_sub_*`, `oracle_sin_*`: verified load, wind and net load
at the same instant.

**Literature (ex-ante)** — `add_literature_features`; see `reports/literature_curtailment.md`:
- `plan_day_cut_frac`, `plan_day_sin_vre_cut_frac`: planned curtailment over the whole day (9:00–15:00), for the cluster and the SIN.
- `lit_sin_mmgd_share`: scheduled MMGD / scheduled load.
- `lit_ne_net_load_forecast`, `lit_se_net_load_forecast`, `lit_ne_vre_forecast`: forecast net load and renewables by region.
- `lit_sin_net_load_ramp_1h`, `lit_sin_net_load_daymin`, `lit_sin_net_load_above_daymin`: daily shape of the net load.
- `lag1d_sin_load_forecast_error`: relative error of the scheduled load on D-1.
- `lag1d_{n,ne,s,se}_{ena_pct_mlt,ear_pct}`, `lag1d_flow_{ne_se,n_se,n_ne,se_s}`: D-1 hydrology and interchange.
  **They worsened classification** in the experiments. One possible explanation, not tested: they are too
  seasonal for ~2 years of data and act as a date marker.

**Archived weather forecast (ex-ante)** — `add_weather`; ECMWF IFS 0.25° via the Open-Meteo
Previous Runs API (`terra_energy_research.weather`). `wx1_*` comes from the run issued 24h before the
valid time and `wx2_*` from the one issued 48h before. Hourly values are repeated in both 30 min intervals.
- `wx{1,2}_ghi`, `wx{1,2}_cloud`: global horizontal irradiance (W/m²) and cloud cover (%) in the cluster's cell.
- `wx{1,2}_sin_solar_ghi`: mean irradiance of the solar clusters, weighted by capacity.
- `wx{1,2}_ne_wind_speed`, `wx{1,2}_ne_wind_cf`: wind at 100 m at the NE wind farms, weighted
  by capacity, and capacity factor approximated with a generic power curve (3–12–25 m/s).

**Two days ahead (D+2) horizon** — information available at the end of D-2: `lag2d_is_curtailed`, `lag2d_curtailed_frac`,
`lag2d_sys_*`, `roll7d_d2_curtailed_frac`, `sys_roll7d_d2_curtailed_frac`,
`lag2d_{sub,sin}_{load,wind,net_load}_verified` and `wx2_*`. Do not use `plan_*`, scheduled `sub_*`/`sin_*`
or `lag1d_*`: they are published later.

**Support columns (do not use as variables)** — `generation`, `availability`, `reference`,
`reason_code`, `origin_code`, `is_curtailed`, `reference_valid`, `curtailed_mw`, `n_plants`,
`n_poa_valid`, `poa_mean`, `gen_estimated_mw`, `capacity_mw`, `nearest_substation_kv`,
`cluster_key`. All of them leak the target or duplicate variables.

## Known limitations

- The daily schedule and forecast vs. scheduled data exist only from **Oct 2024**; before that, the
  forecast `sub_*`/`sin_*` variables and `plan_*` are null (the scheduled load exists since Apr 2024).
  3 files are missing from the portal (2025-02-14 and 2025-03-26). Up to Sep 2024, the models with the plan train
  with these variables null; the gain attributed to the plan is estimated mostly from data from Oct 2024 onward.
- The schedule files may have been **revised by the ONS after publication**. The downloaded
  history is not guaranteed to be the version that existed on D-1. If there were revisions, the metrics of the
  models with `plan_*` may be optimistic relative to operation.
- On some days `programacao_diaria` comes with zero scheduled generation for all Type I/II
  renewables; the per-unit forecasts come from `programacao_x_previsao` and are not affected.
- The oracle variables use measured values. In operation they would be forecasts (NWP or AI models).
  For this reason, the results with oracle are a ceiling and do not estimate operational performance.
- **The assumption that verified D-1 data are available when the forecast is issued was not
  verified.** Verified curtailment, load and CMO are published by the ONS with a lag that was not
  measured. If it exceeds one day, the metrics of the models with `lag1d_*` (the variable with the highest
  gain in the baseline) are optimistic, and the lags need to be shifted to `lag{n}d_*`.
- `cluster_key` changes spelling over time for the same `id_ons`. The join with
  `cluster_halfhour` uses the key of the instant itself, so it is correct, but aggregations by
  `cluster_key` need to take this into account.
- 4 clusters (Juazeiro Solar 1 and 2, São Gonçalo and São Gonçalo A) have no `cluster_key` and no register entry:
  they have no irradiance and no coordinates. In the forecasts for these clusters, the model does not use
  location or irradiance.
- `oracle_poa_mean` is null in ~12% of rows. Part of this comes from the conservative rule in
  `clean.pv_detail_day_flag`: when the sensor appears filled at night (≥ 4 intervals > 20 W/m²),
  the plant's entire day is discarded (~12.6 thousand plant-days, 3%). To use the daytime period
  of these days, it is enough to remove `f.stuck_poa` from the `stuck_day` rule in `sql/10_clean.sql`. The limitation
  affects only the oracle irradiance variables, and therefore only the ceiling.
