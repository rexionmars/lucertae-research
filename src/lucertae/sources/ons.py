"""Download and loading of ONS open data into the br schema (sql/05_ons_system.sql).

Sources:
  - load API (apicarga.ons.org.br): scheduled and verified load, 30 min, by area
  - balanco_energia_subsistema: verified generation by source and load, hourly
  - programacao_diaria: scheduled generation by plant, 30 min (since Oct 2024)
  - programacao_x_previsao: forecast vs. scheduled for wind and solar (since Oct 2024)
  - ena/ear_diario_por_subsistema: natural inflow energy and stored energy, daily
  - intercambio_nacional: verified flow between subsystems, hourly
  - cmo-semi-horario: marginal operating cost by subsystem, 30 min
  - restricao_coff_eolica_usi: constrained-off curtailment at wind clusters, 30 min

    uv run python -m lucertae.sources.ons download --start 2024-04-01 --end 2026-08-31
    uv run python -m lucertae.sources.ons load     --start 2024-04-01 --end 2026-08-31

Requires the local PostGIS (see `lucertae.sources.db`). Columns named after the
ONS files (`id_subsistema`, `din_instante`, `val_*`, ...) and the columns of the
br schema (`instante`, `patamar`, `cod_exibicao`, ...) stay as published.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, text

from ..paths import RAW_DIR, SQL_DIR
from .db import engine

RAW = RAW_DIR / "ons"
SCHEMA_SQL = SQL_DIR / "05_ons_system.sql"
S3 = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset"
API = "https://apicarga.ons.org.br/prd"

DEFAULT_START = date(2024, 4, 1)
DEFAULT_END = date(2026, 8, 31)

# (S3 folder, file prefix, folder under RAW) of the datasets published per year.
YEARLY_DATASETS = (
    ("balanco_energia_subsistema_ho", "BALANCO_ENERGIA_SUBSISTEMA", "balanco"),
    ("ena_subsistema_di", "ENA_DIARIO_SUBSISTEMA", "hidro"),
    ("ear_subsistema_di", "EAR_DIARIO_SUBSISTEMA", "hidro"),
    ("intercambio_nacional_ho", "INTERCAMBIO_NACIONAL", "intercambio"),
    ("cmo_tm", "CMO_SEMIHORARIO", "cmo"),
)
# (S3 folder, which is also the folder under RAW; file prefix), per day.
DAILY_DATASETS = (
    ("programacao_diaria", "PROGRAMACAO_DIARIA"),
    ("programacao_x_previsao", "PROGRAMACAO_X_PREVISAO"),
)

LOAD_AREAS = ("SECO", "S", "NE", "N")
LOAD_ENDPOINTS = {"cargaprogramada": "load_programmed", "cargaverificada": "load_verified"}
PROGRAM_START = date(2024, 10, 1)  # first daily file published
STEPS_PER_DAY = 48                 # the daily schedule comes in 30 min steps ("patamar")
STEP_MINUTES = 30

RENEWABLE_TYPES = ("SOLAR", "EÓLICA")
# PDP -> display code link is only accepted if it matches on most of the days the unit
# appears; small series can coincide by chance between different plants.
MIN_MATCH_DAYS, MIN_MATCH_RATIO = 5, 0.5

FETCH_ATTEMPTS = 4

# One download job: (url, destination, overwrite).
DownloadJob = tuple[str, Path, bool]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _fetch(url: str, dest: Path, overwrite: bool = False) -> str:
    """Download `url` to `dest` and return the outcome.

    The outcome is "ok", "cached" (file already on disk), or the error: an HTTP
    client error returns at once, server and network errors after the retries.
    """
    if dest.exists() and not overwrite:
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=300) as resp:
                data = resp.read()
            break
        except urllib.error.HTTPError as err:
            if err.code < 500:
                return f"http {err.code}"
            error = f"http {err.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            error = type(err).__name__
        time.sleep(5 * (attempt + 1))
    else:
        return error
    # Write to a temporary name so an interrupted download is never read as complete.
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(dest)
    return "ok"


def _months(start: date, end: date) -> list[pd.Period]:
    return list(pd.period_range(start, end, freq="M"))


def _program_days(start: date, end: date) -> pd.DatetimeIndex:
    """Days in the window for which the daily schedule is published."""
    return pd.date_range(max(start, PROGRAM_START), end, freq="D")


def download_jobs(start: date, end: date) -> list[DownloadJob]:
    """(url, destination, overwrite). Files for the current period are always re-downloaded."""
    today = date.today()
    current_month = pd.Period(today, "M")
    jobs = []
    for year in range(start.year, end.year + 1):
        for folder, prefix, dest in YEARLY_DATASETS:
            name = f"{prefix}_{year}.parquet"
            jobs.append((f"{S3}/{folder}/{name}", RAW / dest / name, year == today.year))
    for month in _months(start, end):
        first, last = month.start_time.date(), min(month.end_time.date(), end)
        for endpoint in LOAD_ENDPOINTS:
            for area in LOAD_AREAS:
                url = f"{API}/{endpoint}?dat_inicio={first}&dat_fim={last}&cod_areacarga={area}"
                dest = RAW / "carga" / f"{endpoint}_{area}_{month}.json"
                jobs.append((url, dest, month == current_month))
    for month in _months(start, end):
        name = f"RESTRICAO_COFF_EOLICA_{month.strftime('%Y_%m')}.parquet"
        url = f"{S3}/restricao_coff_eolica_tm/{name}"
        jobs.append((url, RAW / "eolica" / name, month == current_month))
    for day in _program_days(start, end):
        for dataset, prefix in DAILY_DATASETS:
            name = f"{prefix}_{day:%Y_%m_%d}.parquet"
            jobs.append((f"{S3}/{dataset}/{name}", RAW / dataset / name, False))
    return jobs


def download(start: date, end: date, workers: int = 8) -> None:
    """Download every file of the window and print a summary by outcome."""
    jobs = download_jobs(start, end)
    with ThreadPoolExecutor(workers) as pool:
        outcomes = list(pool.map(lambda job: _fetch(*job), jobs))
    print(f"{len(jobs)} files: {dict(Counter(outcomes))}")
    for (_url, dest, _overwrite), outcome in zip(jobs, outcomes):
        if outcome not in ("ok", "cached"):
            print(f"  {outcome}: {dest.name}")


# ---------------------------------------------------------------------------
# Loading into the database
# ---------------------------------------------------------------------------

def _num(s: pd.Series) -> pd.Series:
    """Numeric series from text with either decimal comma or decimal point."""
    return pd.to_numeric(s.astype("string").str.strip().str.replace(",", ".", regex=False), errors="coerce")


def _text(s: pd.Series) -> pd.Series:
    """String series without surrounding whitespace."""
    return s.astype("string").str.strip()


def _in_window(instants: pd.Series, start: date, end: date) -> pd.Series:
    """Mask of the instants from `start` to the end of the day `end`."""
    return (instants >= pd.Timestamp(start)) & (instants < pd.Timestamp(end) + pd.Timedelta(days=1))


def _step_start(day: pd.Timestamp, steps: pd.Series) -> pd.Series:
    """Start instant of each 30 min step; steps are numbered from 1."""
    return day.normalize() + pd.to_timedelta((steps.astype(int) - 1) * STEP_MINUTES, unit="min")


def register_source(conn: Connection, dataset: str, period: str, filename: str, row_count: int) -> int:
    """Record the file a load came from in br.source_file and return its source_id."""
    return conn.execute(
        text("""
            insert into br.source_file (dataset, period, filename, row_count)
            values (:dataset, :period, :filename, :row_count)
            on conflict (dataset, period) do update
               set filename = excluded.filename, row_count = excluded.row_count, loaded_utc = now()
            returning source_id
        """),
        dict(dataset=dataset, period=period, filename=filename, row_count=row_count),
    ).scalar_one()


def upsert(conn: Connection, table: str, df: pd.DataFrame, key: list[str]) -> None:
    """COPY into a temp table and INSERT ... ON CONFLICT DO UPDATE on the non-key columns."""
    if df.empty:
        return
    cols = list(df.columns)
    col_list = ", ".join(cols)
    raw = conn.connection.driver_connection
    with raw.cursor() as cur:
        cur.execute(f"create temp table _stage (like {table} including defaults) on commit drop")
        with cur.copy(f"copy _stage ({col_list}) from stdin") as copy:
            for row in df.itertuples(index=False, name=None):
                copy.write_row([None if pd.isna(v) else v for v in row])
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key)
        cur.execute(
            f"insert into {table} ({col_list}) select {col_list} from _stage "
            f"on conflict ({', '.join(key)}) do update set {updates}"
        )
        cur.execute("drop table _stage")


def load_balance(conn: Connection, start: date, end: date) -> None:
    """Verified generation by source, load and interchange, hourly, by subsystem."""
    for year in range(start.year, end.year + 1):
        path = RAW / "balanco" / f"BALANCO_ENERGIA_SUBSISTEMA_{year}.parquet"
        raw = pd.read_parquet(path)
        df = pd.DataFrame({
            "subsystem": _text(raw["id_subsistema"]),
            "instante": pd.to_datetime(raw["din_instante"]),
            "hydro": _num(raw["val_gerhidraulica"]),
            "thermal": _num(raw["val_gertermica"]),
            "wind": _num(raw["val_gereolica"]),
            "solar": _num(raw["val_gersolar"]),
            "load": _num(raw["val_carga"]),
            "interchange": _num(raw["val_intercambio"]),
        })
        df = df[_in_window(df["instante"], start, end)]
        df["source_id"] = register_source(conn, "subsystem_balance", str(year), path.name, len(df))
        upsert(conn, "br.subsystem_balance_hourly", df, ["subsystem", "instante"])
        print(f"balance {year}: {len(df):,} rows")


def load_hydro(conn: Connection, start: date, end: date) -> None:
    """Natural inflow energy (ENA) and stored energy (EAR), daily, by subsystem."""
    for year in range(start.year, end.year + 1):
        ena = pd.read_parquet(RAW / "hidro" / f"ENA_DIARIO_SUBSISTEMA_{year}.parquet")
        ear = pd.read_parquet(RAW / "hidro" / f"EAR_DIARIO_SUBSISTEMA_{year}.parquet")
        ena = pd.DataFrame({
            "subsystem": _text(ena["id_subsistema"]),
            "day": pd.to_datetime(ena["ena_data"]).dt.date,
            "ena_mwmed": _num(ena["ena_bruta_regiao_mwmed"]),
            "ena_pct_mlt": _num(ena["ena_bruta_regiao_percentualmlt"]),
        })
        ear = pd.DataFrame({
            "subsystem": _text(ear["id_subsistema"]),
            "day": pd.to_datetime(ear["ear_data"]).dt.date,
            "ear_mwmes": _num(ear["ear_verif_subsistema_mwmes"]),
            "ear_pct": _num(ear["ear_verif_subsistema_percentual"]),
        })
        df = ena.merge(ear, on=["subsystem", "day"], how="outer")
        df = df[(df["day"] >= start) & (df["day"] <= end)]
        filename = f"ENA/EAR_DIARIO_SUBSISTEMA_{year}.parquet"
        df["source_id"] = register_source(conn, "hydro_daily", str(year), filename, len(df))
        upsert(conn, "br.hydro_daily", df, ["subsystem", "day"])
        print(f"hydrology {year}: {len(df):,} rows")


def load_interchange(conn: Connection, start: date, end: date) -> None:
    """Verified flow between subsystems, hourly, by ordered pair."""
    for year in range(start.year, end.year + 1):
        path = RAW / "intercambio" / f"INTERCAMBIO_NACIONAL_{year}.parquet"
        raw = pd.read_parquet(path)
        df = pd.DataFrame({
            "origin": _text(raw["id_subsistema_origem"]),
            "destination": _text(raw["id_subsistema_destino"]),
            "instante": pd.to_datetime(raw["din_instante"]),
            "flow_mw": _num(raw["val_intercambiomwmed"]),
        })
        df = df[_in_window(df["instante"], start, end)]
        df["source_id"] = register_source(conn, "interchange", str(year), path.name, len(df))
        upsert(conn, "br.interchange_hourly", df, ["origin", "destination", "instante"])
        print(f"interchange {year}: {len(df):,} rows")


def load_cmo(conn: Connection, start: date, end: date) -> None:
    """Marginal operating cost, 30 min, by subsystem."""
    for year in range(start.year, end.year + 1):
        path = RAW / "cmo" / f"CMO_SEMIHORARIO_{year}.parquet"
        raw = pd.read_parquet(path)
        df = pd.DataFrame({
            "subsystem": _text(raw["id_subsistema"]),
            "instante": pd.to_datetime(raw["din_instante"]),
            "cmo": _num(raw["val_cmo"]),
        })
        df = df[_in_window(df["instante"], start, end)]
        df["source_id"] = register_source(conn, "cmo", str(year), path.name, len(df))
        upsert(conn, "br.cmo_halfhour", df, ["subsystem", "instante"])
        print(f"CMO {year}: {len(df):,} rows")


# ONS column -> br.wind_curtail column.
WIND_COLUMNS = {
    "id_ons": "id_ons", "din_instante": "instante", "ceg": "ceg", "id_subsistema": "subsystem",
    "id_estado": "uf", "nom_usina": "plant_name", "id_pontoconexao": "connection_code",
    "nom_agenteoperador": "operator", "val_geracao": "generation", "val_geracaolimitada": "generation_limited",
    "val_disponibilidade": "availability", "val_geracaoreferencia": "reference",
    "val_geracaoreferenciafinal": "reference_final", "val_geracaonaorealizadaapurada": "unrealized_mw",
    "cod_razaorestricao": "reason_code", "cod_origemrestricao": "origin_code",
    "num_minutos_rel": "minutes_rel", "num_minutos_cnf": "minutes_cnf", "num_minutos_ene": "minutes_ene",
    "num_minutos_restricao": "minutes_restriction",
}
WIND_POWER_COLUMNS = (
    "generation", "generation_limited", "availability", "reference", "reference_final", "unrealized_mw",
)
WIND_MINUTE_COLUMNS = ("minutes_rel", "minutes_cnf", "minutes_ene", "minutes_restriction")
WIND_TEXT_COLUMNS = (
    "id_ons", "ceg", "subsystem", "uf", "plant_name", "connection_code", "operator", "reason_code", "origin_code",
)


def load_wind_curtail(conn: Connection, start: date, end: date) -> None:
    """Constrained-off curtailment at wind clusters, 30 min."""
    for month in _months(start, end):
        path = RAW / "eolica" / f"RESTRICAO_COFF_EOLICA_{month.strftime('%Y_%m')}.parquet"
        if not path.exists():
            print(f"wind {month}: file missing")
            continue
        raw = pd.read_parquet(path)
        df = raw[list(WIND_COLUMNS)].rename(columns=WIND_COLUMNS)
        df["instante"] = pd.to_datetime(df["instante"])
        for col in WIND_POWER_COLUMNS:
            df[col] = _num(df[col])
        for col in WIND_MINUTE_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        for col in WIND_TEXT_COLUMNS:
            df[col] = _text(df[col])
        df = df.drop_duplicates(["id_ons", "instante"], keep="last")
        df["source_id"] = register_source(conn, "wind_curtailment", str(month), path.name, len(df))
        upsert(conn, "br.wind_curtail", df, ["id_ons", "instante"])
        print(f"wind {month}: {len(df):,} rows")


def load_area_load(conn: Connection, start: date, end: date) -> None:
    """Scheduled and verified load, 30 min, by load area."""
    for month in _months(start, end):
        for endpoint, dataset in LOAD_ENDPOINTS.items():
            scheduled = endpoint == "cargaprogramada"
            frames = []
            for area in LOAD_AREAS:
                path = RAW / "carga" / f"{endpoint}_{area}_{month}.json"
                frames.append(pd.DataFrame(json.loads(path.read_text())))
            df = pd.concat(frames, ignore_index=True)
            # din_referenciautc marks the END of the interval in UTC -> start in Brasília time
            utc_end = pd.to_datetime(df["din_referenciautc"], utc=True)
            utc_start = utc_end - pd.Timedelta(minutes=STEP_MINUTES)
            out = pd.DataFrame({
                "area": df["cod_areacarga"],
                "instante": utc_start.dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None),
            })
            if scheduled:
                out["load_programmed"] = _num(df["val_cargaglobalprogramada"])
            else:
                out["load_verified"] = _num(df["val_cargaglobal"])
                out["load_verified_cons"] = _num(df["val_cargaglobalcons"])
                out["load_verified_no_mmgd"] = _num(df["val_cargaglobalsmmgd"])
                out["load_mmgd"] = _num(df["val_cargammgd"])
                out["load_supervised"] = _num(df["val_cargasupervisionada"])
                out["load_unsupervised"] = _num(df["val_carganaosupervisionada"])
            out = out.drop_duplicates(["area", "instante"], keep="last")
            source_col = "source_programmed_id" if scheduled else "source_verified_id"
            out[source_col] = register_source(conn, dataset, str(month), f"{endpoint}_{month}.json", len(out))
            upsert(conn, "br.load_halfhour", out, ["area", "instante"])
        print(f"load {month}: ok")


def _read_program_day(day: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Daily schedule and forecast-vs-scheduled of one day, or None if a file is missing."""
    stamp = day.strftime("%Y_%m_%d")
    daily_path = RAW / "programacao_diaria" / f"PROGRAMACAO_DIARIA_{stamp}.parquet"
    fx_path = RAW / "programacao_x_previsao" / f"PROGRAMACAO_X_PREVISAO_{stamp}.parquet"
    if not (daily_path.exists() and fx_path.exists()):
        return None

    daily = pd.read_parquet(daily_path)
    daily = pd.DataFrame({
        # day from the file name: the date column changes format between files
        "instante": _step_start(day, daily["num_patamar"]),
        "patamar": daily["num_patamar"].astype(int),
        "cod_exibicao": _text(daily["cod_exibicaousina"]),
        "name": _text(daily["nom_usina"]),
        "gen_type": _text(daily["tip_geracao"]).fillna("N/D"),
        "modality": _text(daily["nom_modalidadeoperacao"]).fillna("N/D"),
        "subsystem": _text(daily["id_subsistema"]),
        "uf": _text(daily["id_estado"]),
        "programmed_mw": _num(daily["val_geracaoprogramada"]),
        "availability_mw": _num(daily["val_disponibilidade"]),
    })

    fx = pd.read_parquet(fx_path)
    fx = pd.DataFrame({
        "instante": _step_start(day, fx["num_patamar"]),
        "patamar": fx["num_patamar"].astype(int),
        "cod_pdp": _text(fx["cod_usinapdp"]),
        "name_pdp": _text(fx["nom_usinapdp"]),
        "forecast_mw": _num(fx["val_previsao"]),
        "programmed_mw": _num(fx["val_programado"]),
    })
    return daily, fx


