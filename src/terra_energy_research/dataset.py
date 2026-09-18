"""Curtailment forecasting dataset by cluster × 30 min.

Grain: one ONS cluster (id_ons) at one 30-min instant. Solar: 05h to 19h30;
wind: all 24 hours (wind has no marked diurnal cycle).
Sources: clean.pv_curtail, clean.cluster_halfhour (sql/10_clean.sql),
clean.system_halfhour and clean.unit_plan (sql/20_clean_system.sql).
Column dictionary and assumptions: docs/dataset_curtailment.md.

    uv run python -m terra_energy_research.dataset
    uv run python -m terra_energy_research.dataset --tech wind
"""

import argparse
from pathlib import Path

import holidays
import numpy as np
import pandas as pd

from terra_energy_research.db import query

DEFAULT_OUT = Path("data/processed/curtailment_halfhour.parquet")
WIND_OUT = Path("data/processed/curtailment_wind_halfhour.parquet")

TECH = {
    "solar": dict(table="clean.pv_curtail", hours=(5, 19), out=DEFAULT_OUT, unit_kind="solar",
                  weather=("ghi", "cloud_cover")),
    "wind": dict(table="clean.wind_curtail", hours=(0, 23), out=WIND_OUT, unit_kind="wind",
                 weather=("wind_speed_100m",)),
}

# Temporal split: nothing from the future enters training
TRAIN_END = pd.Timestamp("2025-09-01")
VALID_END = pd.Timestamp("2026-03-01")

MIN_REFERENCE_MW = 1.0


def load_halfhour(tech: str) -> pd.DataFrame:
    cfg = TECH[tech]
    extra = (
        ", h.n_plants, h.n_poa_valid, h.poa_mean, h.gen_estimated_mw" if tech == "solar" else ""
    )
    join = (
        "left join clean.cluster_halfhour h using (cluster_key, instante)" if tech == "solar" else ""
    )
    cluster = "c.cluster_key," if tech == "solar" else ""
    return query(
        f"""
        select c.id_ons, {cluster} c.instante, c.uf, c.subsystem,
               c.capacity_mw, c.generation, c.availability, c.reference,
               c.reason_code, c.origin_code, c.is_curtailed, c.reference_valid, c.curtailed_mw
               {extra}
        from {cfg["table"]} c
        {join}
        where extract(hour from c.instante) between :h0 and :h1
        """,
        h0=cfg["hours"][0],
        h1=cfg["hours"][1],
    )


def load_units(tech: str) -> pd.DataFrame:
    """Static cluster attributes: connection position and voltage."""
    return query(
        """
        select u.id_ons,
               st_x(u.geom_connection) as lon,
               st_y(u.geom_connection) as lat,
               -- code = 6 substation characters + voltage (e.g. MGARI2500-A -> 500)
               substring(u.connection_code from '^.{6}(\\d{2,3})')::real as conn_voltage_kv,
               s.voltage_kv as nearest_substation_kv
        from br.ons_unit u
        left join lateral (
            select voltage_kv from br.substation s
            order by s.geom <-> u.geom_connection limit 1
        ) s on true
        where u.kind = :kind
        """,
        kind="Solar" if tech == "solar" else "Eólica",
    )


def load_unit_plan(tech: str) -> pd.DataFrame:
    return query(
        """
        select id_ons, instante, plan_forecast_mw, plan_programmed_mw, plan_cut_mw
        from clean.unit_plan
        where extract(hour from instante) between :h0 and :h1
        """,
        h0=TECH[tech]["hours"][0],
        h1=TECH[tech]["hours"][1],
    )


def load_system() -> pd.DataFrame:
    return query(
        """
        select subsystem, instante, load_programmed, load_verified, wind_programmed, wind_forecast,
               wind_plan_cut, solar_central_programmed, solar_distributed_programmed, solar_forecast,
               solar_plan_cut, hydro_programmed, thermal_programmed, cmo, wind_verified, solar_verified,
               net_load_verified
        from clean.system_halfhour
        """
    )


def load_hydro() -> pd.DataFrame:
    return query("select subsystem, day, ena_pct_mlt, ear_pct from br.hydro_daily")


