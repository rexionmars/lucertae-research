"""Archived weather forecasts for the ONS solar and wind clusters.

Source: Open-Meteo Previous Runs API (https://open-meteo.com/en/docs/previous-runs-api), model
ECMWF IFS 0.25°. `*_previous_dayN` is the value forecast by the run issued N×24h before the valid
time. Use subject to the Open-Meteo license (free for non-commercial use).

    uv run python -m terra_energy_research.weather download
    uv run python -m terra_energy_research.weather load
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from terra_energy_research.db import engine, query
from terra_energy_research.ons import _register_source, _upsert

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
RAW = Path("data/raw/openmeteo")
MODEL = "ecmwf_ifs025"
LEADS = (1, 2)
START, END = "2024-04-01", "2026-08-31"
BATCH = 8
GRID = 0.25
VARIABLES = {"solar": ("shortwave_radiation", "cloud_cover"), "wind": ("wind_speed_100m",)}


def unit_cells() -> pd.DataFrame:
    """Solar clusters (centroid of the plants; otherwise ONS collector) and wind clusters (ONS collector) on the grid."""
    units = query(
        """
        with solar as (
            select c.id_ons, u.subsystem, u.capacity_mw,
                   coalesce(st_centroid(st_collect(p.geom)), u.geom_collector, u.geom_connection) as g
            from (select distinct id_ons, cluster_key from br.pv_curtail) c
            left join br.plant_cluster pc using (cluster_key)
            left join clean.plant p on p.ceg_core = pc.ceg_core
            left join br.ons_unit u on u.id_ons = c.id_ons
            group by c.id_ons, u.subsystem, u.capacity_mw, u.geom_collector, u.geom_connection
        )
        select id_ons, 'solar' as kind, subsystem, capacity_mw, st_y(g) as lat, st_x(g) as lon from solar where g is not null
        union all
        select id_ons, 'wind', subsystem, capacity_mw,
               st_y(coalesce(geom_collector, geom_connection)), st_x(coalesce(geom_collector, geom_connection))
        from br.ons_unit where kind = 'Eólica'
        """
    )
    units["latitude"] = (units["lat"] / GRID).round() * GRID
    units["longitude"] = (units["lon"] / GRID).round() * GRID
    units["cell_id"] = units["latitude"].map("{:.2f}".format) + "_" + units["longitude"].map("{:.2f}".format)
    return units


def _request(cells: pd.DataFrame, variables: tuple[str, ...]) -> list[dict]:
    hourly = ",".join(f"{v}_previous_day{lead}" for v in variables for lead in LEADS)
    url = (
        f"{API}?latitude={','.join(cells['latitude'].map(str))}&longitude={','.join(cells['longitude'].map(str))}"
        f"&hourly={hourly}&models={MODEL}&start_date={START}&end_date={END}&timezone=America%2FSao_Paulo"
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=600) as resp:
                data = json.loads(resp.read())
            return data if isinstance(data, list) else [data]
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504):
                raise
            wait = 60 * (attempt + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            wait = 30 * (attempt + 1)
        print(f"  attempt {attempt + 1} failed; waiting {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError("Open-Meteo unavailable")


def download(kinds: tuple[str, ...] = tuple(VARIABLES)) -> None:
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
            payload = [{"cell_id": cid, **loc} for cid, loc in zip(batch["cell_id"], data)]
            dest.write_text(json.dumps(payload))
            print(f"{dest.name}: {len(batch)} cells", flush=True)


def _hourly_frame(loc: dict, variables: tuple[str, ...]) -> pd.DataFrame:
    h = loc["hourly"]
    label = pd.to_datetime(pd.Series(h["time"]))
    frames = []
    for lead in LEADS:
        df = pd.DataFrame({"label": label})
        for var in variables:
            df[var] = pd.to_numeric(pd.Series(h[f"{var}_previous_day{lead}"]), errors="coerce")
        # hour [H, H+1): radiation labeled at H+1 (mean of the previous hour); instantaneous values, mean of H and H+1
        out = pd.DataFrame({"instante": df["label"] - pd.Timedelta(hours=1)})
        if "shortwave_radiation" in df:
            out["ghi"] = df["shortwave_radiation"]
        for var, col in (("cloud_cover", "cloud_cover"), ("wind_speed_100m", "wind_speed_100m")):
            if var in df:
                out[col] = (df[var] + df[var].shift(1)) / 2
        out["lead_day"] = lead
        frames.append(out.iloc[1:])
    return pd.concat(frames, ignore_index=True)


def load() -> None:
    ddl = Path("sql/05_ons_system.sql").read_text()
    units = unit_cells()
    with engine().begin() as conn:
        conn.connection.driver_connection.execute(ddl)
        cells = units.drop_duplicates("cell_id")[["cell_id", "latitude", "longitude"]]
        _upsert(conn, "br.weather_cell", cells, ["cell_id"])
        conn.execute(text("delete from br.weather_cell_unit"))
        _upsert(conn, "br.weather_cell_unit", units[["id_ons", "kind", "subsystem", "capacity_mw", "cell_id"]], ["id_ons", "kind"])

    for path in sorted(RAW.glob(f"*_{MODEL}_*.json")):
        kind = path.name.split("_")[0]
        rows = []
        for loc in json.loads(path.read_text()):
            frame = _hourly_frame(loc, VARIABLES[kind])
            frame["cell_id"] = loc["cell_id"]
            rows.append(frame)
        df = pd.concat(rows, ignore_index=True)
        df["model"] = MODEL
        with engine().begin() as conn:
            df["source_id"] = _register_source(conn, f"weather_{MODEL}", path.stem, path.name, len(df))
            cols = ["cell_id", "model", "lead_day", "instante", *[c for c in ("ghi", "cloud_cover", "wind_speed_100m") if c in df], "source_id"]
            _upsert(conn, "br.weather_forecast", df[cols], ["cell_id", "model", "lead_day", "instante"])
        print(f"{path.name}: {len(df):,} rows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["download", "load"])
    parser.add_argument("--kinds", default=",".join(VARIABLES), help="solar,wind")
    args = parser.parse_args()
    download(tuple(args.kinds.split(","))) if args.command == "download" else load()


if __name__ == "__main__":
    main()
