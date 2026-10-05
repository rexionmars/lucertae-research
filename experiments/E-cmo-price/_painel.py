"""Build the subsystem-by-half-hour panel and its next-day features.

This module is separate from the runner because leakage control C3 must call the
same function with source series truncated at issue time. If any feature used
future information, truncation would change its value and the control would
fail.

Feature suffixes identify the source day relative to target day D: `_d1` means
the full day D-1; `_l1` means the same half-hour on D-1.
"""
import numpy as np
import pandas as pd

from _comum import (CMO_FLOOR_THRESHOLD, CMO_LAG_DAYS, HYDRO_LAG_DAYS,
                    LOAD_LAG_DAYS, SUBSYSTEMS)


def _daily_summary(half_hourly_series):
    """Summarize each day of a half-hourly series by mean, min, max, and floor fraction."""
    day = half_hourly_series.index.normalize()
    grouped = half_hourly_series.groupby(day)
    return pd.DataFrame({
        "med": grouped.mean(), "min": grouped.min(), "max": grouped.max(),
        "piso": (half_hourly_series <= CMO_FLOOR_THRESHOLD).groupby(day).mean(),
    })


def build_panel(cmo, load, interchange, ear, ear_sin, ena, horizon=1):
    """Build a long panel with one row per (subsystem, target-day half-hour).

    `horizon` shifts the target in days without changing issue time. At 2, a
    forecast issued on the day before D targets D+1, and each information-gate
    lag increases by one day. This supports control C9, which expects error to
    increase with forecast horizon.

    Target `y` is CMO at that timestamp. Features follow the gate declared in
    `_comum` and do not use any information from day D.
    """
    horizon_shift = horizon - 1
    cmo_lag = CMO_LAG_DAYS + horizon_shift
    load_lag = LOAD_LAG_DAYS + horizon_shift
    hydro_lag = HYDRO_LAG_DAYS + horizon_shift

    daily_cmo = {subsystem: _daily_summary(cmo[subsystem]) for subsystem in SUBSYSTEMS}
    half_hours_per_day = 48

    blocks = []
    for subsystem in SUBSYSTEMS:
        frame = pd.DataFrame({"t": cmo.index, "y": cmo[subsystem].to_numpy()})
        frame["sub"] = subsystem
        frame["dia"] = frame["t"].dt.normalize()
        frame["hh"] = frame["t"].dt.hour * 2 + frame["t"].dt.minute // 30
        frame["dow"] = frame["t"].dt.dayofweek
        frame["mes"] = frame["t"].dt.month

        # Own-subsystem CMO at the same half-hour on prior days.
        for k in (0, 1, 2, 6):
            frame[f"cmo_l{cmo_lag + k}"] = cmo[subsystem].shift(
                half_hours_per_day * (cmo_lag + k)
            ).to_numpy()

        # Own-subsystem CMO daily aggregates.
        for k in (0, 1, 6):
            day_index = frame["dia"] - pd.Timedelta(days=cmo_lag + k)
            daily_values = daily_cmo[subsystem].reindex(day_index)
            for column in ("med", "min", "max", "piso"):
                frame[f"cmo{column}_d{cmo_lag + k}"] = daily_values[column].to_numpy()

        # CMO for all four subsystems at the same half-hour. Interchange limits
        # couple subsystem prices. The own-subsystem column is intentionally
        # duplicated so each subsystem block has the same feature columns.
        for other_subsystem in SUBSYSTEMS:
            frame[f"cmo_{other_subsystem}_l{cmo_lag}"] = cmo[other_subsystem].shift(
                half_hours_per_day * cmo_lag
            ).to_numpy()
        lagged_day_index = frame["dia"] - pd.Timedelta(days=cmo_lag)
        for other_subsystem in SUBSYSTEMS:
            frame[f"cmomed_{other_subsystem}_d{cmo_lag}"] = (
                daily_cmo[other_subsystem]["med"].reindex(lagged_day_index).to_numpy()
            )

        # Load and interchange are hourly, so join on the full hour.
        hour = frame["t"].dt.floor("h")
        for k in (0, 1, 7):
            frame[f"carga_l{load_lag + k}"] = load[subsystem].reindex(
                hour - pd.Timedelta(days=load_lag + k)
            ).to_numpy()
        daily_load_mean = load[subsystem].groupby(load.index.normalize()).mean()
        daily_load_max = load[subsystem].groupby(load.index.normalize()).max()
        lagged_load_day = frame["dia"] - pd.Timedelta(days=load_lag)
        frame[f"cargamed_d{load_lag}"] = daily_load_mean.reindex(lagged_load_day).to_numpy()
        frame[f"cargamax_d{load_lag}"] = daily_load_max.reindex(lagged_load_day).to_numpy()
        frame[f"cargasin_d{load_lag}"] = load.sum(axis=1).groupby(
            load.index.normalize()
        ).mean().reindex(lagged_load_day).to_numpy()
        frame[f"interc_l{load_lag}"] = interchange[subsystem].reindex(
            hour - pd.Timedelta(days=load_lag)
        ).to_numpy()
        frame[f"intercmed_d{load_lag}"] = interchange[subsystem].groupby(
            interchange.index.normalize()
        ).mean().reindex(lagged_load_day).to_numpy()

        # Daily hydrology.
        lagged_hydro_day = frame["dia"] - pd.Timedelta(days=hydro_lag)
        frame[f"ear_d{hydro_lag}"] = ear[subsystem].reindex(lagged_hydro_day).to_numpy()
        frame["ear_delta7"] = frame[f"ear_d{hydro_lag}"] - ear[subsystem].reindex(
            lagged_hydro_day - pd.Timedelta(days=7)
        ).to_numpy()
        frame[f"earsin_d{hydro_lag}"] = ear_sin.reindex(lagged_hydro_day).to_numpy()
        frame[f"ena_d{hydro_lag}"] = ena[subsystem].reindex(lagged_hydro_day).to_numpy()
        frame[f"enam7_d{hydro_lag}"] = ena[subsystem].rolling(7).mean().reindex(
            lagged_hydro_day
        ).to_numpy()

        blocks.append(frame)

    panel = pd.concat(blocks, ignore_index=True)
    return panel.sort_values(["t", "sub"]).reset_index(drop=True)


# Treat subsystem as a categorical feature. Without it, the model cannot
# identify the subsystem represented by a row: all four `cmo_<sub>_l1` columns
# always appear in the same order, and the own-subsystem lag cannot be inferred
# from their values alone. It is excluded from `feature_columns` because it is
# nonnumeric, then added by `model_columns` after the leakage check.
CATEGORICAL_FEATURE = "sub"


def feature_columns(panel):
    """Return numeric features, excluding the target, keys, and naive baseline."""
    excluded = {"t", "y", "dia", "sub", "naive_sazonal"}
    return [column for column in panel.columns if column not in excluded]


def model_columns(panel):
    """Return model inputs: numeric features plus subsystem as a category."""
    return feature_columns(panel) + [CATEGORICAL_FEATURE]
