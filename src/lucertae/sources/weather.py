"""Archived weather forecasts for the ONS solar and wind clusters.

Source: Open-Meteo Previous Runs API (https://open-meteo.com/en/docs/previous-runs-api), model
ECMWF IFS 0.25°. `*_previous_dayN` is the value forecast by the run issued N×24h before the valid
time. Use subject to the Open-Meteo license (free for non-commercial use).

    uv run python -m lucertae.sources.weather download
    uv run python -m lucertae.sources.weather load

Requires the local PostGIS (see `lucertae.sources.db`) and network access to Open-Meteo.
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
from sqlalchemy import text

from ..paths import RAW_DIR, SQL_DIR
from .db import engine, query
from .ons import register_source, upsert

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
RAW = RAW_DIR / "openmeteo"
SCHEMA_SQL = SQL_DIR / "05_ons_system.sql"
MODEL = "ecmwf_ifs025"
LEADS = (1, 2)               # forecast lead, in days
START, END = "2024-04-01", "2026-08-31"
TIMEZONE = "America/Sao_Paulo"
BATCH = 8                    # cells per request
GRID = 0.25                  # model grid step, in degrees
VARIABLES = {"solar": ("shortwave_radiation", "cloud_cover"), "wind": ("wind_speed_100m",)}
# Open-Meteo variable -> br.weather_forecast column.
FORECAST_COLUMNS = {
    "shortwave_radiation": "ghi",
    "cloud_cover": "cloud_cover",
    "wind_speed_100m": "wind_speed_100m",
}
# Averaged over the previous hour by the model; the others are instantaneous.
HOURLY_MEAN_VARIABLES = ("shortwave_radiation",)

REQUEST_ATTEMPTS = 6
RETRYABLE_HTTP_CODES = (429, 500, 502, 503, 504)

UNIT_CELLS_SQL = """
    with solar as (
        select c.id_ons, u.subsystem, u.capacity_mw,
               coalesce(st_centroid(st_collect(p.geom)), u.geom_collector, u.geom_connection) as g
        from (select distinct id_ons, cluster_key from br.pv_curtail) c
        left join br.plant_cluster pc using (cluster_key)
        left join clean.plant p on p.ceg_core = pc.ceg_core
        left join br.ons_unit u on u.id_ons = c.id_ons
        group by c.id_ons, u.subsystem, u.capacity_mw, u.geom_collector, u.geom_connection
    )
    select id_ons, 'solar' as kind, subsystem, capacity_mw, st_y(g) as lat, st_x(g) as lon
    from solar where g is not null
    union all
    select id_ons, 'wind', subsystem, capacity_mw,
           st_y(coalesce(geom_collector, geom_connection)), st_x(coalesce(geom_collector, geom_connection))
    from br.ons_unit where kind = 'Eólica'
