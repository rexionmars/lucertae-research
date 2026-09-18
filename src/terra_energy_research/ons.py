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

    uv run python -m terra_energy_research.ons download --start 2024-04-01 --end 2026-08-31
    uv run python -m terra_energy_research.ons load     --start 2024-04-01 --end 2026-08-31
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from terra_energy_research.db import engine

RAW = Path("data/raw/ons")
S3 = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset"
API = "https://apicarga.ons.org.br/prd"

LOAD_AREAS = ("SECO", "S", "NE", "N")
LOAD_ENDPOINTS = {"cargaprogramada": "load_programmed", "cargaverificada": "load_verified"}
PROGRAM_START = date(2024, 10, 1)  # first daily file published

RENEWABLE_TYPES = ("SOLAR", "EÓLICA")
# PDP -> display code link is only accepted if it matches on most of the days the unit
# appears; small series can coincide by chance between different plants.
MIN_MATCH_DAYS, MIN_MATCH_RATIO = 5, 0.5


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _fetch(url: str, dest: Path, overwrite: bool = False) -> str:
    if dest.exists() and not overwrite:
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
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
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(dest)
    return "ok"


def _months(start: date, end: date) -> list[pd.Period]:
    return list(pd.period_range(start, end, freq="M"))


def download_jobs(start: date, end: date) -> list[tuple[str, Path, bool]]:
    """(url, destination, overwrite). Files for the current period are always re-downloaded."""
    today = date.today()
    jobs = []
    for year in range(start.year, end.year + 1):
        for folder, prefix, dest in (
            ("balanco_energia_subsistema_ho", "BALANCO_ENERGIA_SUBSISTEMA", "balanco"),
            ("ena_subsistema_di", "ENA_DIARIO_SUBSISTEMA", "hidro"),
            ("ear_subsistema_di", "EAR_DIARIO_SUBSISTEMA", "hidro"),
            ("intercambio_nacional_ho", "INTERCAMBIO_NACIONAL", "intercambio"),
            ("cmo_tm", "CMO_SEMIHORARIO", "cmo"),
        ):
            name = f"{prefix}_{year}.parquet"
            jobs.append((f"{S3}/{folder}/{name}", RAW / dest / name, year == today.year))
    for month in _months(start, end):
        first, last = month.start_time.date(), min(month.end_time.date(), end)
        current = month == pd.Period(today, "M")
        for endpoint in LOAD_ENDPOINTS:
            for area in LOAD_AREAS:
                url = f"{API}/{endpoint}?dat_inicio={first}&dat_fim={last}&cod_areacarga={area}"
                jobs.append((url, RAW / "carga" / f"{endpoint}_{area}_{month}.json", current))
    for month in _months(start, end):
        name = f"RESTRICAO_COFF_EOLICA_{month.strftime('%Y_%m')}.parquet"
        jobs.append((f"{S3}/restricao_coff_eolica_tm/{name}", RAW / "eolica" / name, month == pd.Period(today, "M")))
    for day in pd.date_range(max(start, PROGRAM_START), end, freq="D"):
        stamp = day.strftime("%Y_%m_%d")
        for dataset, prefix in (("programacao_diaria", "PROGRAMACAO_DIARIA"), ("programacao_x_previsao", "PROGRAMACAO_X_PREVISAO")):
            name = f"{prefix}_{stamp}.parquet"
            jobs.append((f"{S3}/{dataset}/{name}", RAW / dataset / name, False))
    return jobs


def download(start: date, end: date, workers: int = 8) -> None:
    jobs = download_jobs(start, end)
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda j: (j[1], _fetch(*j)), jobs))
    status = Counter(r for _, r in results)
    print(f"{len(jobs)} files: {dict(status)}")
    for path, result in results:
        if result not in ("ok", "cached"):
            print(f"  {result}: {path.name}")


# ---------------------------------------------------------------------------
# Loading into the database
# ---------------------------------------------------------------------------

def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.strip().str.replace(",", ".", regex=False), errors="coerce")


def _register_source(conn, dataset: str, period: str, filename: str, row_count: int) -> int:
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


def _upsert(conn, table: str, df: pd.DataFrame, key: list[str]) -> None:
    """COPY into a temp table and INSERT ... ON CONFLICT DO UPDATE on the non-key columns."""
    if df.empty:
        return
    cols = list(df.columns)
    raw = conn.connection.driver_connection
    with raw.cursor() as cur:
        cur.execute(f"create temp table _stage (like {table} including defaults) on commit drop")
        with cur.copy(f"copy _stage ({', '.join(cols)}) from stdin") as copy:
            for row in df.itertuples(index=False, name=None):
                copy.write_row([None if pd.isna(v) else v for v in row])
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key)
        cur.execute(
            f"insert into {table} ({', '.join(cols)}) select {', '.join(cols)} from _stage "
            f"on conflict ({', '.join(key)}) do update set {updates}"
        )
        cur.execute("drop table _stage")


