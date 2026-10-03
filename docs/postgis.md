# Setting up the PostGIS database (`terra_br`)

This project reads everything from a local PostgreSQL database with PostGIS, named `terra_br`. The database has three
schemas, filled by two different projects:

| schema | what it contains | who creates and loads it |
|---|---|---|
| `br` (base) | ANEEL plant register, ONS network, ONS units, photovoltaic curtailment and detail | the **TERRA** project (`sidecar/terra/grid/store.py`) |
| `br` (system) | load, energy balance, daily schedule, CMO, hydrology, interchange, wind curtailment, weather forecast | this project (`sql/05_ons_system.sql`, `ons.py`, `weather.py`) |
| `clean` | cleaning layer and aggregates used by the dataset | this project (`sql/10_clean.sql`, `sql/20_clean_system.sql`) |

The system tables depend on the base tables: `br.source_file`, which records the origin of each row, is
created by TERRA. For this reason, the order below matters.

Reference for the database in use (Sep 2026): PostgreSQL 17.11 (Homebrew, macOS arm64), PostGIS 3.6.4,
9.7 GB in total with data from Apr 2024 to Aug 2026. The largest tables are `br.pv_detail` (3.8 GB),
`br.wind_curtail` (1.4 GB) and `br.weather_forecast` (1.2 GB).

## 1. Install PostgreSQL and PostGIS

**macOS (Homebrew)**

```sh
brew install postgresql@17 postgis
brew services start postgresql@17
```

The Homebrew `postgis` formula is built for a specific PostgreSQL version. Check with
`brew info postgis` that it matches the installed version; if it does not, `create extension
postgis` fails with "extension not available".

**Debian/Ubuntu**

```sh
sudo apt install postgresql-17 postgresql-17-postgis-3
sudo -u postgres createuser --superuser "$USER"
```

## 2. Create the database

```sh
createdb terra_br
psql -d terra_br -c "create extension if not exists postgis;"
psql -d terra_br -c "select postgis_full_version();"
```

TERRA also runs `create extension if not exists postgis` when it opens the database. Creating the extension
here first makes it possible to check the installation without depending on TERRA.

## 3. Connection

Both projects look for the same database by default, but they read different environment variables:

| project | variable | default |
|---|---|---|
| this one | `DATABASE_URL`, or `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE` (`db.py`) | `postgresql+psycopg://$USER@localhost:5432/terra_br` |
| TERRA | `TERRA_BR_DSN` | `postgresql:///terra_br` (local socket) |

With a local database owned by the system user, no variable is needed. On another host or
port, set both, pointing to the same database:

```sh
export DATABASE_URL=postgresql+psycopg://usuario@host:5432/terra_br
export TERRA_BR_DSN=postgresql://usuario@host:5432/terra_br
```

## 4. Base tables (TERRA)