"""


def unit_cells() -> pd.DataFrame:
    """Solar and wind clusters, each assigned to the nearest cell of the model grid.

    A solar cluster is located at the centroid of its plants, or at the ONS collector when
    no plant is known; a wind cluster, at the ONS collector.
    """
    units = query(UNIT_CELLS_SQL)
    units["latitude"] = (units["lat"] / GRID).round() * GRID
    units["longitude"] = (units["lon"] / GRID).round() * GRID
    units["cell_id"] = units["latitude"].map("{:.2f}".format) + "_" + units["longitude"].map("{:.2f}".format)
    return units


def _request(cells: pd.DataFrame, variables: tuple[str, ...]) -> list[dict]:
    """Hourly forecasts for a batch of cells, one dict per cell, in the order of `cells`."""
    hourly = ",".join(f"{v}_previous_day{lead}" for v in variables for lead in LEADS)
    latitudes = ",".join(cells["latitude"].map(str))
    longitudes = ",".join(cells["longitude"].map(str))
    url = (
        f"{API}?latitude={latitudes}&longitude={longitudes}"
        f"&hourly={hourly}&models={MODEL}&start_date={START}&end_date={END}"
        f"&timezone={urllib.parse.quote(TIMEZONE, safe='')}"
    )
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=600) as resp:
                data = json.loads(resp.read())
            return data if isinstance(data, list) else [data]
        except urllib.error.HTTPError as err:
            if err.code not in RETRYABLE_HTTP_CODES:
                raise
            wait = 60 * (attempt + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            wait = 30 * (attempt + 1)
        print(f"  attempt {attempt + 1} failed; waiting {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError("Open-Meteo unavailable")


def download(kinds: tuple[str, ...] = tuple(VARIABLES)) -> None:
    """Download the forecasts in batches of cells; batches already on disk are skipped."""
    units = unit_cells()
    for kind in kinds:
        variables = VARIABLES[kind]
        cells = units[units["kind"] == kind].drop_duplicates("cell_id").reset_index(drop=True)
        for i in range(0, len(cells), BATCH):
            batch = cells.iloc[i:i + BATCH]
            dest = RAW / f"{kind}_{MODEL}_{i // BATCH:03d}.json"
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = _request(batch, variables)
            payload = [{"cell_id": cell_id, **loc} for cell_id, loc in zip(batch["cell_id"], data)]
            dest.write_text(json.dumps(payload))
            print(f"{dest.name}: {len(batch)} cells", flush=True)


def _hourly_frame(loc: dict, variables: tuple[str, ...]) -> pd.DataFrame:
    """Forecasts of one cell as rows of (instante, lead_day), one column per variable.

    A row covers the hour [H, H+1). Radiation is labeled at H+1 as the mean of the previous
    hour and is used as is; an instantaneous variable becomes the mean of its values at H
    and H+1. The first label has no previous value and is dropped.
    """
    hourly = loc["hourly"]
    label = pd.to_datetime(pd.Series(hourly["time"]))
    frames = []
    for lead in LEADS:
        out = pd.DataFrame({"instante": label - pd.Timedelta(hours=1)})
        for var in variables:
            values = pd.to_numeric(pd.Series(hourly[f"{var}_previous_day{lead}"]), errors="coerce")
            if var not in HOURLY_MEAN_VARIABLES:
                values = (values + values.shift(1)) / 2
            out[FORECAST_COLUMNS[var]] = values
        out["lead_day"] = lead
        frames.append(out.iloc[1:])
    return pd.concat(frames, ignore_index=True)


def load() -> None:
    """Load the cells, the cell of each cluster and the downloaded forecasts into the br schema."""
    ddl = SCHEMA_SQL.read_text()
    units = unit_cells()
    with engine().begin() as conn:
        conn.connection.driver_connection.execute(ddl)
        cells = units.drop_duplicates("cell_id")[["cell_id", "latitude", "longitude"]]
        upsert(conn, "br.weather_cell", cells, ["cell_id"])
        conn.execute(text("delete from br.weather_cell_unit"))
        cell_units = units[["id_ons", "kind", "subsystem", "capacity_mw", "cell_id"]]
        upsert(conn, "br.weather_cell_unit", cell_units, ["id_ons", "kind"])

    for path in sorted(RAW.glob(f"*_{MODEL}_*.json")):
        kind = path.name.split("_")[0]
        variables = VARIABLES[kind]
        frames = []
        for loc in json.loads(path.read_text()):
            frame = _hourly_frame(loc, variables)
            frame["cell_id"] = loc["cell_id"]
            frames.append(frame)
        df = pd.concat(frames, ignore_index=True)
        df["model"] = MODEL
        with engine().begin() as conn:
            df["source_id"] = register_source(conn, f"weather_{MODEL}", path.stem, path.name, len(df))
            value_cols = [FORECAST_COLUMNS[var] for var in FORECAST_COLUMNS if var in variables]
            cols = ["cell_id", "model", "lead_day", "instante", *value_cols, "source_id"]
            upsert(conn, "br.weather_forecast", df[cols], ["cell_id", "model", "lead_day", "instante"])
        print(f"{path.name}: {len(df):,} rows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["download", "load"])
    parser.add_argument("--kinds", default=",".join(VARIABLES), help="solar,wind")
    args = parser.parse_args()
    if args.command == "download":
        download(tuple(args.kinds.split(",")))
    else:
        load()


if __name__ == "__main__":
    main()
