# Corte por cluster (`lucertae.corte`)

Analysis and modeling of solar generation curtailment in the SIN (Brazilian National Interconnected
System), based on ONS open data loaded into the local PostGIS database `terra_br`.

## Structure

| path | contents |
|---|---|
| `sql/05_ons_system.sql` | raw ONS tables for load, energy balance and daily schedule (schema `br`) |
| `sql/10_clean.sql` | cleaning layer (`clean` schema) on top of the `br` schema; idempotent |
| `sql/20_clean_system.sql` | load, wind, net load and ONS day-ahead (D-1) plan by subsystem and by cluster |
| `src/lucertae/corte/ons.py` | download (S3 and the ONS load API) and loading of the system sources |
| `src/lucertae/corte/weather.py` | archived ECMWF forecasts (Open-Meteo) at the solar clusters and wind farms |
| `notebooks/01_eda_curtailment.ipynb` | exploratory analysis: evolution, reasons, hour × day, map, quality |
| `notebooks/02_system_drivers.ipynb` | net load vs. curtailment; ONS D-1 plan vs. realized curtailment |
| `reports/figures/` | notebook figures as PDF, SVG and PNG (style defined in `src/lucertae/corte/viz.py`) |
| `src/lucertae/corte/dataset.py` | builds the forecasting dataset (cluster × 30 min) as parquet |
| `src/lucertae/corte/baseline.py` | baselines: persistence, climatology and LightGBM |
| `src/lucertae/corte/experiments.py` | improvements from the literature: selection on validation, test and monthly retraining |
| `src/lucertae/corte/model.py` | trains on all data, saves to `models/` and produces forecasts |
| `src/lucertae/corte/viz.py` | matplotlib style shared by the notebooks |
| `reports/*.csv`, `reports/experiments_iterations.json` | raw metrics and the chosen number of trees (read by `model.py`) |
| `docs/postgis.md` | how to install and load the `terra_br` database (PostGIS), including the TERRA base tables |
| `docs/dataset_curtailment.md` | column dictionary, assumptions and limitations of the dataset |
| `reports/baseline_curtailment.md` | baseline results |
| `reports/literature_curtailment.md` | literature review and tested hypotheses |
| `reports/experiments_curtailment.md` | improvement experiments and recommended configuration |

## How to run

Prerequisite: the `terra_br` database with the base tables loaded by TERRA. See `docs/postgis.md`.

```sh
uv sync

# 1. clean layer (~12 min; most of it is clean.pv_detail_day_flag)
psql -h localhost -d terra_br -v ON_ERROR_STOP=1 -f sql/10_clean.sql

# 2. ONS system data: download (~400 MB in data/raw/ons) and load (~10 min), then views
uv run python -m lucertae.corte.ons download --start 2024-04-01 --end 2026-08-31
uv run python -m lucertae.corte.ons load --start 2024-04-01 --end 2026-08-31
psql -h localhost -d terra_br -v ON_ERROR_STOP=1 -f sql/20_clean_system.sql

# 2b. archived weather forecast: download (~11 min, ~110 MB in data/raw/openmeteo) and load (~5 min, ~1.2 GB in the database)
uv run python -m lucertae.corte.weather download
uv run python -m lucertae.corte.weather load

# 3. datasets -> data/processed/curtailment_{,wind_}halfhour.parquet (~1 and ~2 min)
uv run python -m lucertae.corte.dataset
uv run python -m lucertae.corte.dataset --tech wind

# 4. baselines -> reports/baseline_metrics.csv (~5 min)
uv run python -m lucertae.corte.baseline

# 5. experiments (selection ~10 min; test ~5 min; monthly retraining ~11 min)
uv run python -m lucertae.corte.experiments select
uv run python -m lucertae.corte.experiments final --configs base,core,core_recency
uv run python -m lucertae.corte.experiments walk --configs base,core,core_recency
uv run python -m lucertae.corte.experiments walk --calibrate --configs core_recency,d2_recency_wx
uv run python -m lucertae.corte.experiments select --data data/processed/curtailment_wind_halfhour.parquet --configs wind_base,wind_core_recency

# 6. final model -> models/{solar,wind}/ and forecasts in data/processed/predictions.parquet
uv run python -m lucertae.corte.model train --tech solar
uv run python -m lucertae.corte.model predict --tech solar --start 2026-08-01 --end 2026-08-31

# 7. notebooks
uv run jupyter lab notebooks/
```

The connection uses `DATABASE_URL`, or `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE`. The default is
`localhost:5432/terra_br` with the system user.

## Schema `clean`

| object | type | what it does |
|---|---|---|
| `clean.plant` | view | ANEEL plant register: sentinel date 1900-01-03, capacity ≤ 0 and geometry outside Brazil become NULL |
| `clean.transmission_line` | view | `length_ratio` and `length_flag` (published < straight line, > 3×, missing) |
| `clean.pv_curtail` | view | corrected subsystem, `reference_valid`, `curtailed_mw` (only with a reason and a valid reference) |
| `clean.pv_detail_day_flag` | mat. view | per plant × day: stuck/flattened irradiance, flattened or nighttime generation |
| `clean.pv_detail` | view | irradiance and generation with impossible values nulled; `irr_flag`, `gen_flag`, `*_raw` columns |
| `clean.cluster_halfhour` | mat. view | plants aggregated by cluster × 30 min (mean POA, estimated and verified generation) |
| `clean.pv_detail_quality_monthly` | mat. view | count of each problem type per plant × month |
| `clean.quality_summary` | view | one row per check, with counts |
| `clean.unit_plan` | mat. view | D-1 plan per solar or wind cluster: forecast, scheduled and planned curtailment (since Oct 2024) |
| `clean.wind_curtail` | view | cleaned wind curtailment, mirroring `clean.pv_curtail` |
| `clean.system_halfhour` | mat. view | per subsystem × 30 min: scheduled/verified load, forecast/scheduled/verified wind and solar, net load |

## System tables in `br` (loaded by `ons.py`)

| table | source | coverage |
|---|---|---|
| `br.load_halfhour` | load API: scheduled and verified, by area (SECO, S, NE, N) | Apr 2024– |
| `br.subsystem_balance_hourly` | energy balance by subsystem (hydro, thermal, wind, solar, load) | Apr 2024– |
| `br.program_daily_agg` | daily schedule aggregated by subsystem × type × modality | Oct 2024– |
| `br.renewable_program` | forecast vs. scheduled per wind/solar unit | Oct 2024– |
| `br.cmo_halfhour` | CMO (marginal operating cost) by subsystem, 30 min (DESSEM) | Apr 2024– |
| `br.wind_curtail` | constrained-off curtailment at wind clusters, 30 min | Apr 2024– |
| `br.hydro_daily` | daily ENA and EAR by subsystem | Apr 2024– |
| `br.interchange_hourly` | verified interchange between subsystems | Apr 2024– |
| `br.weather_cell`, `br.weather_cell_unit`, `br.weather_forecast` | ECMWF IFS 0.25° forecast issued 24h and 48h ahead (Open-Meteo Previous Runs), per 0.25° cell | Apr 2024– |
| `br.program_unit` | links PDP code → schedule plant → cluster (`id_ons`), by comparing series | — |

3 schedule files are missing from the portal (2025-02-14 and 2025-03-26). Times are the interval
start in Brasília time; the load from the API comes in UTC labeled at the interval end and is converted.

After loading new CSVs into `br`, run `sql/10_clean.sql` again to refresh the materialized
views.
