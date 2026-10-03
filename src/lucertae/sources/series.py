"""Readers of the ONS open series. ONE source per series.

Every experiment that imports from here reads the same series, with the same
treatment.

DECISIONS THE DATA FORCES, valid for every consumer
---------------------------------------------------
1. `id_subsistema` comes with a trailing space in part of the yearly EAR and
   ENA files ('N ', 'S '). Without `.strip()` the pivot creates a duplicate
   column and the series of the affected subsystem is cut in half.
2. Every series is REINDEXED on the regular grid of its own step, and what the
   source does not publish becomes an explicit NaN instead of disappearing.
   Eight whole days have no CMO in the 2024-2026 window, and a `groupby` over
   the shortened series would skip them without saying so.
3. No reader interpolates. Filling a gap here would contaminate every consumer.
4. The step is NATIVE: 30 min for CMO, hourly for load and interchange, daily
   for EAR and ENA. Resampling is the consumer's decision, not the reader's.
5. `din_instante` is Brasília time, with no time zone in the file. The series
   are read as naive timestamps and compared with each other; none is
   converted to UTC.

Column names starting with `id_`, `din_`, `val_`, `ear_` and `ena_` are the
ONS column names and stay as published.
"""
import pandas as pd

from ..paths import RAW_DIR

SUBSYSTEMS = ["N", "NE", "S", "SE"]


def _read_csv(pattern: str) -> pd.DataFrame:
    """Concatenate the files in `RAW_DIR` matching `pattern`, in name order."""
    paths = sorted(RAW_DIR.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"no file in {RAW_DIR} matches {pattern}")
    frame = pd.concat([pd.read_csv(path, sep=";") for path in paths],
                      ignore_index=True)
    if "id_subsistema" in frame.columns:
        frame["id_subsistema"] = frame["id_subsistema"].astype(str).str.strip()
    return frame


def _on_regular_grid(wide: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Reindex on the regular grid between the first and the last instant."""
    grid = pd.date_range(wide.index.min(), wide.index.max(), freq=freq)
    return wide.reindex(grid).reindex(columns=SUBSYSTEMS)


def _by_subsystem(frame: pd.DataFrame, time_column: str, value_column: str,
                  freq: str) -> pd.DataFrame:
    """One column per subsystem, indexed by time on the regular grid."""
    frame["t"] = pd.to_datetime(frame[time_column])
    wide = frame.pivot_table(index="t", columns="id_subsistema",
                             values=value_column)
    return _on_regular_grid(wide, freq)


def cmo() -> pd.DataFrame:
    """Marginal operating cost (CMO), R$/MWh, by subsystem, 30 min step."""
    frame = _read_csv("cmo/cmo_*.csv")
    return _by_subsystem(frame, "din_instante", "val_cmo", "30min")


def hourly_load() -> pd.DataFrame:
    """Energy load, MWmed, by subsystem, hourly."""
    frame = _read_csv("curva_carga/CURVA_CARGA_*.csv")
    return _by_subsystem(frame, "din_instante", "val_cargaenergiahomwmed", "h")


def net_interchange() -> pd.DataFrame:
    """Net flow by subsystem, MWmed, hourly. Positive means exporter.

    The file holds the ORDERED pair origin->destination, and the two
    directions of the same pair appear in different hours. Summing without
    sign would give gross flow, which is not the quantity. The net flow is
    what leaves minus what enters.
    """
    frame = _read_csv("intercambio/INTERCAMBIO_NACIONAL_*.csv")
    frame["t"] = pd.to_datetime(frame["din_instante"])
    for column in ("id_subsistema_origem", "id_subsistema_destino"):
        frame[column] = frame[column].astype(str).str.strip()
    outflow = frame.pivot_table(index="t", columns="id_subsistema_origem",
                                values="val_intercambiomwmed", aggfunc="sum")
    inflow = frame.pivot_table(index="t", columns="id_subsistema_destino",
                               values="val_intercambiomwmed", aggfunc="sum")
    net = (outflow.reindex(columns=SUBSYSTEMS).fillna(0.0)
           - inflow.reindex(columns=SUBSYSTEMS).fillna(0.0))
    return _on_regular_grid(net, "h")


def _read_ear() -> pd.DataFrame:
    frame = _read_csv("ear_subsistema/EAR_DIARIO_SUBSISTEMA_202[456].csv")
    frame["t"] = pd.to_datetime(frame["ear_data"])
    return frame


def ear() -> pd.DataFrame:
    """Verified stored energy (EAR), % of maximum, daily, by subsystem."""
    wide = _read_ear().pivot_table(index="t", columns="id_subsistema",
                                   values="ear_verif_subsistema_percentual")
    return _on_regular_grid(wide, "D")


def ear_sin() -> pd.Series:
    """Stored energy aggregated over the SIN, % of maximum, daily.

    Ratio between the sum of the verified energy in MWmonth and the sum of the
    maximum, NOT the mean of the percentages: the reservoirs of the subsystems
    differ a lot in size, and a simple mean would weigh the North like the
    Southeast.
    """
    frame = _read_ear()
    verified = frame.pivot_table(index="t", columns="id_subsistema",
                                 values="ear_verif_subsistema_mwmes",
                                 aggfunc="sum")
    maximum = frame.pivot_table(index="t", columns="id_subsistema",
                                values="ear_max_subsistema", aggfunc="sum")
    percent = 100.0 * verified.sum(axis=1) / maximum.sum(axis=1)
    grid = pd.date_range(percent.index.min(), percent.index.max(), freq="D")
    return percent.reindex(grid)


def ena() -> pd.DataFrame:
    """Gross natural inflow energy (ENA), % of the long-term mean, daily."""
    frame = _read_csv("ena_subsistema/ENA_DIARIO_SUBSISTEMA_202[456].csv")
    return _by_subsystem(frame, "ena_data", "ena_bruta_regiao_percentualmlt",
                         "D")


def missing_days(series: pd.DataFrame | pd.Series) -> list[str]:
    """Days on which the WHOLE grid is missing. A count, not a correction."""
    if isinstance(series, pd.Series):
        missing = series.isna()
    else:
        missing = series.isna().all(axis=1)
    by_day = pd.Series(missing.to_numpy(), index=series.index).groupby(
        series.index.normalize()).all()
    return [str(day.date()) for day in by_day[by_day].index]