def _series_keys(df: pd.DataFrame, unit_col: str) -> pd.Series:
    """Series of 48 scheduled-generation steps as text, to match units between files."""
    wide = df.pivot_table(index=unit_col, columns="patamar", values="programmed_mw", aggfunc="sum")
    wide = wide.reindex(columns=range(1, STEPS_PER_DAY + 1))
    wide = wide[(wide.fillna(0) > 0).sum(axis=1) >= 4]  # near-zero series do not identify the unit
    if wide.empty:  # on some days the daily schedule comes zeroed for all renewables
        return pd.Series(dtype="string", name="k").rename_axis(unit_col)
    return wide.astype(float).round(1).fillna(-1).astype(str).agg("|".join, axis=1)


def load_program(conn: Connection, start: date, end: date) -> None:
    """Daily schedule aggregates, forecast vs. scheduled by unit, and the PDP -> display code link.

    The two files identify the same unit by different codes. A unit is linked when its
    48-step scheduled series is identical in both files; each matching day is one vote,
    and `save_program_units` keeps the links with enough votes.
    """
    match_votes: dict[str, Counter] = defaultdict(Counter)
    days_seen: Counter = Counter()
    exib_attrs: dict[str, dict] = {}
    pdp_names: dict[str, str] = {}

    for day in _program_days(start, end):
        pair = _read_program_day(day)
        if pair is None:
            print(f"schedule {day.date()}: file missing")
            continue
        daily, fx = pair
        period = str(day.date())

        # aggregate by subsystem × type × modality
        agg = (
            daily.groupby(["instante", "subsystem", "gen_type", "modality"], dropna=False)
            .agg(programmed_mw=("programmed_mw", "sum"), availability_mw=("availability_mw", "sum"),
                 n_units=("cod_exibicao", "nunique"))
            .reset_index()
        )
        agg["subsystem"] = agg["subsystem"].fillna("N/D")
        daily_name = f"PROGRAMACAO_DIARIA_{day:%Y_%m_%d}.parquet"
        agg["source_id"] = register_source(conn, "program_daily", period, daily_name, len(daily))
        upsert(conn, "br.program_daily_agg", agg, ["instante", "subsystem", "gen_type", "modality"])

        # forecast vs. scheduled by unit (only intervals with some value)
        rows = fx[(fx["forecast_mw"].fillna(0) > 0) | (fx["programmed_mw"].fillna(0) > 0)]
        rows = rows.groupby(["cod_pdp", "instante"], as_index=False)[["forecast_mw", "programmed_mw"]].sum()
        fx_name = f"PROGRAMACAO_X_PREVISAO_{day:%Y_%m_%d}.parquet"
        rows["source_id"] = register_source(conn, "renewable_program", period, fx_name, len(fx))
        upsert(conn, "br.renewable_program", rows, ["cod_pdp", "instante"])

        # match votes PDP -> display code (identical scheduled series on the day)
        renewables = daily[daily["gen_type"].isin(RENEWABLE_TYPES) & (daily["modality"] != "TIPO III")]
        keys_exib = _series_keys(renewables, "cod_exibicao")
        keys_pdp = _series_keys(fx, "cod_pdp")
        unique_exib = keys_exib[~keys_exib.duplicated(keep=False)]
        matched = keys_pdp.rename("k").reset_index().merge(unique_exib.rename("k").reset_index(), on="k")
        for pdp, exib in zip(matched["cod_pdp"], matched["cod_exibicao"]):
            match_votes[pdp][exib] += 1
        days_seen.update(keys_pdp.index)
        for rec in renewables.drop_duplicates("cod_exibicao").to_dict("records"):
            exib_attrs[rec["cod_exibicao"]] = rec
        pdp_names.update(fx.drop_duplicates("cod_pdp").set_index("cod_pdp")["name_pdp"].to_dict())

        if day.day == 1:
            print(f"schedule {day:%Y-%m}: loading")
        conn.commit()

    save_program_units(conn, match_votes, days_seen, exib_attrs, pdp_names)