def load_interchange() -> pd.DataFrame:
    """Hourly flow in canonical direction (NE->SE, N->SE, N->NE, SE->S); reverse direction becomes negative."""
    return query(
        """
        with canon(a, b) as (values ('NE', 'SE'), ('N', 'SE'), ('N', 'NE'), ('SE', 'S'))
        select c.a || '_' || c.b as pair, i.instante,
               sum(case when i.origin = c.a then i.flow_mw else -i.flow_mw end) as flow_mw
        from br.interchange_hourly i
        join canon c on (i.origin, i.destination) in ((c.a, c.b), (c.b, c.a))
        group by 1, 2
        """
    )


def load_weather(tech: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Archived ECMWF forecast (br.weather_forecast): by cluster and system aggregate."""
    cols = ", ".join(f"f.{c}" for c in TECH[tech]["weather"])
    unit = query(
        f"""
        select u.id_ons, f.lead_day, f.instante, {cols}
        from br.weather_forecast f join br.weather_cell_unit u using (cell_id)
        where u.kind = :kind
        """,
        kind=TECH[tech]["unit_kind"],
    )
    system = query(
        """
        with w as (
            select f.lead_day, f.instante, u.kind, u.subsystem, coalesce(u.capacity_mw, 0) as cap,
                   f.ghi, f.wind_speed_100m / 3.6 as v  -- km/h -> m/s
            from br.weather_forecast f join br.weather_cell_unit u using (cell_id)
        )
        select lead_day, instante,
               sum(ghi * cap) filter (where kind = 'solar') / nullif(sum(cap) filter (where kind = 'solar'), 0) as sin_solar_ghi,
               sum(v * cap) filter (where kind = 'wind' and subsystem = 'NE')
                   / nullif(sum(cap) filter (where kind = 'wind' and subsystem = 'NE'), 0) as ne_wind_speed,
               -- generic power curve: 0 below 3 m/s, cubic up to 12 m/s, 1 up to 25 m/s
               sum(cap * case when v < 3 or v >= 25 then 0 when v < 12 then power((v - 3) / 9, 3) else 1 end)
                   filter (where kind = 'wind' and subsystem = 'NE')
                   / nullif(sum(cap) filter (where kind = 'wind' and subsystem = 'NE'), 0) as ne_wind_cf
        from w group by 1, 2
        """
    )
    return unit, system


def add_weather(df: pd.DataFrame, unit: pd.DataFrame, system: pd.DataFrame) -> pd.DataFrame:
    """wx{N}_*: forecast issued N×24h before (N=1 day ahead, N=2 two days ahead). Hourly, repeated in the 30-min intervals."""
    df["_hour"] = df["instante"].dt.floor("h")
    unit_cols = [c for c in ("ghi", "cloud_cover", "wind_speed_100m") if c in unit.columns]
    for frame, keys, cols in ((unit, ["id_ons"], unit_cols),
                              (system, [], ["sin_solar_ghi", "ne_wind_speed", "ne_wind_cf"])):
        frame = frame.assign(instante=pd.to_datetime(frame["instante"]))
        wide = frame.pivot_table(index=[*keys, "instante"], columns="lead_day", values=cols)
        wide.columns = [
            f"wx{lead}_" + col.replace("cloud_cover", "cloud").replace("wind_speed_100m", "wind_speed")
            for col, lead in wide.columns
        ]
        wide = wide.reset_index().rename(columns={"instante": "_hour"})
        df = df.merge(wide, on=[*keys, "_hour"], how="left")
    return df.drop(columns="_hour")


def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    df["y_is_curtailed"] = df["is_curtailed"].astype("int8")
    df["y_curtailed_mw"] = df["curtailed_mw"]
    usable = df["reference_valid"] & (df["reference"] >= MIN_REFERENCE_MW)
    df["y_curtailed_frac"] = (df["curtailed_mw"] / df["reference"]).where(usable).clip(0, 1)
    return df


def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    t = df["instante"]
    br_holidays = holidays.Brazil(years=range(t.dt.year.min(), t.dt.year.max() + 1))
    df["hour"] = (t.dt.hour + t.dt.minute / 60).astype("float32")
    df["dow"] = t.dt.dayofweek.astype("int8")
    df["month"] = t.dt.month.astype("int8")
    df["doy"] = t.dt.dayofyear.astype("int16")
    df["is_weekend"] = (df["dow"] >= 5).astype("int8")
    df["is_holiday"] = t.dt.date.isin(set(br_holidays)).astype("int8")
    df["trend_days"] = ((t - t.min()).dt.total_seconds() / 86400).astype("float32")
    return df


def add_static(df: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(units, on="id_ons", how="left")
    df["conn_voltage_kv"] = df["conn_voltage_kv"].fillna(df["nearest_substation_kv"])
    # 4 clusters are not in ons_unit: capacity estimated from the p99 of the reference
    p99 = df.groupby("id_ons")["reference"].transform(lambda s: s.quantile(0.99))
    df["capacity_mw_est"] = df["capacity_mw"].fillna(p99).astype("float32")
    return df


def add_oracle(df: pd.DataFrame) -> pd.DataFrame:
    """Features from the same instant, known only after the fact.

    They stand in for weather/generation forecasts that would exist in real operation.
    Use with care: performance with them is a ceiling, not a realistic estimate.
    """
    ref = df["reference"].where(df["reference_valid"])
    if "poa_mean" in df:  # irradiance only exists for solar
        df["oracle_poa_mean"] = df["poa_mean"].astype("float32")
    df["oracle_reference_cf"] = (ref / df["capacity_mw_est"]).clip(0, 1.5).astype("float32")
    df["_ref"] = ref
    df["oracle_sys_reference_mw"] = df.groupby("instante")["_ref"].transform("sum").astype("float32")
    df["oracle_sub_reference_mw"] = (
        df.groupby(["subsystem", "instante"])["_ref"].transform("sum").astype("float32")
    )
    return df.drop(columns="_ref")


def _system_features(sys: pd.DataFrame) -> pd.DataFrame:
    """Features by subsystem × instant; the 'SIN' row sums the subsystems."""
    cols = [c for c in sys.columns if c not in ("subsystem", "instante")]
    # where the day's schedule exists, a subsystem without wind/solar units has value 0, not null
    has_program = sys.groupby("instante")["wind_forecast"].transform(lambda v: v.notna().any())
    for col in ("wind_forecast", "wind_plan_cut", "solar_forecast", "solar_plan_cut", "solar_distributed_programmed"):
        sys[col] = sys[col].mask(has_program & sys[col].isna(), 0)
    sin = sys.groupby("instante", as_index=False)[cols].sum(min_count=1).assign(subsystem="SIN")
    sys = pd.concat([sys, sin], ignore_index=True)
    out = sys[["subsystem", "instante"]].copy()
    # forecasts and scheduled load (ex-ante, no dispatch decision)
    out["load_programmed"] = sys["load_programmed"]
    out["wind_forecast"] = sys["wind_forecast"]
    out["solar_forecast"] = sys["solar_forecast"]
    out["solar_distributed_programmed"] = sys["solar_distributed_programmed"]
    out["net_load_forecast"] = (
        sys["load_programmed"] - sys["wind_forecast"].fillna(0) - sys["solar_forecast"].fillna(0)
        - sys["solar_distributed_programmed"].fillna(0)
    ).where(sys["wind_forecast"].notna())
    out["vre_share_forecast"] = 1 - out["net_load_forecast"] / sys["load_programmed"]
    # dispatch plan (ex-ante, already embeds the ONS curtailment decision)
    out["plan_wind_cut_frac"] = sys["wind_plan_cut"] / sys["wind_forecast"].where(sys["wind_forecast"] > 1)
    out["plan_solar_cut_frac"] = sys["solar_plan_cut"] / sys["solar_forecast"].where(sys["solar_forecast"] > 1)
    out["plan_hydro_programmed"] = sys["hydro_programmed"]
    out["plan_thermal_programmed"] = sys["thermal_programmed"]
    # verified (ex-post)
    out["cmo"] = sys["cmo"]
    out["load_verified"] = sys["load_verified"]
    out["wind_verified"] = sys["wind_verified"]
    out["net_load_verified"] = sys["net_load_verified"]
    return out


VERIFIED = ["load_verified", "wind_verified", "net_load_verified", "cmo"]


def add_system(df: pd.DataFrame, unit_plan: pd.DataFrame, sys: pd.DataFrame) -> pd.DataFrame:
    """Cluster D-1 plan and features for the cluster's subsystem (sub_) and the SIN (sin_).

    Prefixes: sub_/sin_ forecasts and scheduled load; plan_ D-1 plan decisions;
    lag1d_ verified values from D-1; oracle_ verified values from the same instant.
    """
    unit_plan = unit_plan.assign(instante=pd.to_datetime(unit_plan["instante"]))
    unit_plan["plan_cut_frac"] = (
        unit_plan["plan_cut_mw"] / unit_plan["plan_forecast_mw"].where(unit_plan["plan_forecast_mw"] > 1)
    ).clip(0, 1)
    df = df.merge(unit_plan, on=["id_ons", "instante"], how="left")

    feats = _system_features(sys.assign(instante=pd.to_datetime(sys["instante"])))
    ex_ante = [c for c in feats.columns if c not in ("subsystem", "instante", *VERIFIED)]

    df["subsystem"] = df["subsystem"].astype(str)
    for scope in ("sub", "sin"):
        part = feats[feats["subsystem"] == "SIN"] if scope == "sin" else feats[feats["subsystem"] != "SIN"]
        keys = ["subsystem", "instante"] if scope == "sub" else ["instante"]
        part = part[[*keys, *ex_ante, *VERIFIED]]

        renamed = {
            c: f"plan_{scope}_{c.removeprefix('plan_')}" if c.startswith("plan_") else f"{scope}_{c}"
            for c in ex_ante
        }
        renamed |= {c: f"oracle_{scope}_{c}" for c in VERIFIED}
        df = df.merge(part.rename(columns=renamed), on=keys, how="left")

        for days in (1, 2):
            lag = part[[*keys, *VERIFIED]].rename(columns={c: f"lag{days}d_{scope}_{c}" for c in VERIFIED})
            lag["instante"] += pd.Timedelta(days=days)
            df = df.merge(lag, on=keys, how="left")
    return df


def add_literature_features(df: pd.DataFrame, sys: pd.DataFrame, hydro: pd.DataFrame, flows: pd.DataFrame,
                            tech: str = "solar") -> pd.DataFrame:
    """Literature-motivated features (see reports/literature_curtailment.md). All known on D-1.

    - Vieira et al. (2026): MMGD is the main predictor of energy-balance curtailment; load is protective;
      NE renewable generation explains reliability curtailment.
    - Titz et al. (2023): interregional interchange and hydro explain congestion.
    - Volt Robotics (2026): Sunday mornings with strong wind are the critical point.
    """
    day = df["instante"].dt.normalize()
    # solar: midday window, where curtailment happens; wind: the whole day
    daytime = df["hour"].between(9, 15) if tech == "solar" else pd.Series(True, index=df.index)

    # whole-day plan, published at once the day ahead
    unit_day = df[daytime].groupby(["id_ons", day[daytime]])[["plan_cut_mw", "plan_forecast_mw"]].sum(min_count=1)
    unit_day["plan_day_cut_frac"] = unit_day["plan_cut_mw"] / unit_day["plan_forecast_mw"].where(unit_day["plan_forecast_mw"] > 1)
    df = df.assign(day=day).merge(
        unit_day[["plan_day_cut_frac"]].rename_axis(["id_ons", "day"]).reset_index(), on=["id_ons", "day"], how="left"
    )

    sys = sys.assign(instante=pd.to_datetime(sys["instante"]))
    sys["net_load_forecast"] = (
        sys["load_programmed"] - sys["wind_forecast"].fillna(0) - sys["solar_forecast"].fillna(0)
        - sys["solar_distributed_programmed"].fillna(0)
    ).where(sys.groupby("instante")["wind_forecast"].transform(lambda v: v.notna().any()))
    wide = sys.pivot_table(index="instante", columns="subsystem",
                           values=["net_load_forecast", "solar_distributed_programmed", "load_programmed",
                                   "wind_forecast", "solar_forecast", "wind_plan_cut", "solar_plan_cut",
                                   "load_verified", "cmo"], aggfunc="mean")
    reg = pd.DataFrame(index=wide.index)
    sin = {c: wide[c].sum(axis=1, min_count=1) for c in wide.columns.levels[0]}
    reg["lit_sin_mmgd_share"] = sin["solar_distributed_programmed"] / sin["load_programmed"]
    reg["lit_ne_net_load_forecast"] = wide[("net_load_forecast", "NE")]
    reg["lit_se_net_load_forecast"] = wide[("net_load_forecast", "SE")]
    reg["lit_ne_vre_forecast"] = wide[("wind_forecast", "NE")].fillna(0) + wide[("solar_forecast", "NE")].fillna(0)
    sin_net = sin["net_load_forecast"]
    reg["lit_sin_net_load_ramp_1h"] = sin_net - sin_net.shift(freq="1h").reindex(sin_net.index)
    net_day = sin_net[sin_net.index.hour.isin(range(9, 16))].groupby(sin_net.index[sin_net.index.hour.isin(range(9, 16))].normalize())
    reg["lit_sin_net_load_daymin"] = net_day.min().reindex(sin_net.index.normalize()).to_numpy()
    reg["lit_sin_net_load_above_daymin"] = sin_net - reg["lit_sin_net_load_daymin"]
    day_cut = (sin["solar_plan_cut"] + sin["wind_plan_cut"])[sin_net.index.hour.isin(range(9, 16))]
    day_fc = (sin["solar_forecast"] + sin["wind_forecast"])[sin_net.index.hour.isin(range(9, 16))]
    frac = day_cut.groupby(day_cut.index.normalize()).sum() / day_fc.groupby(day_fc.index.normalize()).sum()
    reg["plan_day_sin_vre_cut_frac"] = frac.reindex(sin_net.index.normalize()).to_numpy()
    # scheduled-load error on D-1 (verified - scheduled), same time of day
    load_err = (sin["load_verified"] - sin["load_programmed"]) / sin["load_programmed"]
    reg["lag1d_sin_load_forecast_error"] = load_err.shift(freq="1D").reindex(sin_net.index)
    # SIN CMO (mean of the subsystems): level, daily minimum and share of intervals at the floor, on D-1
    cmo = wide["cmo"].mean(axis=1)
    cmo_day = cmo.groupby(cmo.index.normalize())
    # the CMO level already comes from add_system (lag1d_sin_cmo); here only the daily statistics
    for name, series in (("cmo_daymin", cmo_day.min().reindex(cmo.index.normalize()).set_axis(cmo.index)),
                         ("cmo_floor_share", cmo_day.apply(lambda v: (v <= 20).mean()).reindex(cmo.index.normalize()).set_axis(cmo.index))):
        reg[f"lag1d_sin_{name}"] = series.shift(freq="1D").reindex(cmo.index)
    df = df.merge(reg.reset_index(), on="instante", how="left")

    # verified hydrology on D-1
    hydro = hydro.assign(day=pd.to_datetime(hydro["day"]) + pd.Timedelta(days=1))
    hw = hydro.pivot_table(index="day", columns="subsystem", values=["ena_pct_mlt", "ear_pct"])
    hw.columns = [f"lag1d_{sub.lower()}_{var}" for var, sub in hw.columns]
    df = df.merge(hw.reset_index(), on="day", how="left")

    # verified interchange on D-1, same time of day (hourly -> 30 min)
    flows = flows.assign(instante=pd.to_datetime(flows["instante"]))
    fw = flows.pivot_table(index="instante", columns="pair", values="flow_mw")
    fw = pd.concat([fw, fw.set_axis(fw.index + pd.Timedelta(minutes=30))]).sort_index()
    fw.index = fw.index + pd.Timedelta(days=1)
    fw.columns = [f"lag1d_flow_{c.lower()}" for c in fw.columns]
    df = df.merge(fw.reset_index(), on="instante", how="left")
    return df.drop(columns="day")


def add_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Lags of 1, 2 and 7 days.

    Day-ahead forecast (issued after the close of D-1): lag1d, lag7d, roll7d.
    Two-days-ahead forecast (issued after the close of D-2): lag2d, lag7d, roll7d_d2.
    """
    unit = df[["id_ons", "instante", "y_is_curtailed", "y_curtailed_frac"]]
    for days in (1, 2, 7):
        lagged = unit.assign(instante=unit["instante"] + pd.Timedelta(days=days)).rename(
            columns={
                "y_is_curtailed": f"lag{days}d_is_curtailed",
                "y_curtailed_frac": f"lag{days}d_curtailed_frac",
            }
        )
        df = df.merge(lagged, on=["id_ons", "instante"], how="left")

    system = (
        df.assign(_cut=df["curtailed_mw"], _ref=df["reference"].where(df["reference_valid"]))
        .groupby("instante")
        .agg(sys_share_curtailed=("y_is_curtailed", "mean"), _cut=("_cut", "sum"), _ref=("_ref", "sum"))
    )
    system["sys_curtailed_frac"] = system["_cut"] / system["_ref"].where(system["_ref"] > 0)
    system = system[["sys_share_curtailed", "sys_curtailed_frac"]].reset_index()
    for days in (1, 2):
        lagged = system.assign(instante=system["instante"] + pd.Timedelta(days=days))
        df = df.merge(lagged.add_prefix(f"lag{days}d_").rename(columns={f"lag{days}d_instante": "instante"}), on="instante", how="left")

    # Daily moving average over the previous 7 days (D-7 .. D-1), by cluster and for the system
    df["day"] = df["instante"].dt.normalize()
    valid = df.assign(_ref=df["reference"].where(df["reference_valid"] & df["curtailed_mw"].notna()))
    daily = valid.pivot_table(index="day", columns="id_ons", values=["curtailed_mw", "_ref"], aggfunc="sum", observed=True)
    daily = daily.asfreq("D")
    unit_frac = daily["curtailed_mw"] / daily["_ref"].where(daily["_ref"] > 0)
    sys_frac = daily["curtailed_mw"].sum(axis=1) / daily["_ref"].sum(axis=1).where(lambda s: s > 0)
    for shift, suffix in ((1, ""), (2, "_d2")):
        roll_unit = (
            unit_frac.rolling(7, min_periods=3).mean().shift(shift)
            .stack(future_stack=True)
            .rename(f"roll7d{suffix}_curtailed_frac")
            .reset_index()
        )
        roll_sys = sys_frac.rolling(7, min_periods=3).mean().shift(shift).rename(f"sys_roll7d{suffix}_curtailed_frac").reset_index()
        df = df.merge(roll_unit, on=["day", "id_ons"], how="left")
        df = df.merge(roll_sys, on="day", how="left")
    return df.drop(columns="day")


def add_split(df: pd.DataFrame) -> pd.DataFrame:
    df["split"] = np.select(
        [df["instante"] < TRAIN_END, df["instante"] < VALID_END],
        ["train", "valid"],
        default="test",
    )
    return df


def build(tech: str = "solar") -> pd.DataFrame:
    df = load_halfhour(tech)
    df["instante"] = pd.to_datetime(df["instante"])
    df = add_targets(df)
    df = add_calendar(df)
    df = add_static(df, load_units(tech))
    df = add_oracle(df)
    system = load_system()
    df = add_system(df, load_unit_plan(tech), system)
    df = add_literature_features(df, system, load_hydro(), load_interchange(), tech)
    df = add_weather(df, *load_weather(tech))
    df = add_lags(df)
    df = add_split(df)
    if "cluster_key" not in df:
        df["cluster_key"] = pd.NA
    for col in ("id_ons", "uf", "subsystem", "reason_code", "origin_code", "split"):
        df[col] = df[col].astype("category")
    return df.sort_values(["id_ons", "instante"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tech", choices=tuple(TECH), default="solar")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    df = build(args.tech)
    args.out = args.out or TECH[args.tech]["out"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)

    print(f"{len(df):,} rows, {df['id_ons'].nunique()} clusters -> {args.out}")
    print(df.groupby("split", observed=True).agg(
        rows=("instante", "size"),
        start=("instante", "min"),
        end=("instante", "max"),
        pct_curtailed=("y_is_curtailed", "mean"),
        mean_frac=("y_curtailed_frac", "mean"),
    ))


if __name__ == "__main__":
    main()