def load_balance(conn, start: date, end: date) -> None:
    for year in range(start.year, end.year + 1):
        path = RAW / "balanco" / f"BALANCO_ENERGIA_SUBSISTEMA_{year}.parquet"
        df = pd.read_parquet(path)
        df = pd.DataFrame({
            "subsystem": df["id_subsistema"].astype("string").str.strip(),
            "instante": pd.to_datetime(df["din_instante"]),
            "hydro": _num(df["val_gerhidraulica"]),
            "thermal": _num(df["val_gertermica"]),
            "wind": _num(df["val_gereolica"]),
            "solar": _num(df["val_gersolar"]),
            "load": _num(df["val_carga"]),
            "interchange": _num(df["val_intercambio"]),
        })
        df = df[(df["instante"] >= pd.Timestamp(start)) & (df["instante"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
        df["source_id"] = _register_source(conn, "subsystem_balance", str(year), path.name, len(df))
        _upsert(conn, "br.subsystem_balance_hourly", df, ["subsystem", "instante"])
        print(f"balance {year}: {len(df):,} rows")


def load_hydro(conn, start: date, end: date) -> None:
    for year in range(start.year, end.year + 1):
        ena = pd.read_parquet(RAW / "hidro" / f"ENA_DIARIO_SUBSISTEMA_{year}.parquet")
        ear = pd.read_parquet(RAW / "hidro" / f"EAR_DIARIO_SUBSISTEMA_{year}.parquet")
        ena = pd.DataFrame({
            "subsystem": ena["id_subsistema"].astype("string").str.strip(),
            "day": pd.to_datetime(ena["ena_data"]).dt.date,
            "ena_mwmed": _num(ena["ena_bruta_regiao_mwmed"]),
            "ena_pct_mlt": _num(ena["ena_bruta_regiao_percentualmlt"]),
        })
        ear = pd.DataFrame({
            "subsystem": ear["id_subsistema"].astype("string").str.strip(),
            "day": pd.to_datetime(ear["ear_data"]).dt.date,
            "ear_mwmes": _num(ear["ear_verif_subsistema_mwmes"]),
            "ear_pct": _num(ear["ear_verif_subsistema_percentual"]),
        })
        df = ena.merge(ear, on=["subsystem", "day"], how="outer")
        df = df[(df["day"] >= start) & (df["day"] <= end)]
        df["source_id"] = _register_source(conn, "hydro_daily", str(year), f"ENA/EAR_DIARIO_SUBSISTEMA_{year}.parquet", len(df))
        _upsert(conn, "br.hydro_daily", df, ["subsystem", "day"])
        print(f"hydrology {year}: {len(df):,} rows")


def load_interchange(conn, start: date, end: date) -> None:
    for year in range(start.year, end.year + 1):
        path = RAW / "intercambio" / f"INTERCAMBIO_NACIONAL_{year}.parquet"
        raw = pd.read_parquet(path)
        df = pd.DataFrame({
            "origin": raw["id_subsistema_origem"].astype("string").str.strip(),
            "destination": raw["id_subsistema_destino"].astype("string").str.strip(),
            "instante": pd.to_datetime(raw["din_instante"]),
            "flow_mw": _num(raw["val_intercambiomwmed"]),
        })
        df = df[(df["instante"] >= pd.Timestamp(start)) & (df["instante"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
        df["source_id"] = _register_source(conn, "interchange", str(year), path.name, len(df))
        _upsert(conn, "br.interchange_hourly", df, ["origin", "destination", "instante"])
        print(f"interchange {year}: {len(df):,} rows")


def load_cmo(conn, start: date, end: date) -> None:
    for year in range(start.year, end.year + 1):
        path = RAW / "cmo" / f"CMO_SEMIHORARIO_{year}.parquet"
        raw = pd.read_parquet(path)
        df = pd.DataFrame({
            "subsystem": raw["id_subsistema"].astype("string").str.strip(),
            "instante": pd.to_datetime(raw["din_instante"]),
            "cmo": _num(raw["val_cmo"]),
        })
        df = df[(df["instante"] >= pd.Timestamp(start)) & (df["instante"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
        df["source_id"] = _register_source(conn, "cmo", str(year), path.name, len(df))
        _upsert(conn, "br.cmo_halfhour", df, ["subsystem", "instante"])
        print(f"CMO {year}: {len(df):,} rows")


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


def load_wind_curtail(conn, start: date, end: date) -> None:
    for month in _months(start, end):
        path = RAW / "eolica" / f"RESTRICAO_COFF_EOLICA_{month.strftime('%Y_%m')}.parquet"
        if not path.exists():
            print(f"wind {month}: file missing")
            continue
        raw = pd.read_parquet(path)
        df = raw[list(WIND_COLUMNS)].rename(columns=WIND_COLUMNS)
        df["instante"] = pd.to_datetime(df["instante"])
        for col in ("generation", "generation_limited", "availability", "reference", "reference_final", "unrealized_mw"):
            df[col] = _num(df[col])
        for col in ("minutes_rel", "minutes_cnf", "minutes_ene", "minutes_restriction"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        for col in ("id_ons", "ceg", "subsystem", "uf", "plant_name", "connection_code", "operator", "reason_code", "origin_code"):
            df[col] = df[col].astype("string").str.strip()
        df = df.drop_duplicates(["id_ons", "instante"], keep="last")
        df["source_id"] = _register_source(conn, "wind_curtailment", str(month), path.name, len(df))
        _upsert(conn, "br.wind_curtail", df, ["id_ons", "instante"])
        print(f"wind {month}: {len(df):,} rows")


def load_carga(conn, start: date, end: date) -> None:
    for month in _months(start, end):
        for endpoint, column in LOAD_ENDPOINTS.items():
            frames = []
            for area in LOAD_AREAS:
                path = RAW / "carga" / f"{endpoint}_{area}_{month}.json"
                frames.append(pd.DataFrame(json.loads(path.read_text())))
            df = pd.concat(frames, ignore_index=True)
            # din_referenciautc marks the END of the interval in UTC -> start in Brasília time
            utc_end = pd.to_datetime(df["din_referenciautc"], utc=True)
            out = pd.DataFrame({
                "area": df["cod_areacarga"],
                "instante": (utc_end - pd.Timedelta(minutes=30)).dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None),
            })
            if endpoint == "cargaprogramada":
                out["load_programmed"] = _num(df["val_cargaglobalprogramada"])
            else:
                out["load_verified"] = _num(df["val_cargaglobal"])
                out["load_verified_cons"] = _num(df["val_cargaglobalcons"])
                out["load_verified_no_mmgd"] = _num(df["val_cargaglobalsmmgd"])
                out["load_mmgd"] = _num(df["val_cargammgd"])
                out["load_supervised"] = _num(df["val_cargasupervisionada"])
                out["load_unsupervised"] = _num(df["val_carganaosupervisionada"])
            out = out.drop_duplicates(["area", "instante"], keep="last")
            source_col = "source_programmed_id" if endpoint == "cargaprogramada" else "source_verified_id"
            out[source_col] = _register_source(conn, column, str(month), f"{endpoint}_{month}.json", len(out))
            _upsert(conn, "br.load_halfhour", out, ["area", "instante"])
        print(f"load {month}: ok")


def _read_program_day(day: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    stamp = day.strftime("%Y_%m_%d")
    daily_path = RAW / "programacao_diaria" / f"PROGRAMACAO_DIARIA_{stamp}.parquet"
    fx_path = RAW / "programacao_x_previsao" / f"PROGRAMACAO_X_PREVISAO_{stamp}.parquet"
    if not (daily_path.exists() and fx_path.exists()):
        return None

    daily = pd.read_parquet(daily_path)
    daily = pd.DataFrame({
        # day from the file name: the date column changes format between files
        "instante": day.normalize() + pd.to_timedelta((daily["num_patamar"].astype(int) - 1) * 30, unit="min"),
        "patamar": daily["num_patamar"].astype(int),
        "cod_exibicao": daily["cod_exibicaousina"].astype("string").str.strip(),
        "name": daily["nom_usina"].astype("string").str.strip(),
        "gen_type": daily["tip_geracao"].astype("string").str.strip().fillna("N/D"),
        "modality": daily["nom_modalidadeoperacao"].astype("string").str.strip().fillna("N/D"),
        "subsystem": daily["id_subsistema"].astype("string").str.strip(),
        "uf": daily["id_estado"].astype("string").str.strip(),
        "programmed_mw": _num(daily["val_geracaoprogramada"]),
        "availability_mw": _num(daily["val_disponibilidade"]),
    })

    fx = pd.read_parquet(fx_path)
    fx = pd.DataFrame({
        "instante": day.normalize() + pd.to_timedelta((fx["num_patamar"].astype(int) - 1) * 30, unit="min"),
        "patamar": fx["num_patamar"].astype(int),
        "cod_pdp": fx["cod_usinapdp"].astype("string").str.strip(),
        "name_pdp": fx["nom_usinapdp"].astype("string").str.strip(),
        "forecast_mw": _num(fx["val_previsao"]),
        "programmed_mw": _num(fx["val_programado"]),
    })
    return daily, fx


def _series_keys(df: pd.DataFrame, unit_col: str) -> pd.Series:
    """Series of 48 scheduled-generation steps as text, to match units between files."""
    wide = df.pivot_table(index=unit_col, columns="patamar", values="programmed_mw", aggfunc="sum")
    wide = wide.reindex(columns=range(1, 49))
    wide = wide[(wide.fillna(0) > 0).sum(axis=1) >= 4]  # near-zero series do not identify the unit
    if wide.empty:  # on some days the daily schedule comes zeroed for all renewables
        return pd.Series(dtype="string", name="k").rename_axis(unit_col)
    return wide.astype(float).round(1).fillna(-1).astype(str).agg("|".join, axis=1)


def load_program(conn, start: date, end: date) -> None:
    match_votes: dict[str, Counter] = defaultdict(Counter)
    days_seen: Counter = Counter()
    exib_attrs: dict[str, dict] = {}
    pdp_names: dict[str, str] = {}

    for day in pd.date_range(max(start, PROGRAM_START), end, freq="D"):
        pair = _read_program_day(day)
        if pair is None:
            print(f"schedule {day.date()}: file missing")
            continue
        daily, fx = pair

        # aggregate by subsystem × type × modality
        agg = (
            daily.groupby(["instante", "subsystem", "gen_type", "modality"], dropna=False)
            .agg(programmed_mw=("programmed_mw", "sum"), availability_mw=("availability_mw", "sum"),
                 n_units=("cod_exibicao", "nunique"))
            .reset_index()
        )
        agg["subsystem"] = agg["subsystem"].fillna("N/D")
        agg["source_id"] = _register_source(conn, "program_daily", str(day.date()), f"PROGRAMACAO_DIARIA_{day:%Y_%m_%d}.parquet", len(daily))
        _upsert(conn, "br.program_daily_agg", agg, ["instante", "subsystem", "gen_type", "modality"])

        # forecast vs. scheduled by unit (only intervals with some value)
        rows = fx[(fx["forecast_mw"].fillna(0) > 0) | (fx["programmed_mw"].fillna(0) > 0)]
        rows = rows.groupby(["cod_pdp", "instante"], as_index=False)[["forecast_mw", "programmed_mw"]].sum()
        rows["source_id"] = _register_source(conn, "renewable_program", str(day.date()), f"PROGRAMACAO_X_PREVISAO_{day:%Y_%m_%d}.parquet", len(fx))
        _upsert(conn, "br.renewable_program", rows, ["cod_pdp", "instante"])

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


def save_program_units(conn, match_votes, days_seen, exib_attrs, pdp_names) -> None:
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
    _upsert(conn, "br.program_unit", units, ["cod_pdp"])
    print(f"linked PDP units: {len(units)}; with id_ons (solar or wind): {units['id_ons'].notna().sum()}")


def load(start: date, end: date, parts: set[str]) -> None:
    ddl = Path("sql/05_ons_system.sql").read_text()
    with engine().begin() as conn:
        conn.connection.driver_connection.execute(ddl)
    with engine().connect() as conn:
        if "balanco" in parts:
            load_balance(conn, start, end)
            conn.commit()
        if "hidro" in parts:
            load_hydro(conn, start, end)
            conn.commit()
        if "intercambio" in parts:
            load_interchange(conn, start, end)
            conn.commit()
        if "cmo" in parts:
            load_cmo(conn, start, end)
            conn.commit()
        if "eolica" in parts:
            load_wind_curtail(conn, start, end)
            conn.commit()
        if "carga" in parts:
            load_carga(conn, start, end)
            conn.commit()
        if "programacao" in parts:
            load_program(conn, start, end)
            conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["download", "load"])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 4, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 31))
    parser.add_argument("--parts", default="balanco,hidro,intercambio,cmo,eolica,carga,programacao")
    args = parser.parse_args()
    if args.command == "download":
        download(args.start, args.end)
    else:
        load(args.start, args.end, set(args.parts.split(",")))


if __name__ == "__main__":
    main()