TERRA ([rexionmars/TERRA](https://github.com/rexionmars/TERRA)) maintains the base schema and the
loaders in `sidecar/terra/grid/store.py` and `sidecar/terra/grid/ons.py`. They have no command
line: they are Python functions. The script below, run in the Python environment of the TERRA sidecar, loads
what this project uses.

**Input files, downloaded by hand**

| table | source | file |
|---|---|---|
| `br.plant` | ANEEL, [SIGA](https://dadosabertos.aneel.gov.br/dataset/siga-sistema-de-informacoes-de-geracao-da-aneel) | `siga-empreendimentos-geracao.csv` |
| `br.substation`, `br.transmission_line` | ONS, [subestacao](https://dados.ons.org.br/dataset/subestacao) and [linha-transmissao](https://dados.ons.org.br/dataset/linha-transmissao) | `SUBESTACAO.parquet`, `LINHA_TRANSMISSAO.parquet` |
| `br.ons_unit` | ONS, [fator-capacidade-2](https://dados.ons.org.br/dataset/fator-capacidade-2) | the most recent monthly file (one month is enough) |

The photovoltaic curtailment data (`br.pv_curtail`, `br.pv_detail`) are downloaded by TERRA itself from
the ONS catalog (`restricao_coff_fotovoltaica` and `restricao_coff_fotovoltaica_detail`), with a cache
in `~/.cache/geosense/ons` (about 93 MB per month for the detail alone).

```python
from pathlib import Path

from terra.grid import ons, store

conn = store.connect()          # TERRA_BR_DSN or postgresql:///terra_br
store.ensure_schema(conn)       # postgis + br schema + base tables; idempotent

raw = Path("~/dados/terra_br").expanduser()   # where the hand-downloaded files are
print(store.load_plants(conn, raw / "siga-empreendimentos-geracao.csv"))
print(store.load_network(conn, raw / "SUBESTACAO.parquet", raw / "LINHA_TRANSMISSAO.parquet"))
print(store.load_units(conn, raw / "FATOR_CAPACIDADE-2_2026_08.csv"))

cache = Path.home() / ".cache" / "geosense" / "ons"
for dataset in ("pv_curtailment", "pv_curtailment_detail"):
    periods = ons.periods_covering("2024-04-01", "2026-08-31", ons.catalogue(dataset))
    for _, row in periods.iterrows():
        path, provenance = ons.fetch_period(dataset, row, cache)
        print(store.load_period(conn, dataset, path, provenance))

print(store.refresh_clusters(conn))   # br.plant_cluster, from br.pv_detail
print(store.refresh_rollup(conn))     # br.pv_daily; ~70 s, once at the end of the load
conn.commit()
```

The `load_units` file name above is an example; use the one for the downloaded month. The script uses only public
functions of `store.py` and `ons.py`, but it has not been run end to end in this form: the current database
was loaded by TERRA in separate runs.

`load_period` compares the file revision with the one recorded in `br.source_file`. A revision that was already
loaded is skipped; a new revision deletes the rows of the previous one before inserting. Running the script
again therefore only downloads and reloads the months that the ONS republished.

## 5. System tables and weather forecast (this project)

```sh
uv sync

# ~400 MB in data/raw/ons; load ~10 min. The load creates the tables from sql/05_ons_system.sql.
uv run python -m lucertae.corte.ons download --start 2024-04-01 --end 2026-08-31
uv run python -m lucertae.corte.ons load --start 2024-04-01 --end 2026-08-31

# archived ECMWF: download ~11 min (~110 MB), load ~5 min (~1.2 GB in the database)
uv run python -m lucertae.corte.weather download
uv run python -m lucertae.corte.weather load
```

`ons load` accepts `--parts` to load only some of the sources (default:
`balanco,hidro,intercambio,cmo,eolica,carga,programacao`).

## 6. `clean` layer

```sh
psql -d terra_br -v ON_ERROR_STOP=1 -f sql/10_clean.sql          # ~12 min
psql -d terra_br -v ON_ERROR_STOP=1 -f sql/20_clean_system.sql
```

`10_clean.sql` uses only the base tables (`br.plant`, `br.plant_cluster`, `br.ons_unit`,
`br.pv_curtail`, `br.pv_detail`, `br.transmission_line`). `20_clean_system.sql` uses the system
tables and `br.ons_unit`. Both scripts drop and recreate their own objects and can be run
again; no object in `20` depends on `10`.

Most of the run time of `10_clean.sql` is spent in `clean.pv_detail_day_flag`. With the default
Homebrew settings (`work_mem` 4 MB, `maintenance_work_mem` 64 MB), the run takes ~12 min. Larger
values set for the session only may reduce this time; the effect was not measured:

```sh
PGOPTIONS='-c work_mem=256MB -c maintenance_work_mem=1GB' \
  psql -d terra_br -v ON_ERROR_STOP=1 -f sql/10_clean.sql
```

## 7. Verification

```sql
-- origin of each load: one record per file
select dataset, count(*) arquivos, min(period), max(period), sum(row_count) linhas
from br.source_file group by 1 order by 1;

-- registers (they do not go through br.source_file)
select (select count(*) from br.plant) plant, (select count(*) from br.ons_unit) ons_unit,
       (select count(*) from br.substation) substation,
       (select count(*) from br.transmission_line) transmission_line;

-- quality problems found by the clean layer
select * from clean.quality_summary;
```

Values from the database in use, for comparison (Apr 2024–Aug 2026):

| dataset | files | rows |
|---|---|---|
| `pv_curtailment` | 29 | 2,854,800 |
| `pv_curtailment_detail` | 30 (includes 2026-09, partial) | 19,088,880 |
| `wind_curtailment` | 29 | 6,586,368 |
| `program_daily` | 698 | 132,304,752 |
| `renewable_program` | 698 | 18,044,832 |
| `load_programmed` / `load_verified` | 29 / 29 | 169,440 / 169,536 |
| `weather_ecmwf_ifs025` | 20 | 6,696,356 |
| `cmo`, `hydro_daily`, `interchange`, `subsystem_balance` | 3 each | 168,384, 3,532, 84,768, 105,960 |

Registers: `br.plant` 25,130, `br.ons_unit` 236, `br.substation` 1,677, `br.transmission_line` 2,208.

`program_daily` and `renewable_program` have 698 files, not 700, because the files for
2025-02-14 and 2025-03-26 are missing from the portal.

## 8. Updating with new months

1. TERRA: run the `load_period` loop again with the new end date, then `refresh_clusters` and
   `refresh_rollup`. If the register changed, reload `load_units` with the most recent month.
2. This project: `ons download` and `ons load` with the new interval; `weather download` and `weather load`.
3. `sql/10_clean.sql` and `sql/20_clean_system.sql` again, to refresh the materialized views.
4. Regenerate the datasets (`python -m lucertae.corte.dataset`, with and without `--tech wind`).

## Objects that are not part of the workflow

- `clean.solar_unit_plan`: an earlier version of `clean.unit_plan`, restricted to the solar clusters, that
  remained in the database. No script in this project creates or reads it; for the solar clusters, its contents are identical
  to those of `clean.unit_plan` (1,165,454 rows, checked in Sep 2026).
- `br.tmp_pr_dia`: temporary table from an old load. No script creates or reads it.
- `br.load_conflict`: created by TERRA; records duplicate rows (`id_ons`, instant) discarded
  by `load_period`.

The first two can be removed with `drop materialized view clean.solar_unit_plan;` and
`drop table br.tmp_pr_dia;`.