def save_program_units(
    conn: Connection,
    match_votes: dict[str, Counter],
    days_seen: Counter,
    exib_attrs: dict[str, dict],
    pdp_names: dict[str, str],
) -> None:
    """Rewrite br.program_unit with the PDP units linked to a display code.

    A link is kept when the most voted display code matched on at least MIN_MATCH_DAYS
    days and on at least MIN_MATCH_RATIO of the days the PDP unit appears.
    """
    known = pd.read_sql(text("""
        select distinct id_ons from br.pv_curtail
        union select distinct id_ons from br.wind_curtail
    """), conn)["id_ons"]
    known_ids = set(known)
    records = []
    for pdp, votes in match_votes.items():
        exib, n = votes.most_common(1)[0]
        if n < MIN_MATCH_DAYS or n < MIN_MATCH_RATIO * days_seen[pdp]:
            continue
        attrs = exib_attrs.get(exib, {})
        id_ons = next((c for c in (exib, f"CJU_{exib}") if c in known_ids), None)
        records.append({
            "cod_pdp": pdp, "name_pdp": pdp_names.get(pdp), "cod_exibicao": exib, "name": attrs.get("name"),
            "gen_type": attrs.get("gen_type"), "modality": attrs.get("modality"), "subsystem": attrs.get("subsystem"),
            "uf": attrs.get("uf"), "id_ons": id_ons, "days_matched": n, "days_seen": days_seen[pdp],
        })
    units = pd.DataFrame(records)
    conn.execute(text("truncate br.program_unit"))
    upsert(conn, "br.program_unit", units, ["cod_pdp"])
    print(f"linked PDP units: {len(units)}; with id_ons (solar or wind): {units['id_ons'].notna().sum()}")


# Part name on the command line (the folder under RAW) -> loader, in loading order.
LOADERS: dict[str, Callable[[Connection, date, date], None]] = {
    "balanco": load_balance,
    "hidro": load_hydro,
    "intercambio": load_interchange,
    "cmo": load_cmo,
    "eolica": load_wind_curtail,
    "carga": load_area_load,
    "programacao": load_program,
}


def load(start: date, end: date, parts: set[str]) -> None:
    """Create the tables if needed and load the selected parts, committing after each."""
    ddl = SCHEMA_SQL.read_text()
    with engine().begin() as conn:
        conn.connection.driver_connection.execute(ddl)
    with engine().connect() as conn:
        for part, loader in LOADERS.items():
            if part in parts:
                loader(conn, start, end)
                conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["download", "load"])
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--parts", default=",".join(LOADERS))
    args = parser.parse_args()
    if args.command == "download":
        download(args.start, args.end)
    else:
        load(args.start, args.end, set(args.parts.split(",")))


if __name__ == "__main__":
    main()
