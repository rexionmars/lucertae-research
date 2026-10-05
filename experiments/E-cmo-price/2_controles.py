"""Step 2: validate the panel and block step 3 if any required control fails.

Run from the repository root after step 1:
        .venv/bin/python experiments/E-cmo-price/2_controles.py

Each control is falsifiable and independent of the intended result; none passes
by construction. C3 is the most expensive and the only design-level check: it
rebuilds features from source series masked at issue time and requires identical
values.

LIMITATIONS
-----------
- Whether published CMO equals realized CMO. ONS publishes the dispatch-model
    output, and no independent source is available for comparison.
- Publication lag. It was measured once per source from file modification time
    and is documented in `_comum`; there is only one observation per source.
- National and regional holidays are not included because the repository has no
    holiday table. Their effect is part of both models' errors.
"""
import json

import numpy as np
import pandas as pd

from _comum import (CMO_MAX_VALUE, CMO_MIN_VALUE, CONTROLS_PATH, HYDRO_LAG_DAYS,
                    LOAD_LAG_DAYS, OUTPUT_DIR, PANEL_PATH, SUBSYSTEMS)
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load, net_interchange)
from _painel import build_panel, feature_columns

# Minimum fraction of rows with values for each feature family. Below this
# threshold, coverage is insufficient for evaluation.
MIN_FEATURE_COVERAGE = 0.97
SAMPLED_DAYS = 40
# Days absent from the panel over 2024-01-01 through 2026-08-27. There are 24,
# not just the 8 missing CMO days: each source gap removes three panel days (the
# gap, the following day without D-1, and the day seven days later without D-7).
# The gaps are far enough apart for all 8 x 3 days to be distinct. This is a
# tripwire, not a tolerance: any source change that alters the count must be
# investigated rather than silently absorbed.
MISSING_PANEL_DAYS = 24


def arrays_equal(a, b):
    """Compare arrays elementwise, treating missing values as equal."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    return np.all((np.isclose(a, b, rtol=1e-9, atol=1e-9)) |
                  (np.isnan(a) & np.isnan(b)))


def c1_grid(panel):
    """Check unique keys, 48 half-hours per day, and no invented dates.

    Missing CMO days must remain absent from the panel. Filling them by
    interpolation would make the calendar appear complete and invent targets
    that the operator never published.
    """
    duplicates = int(panel.duplicated(["sub", "t"]).sum())
    rows_per_day = panel.groupby(["sub", "dia"]).size()
    # The first and last days may be truncated by the D-7 exclusion; interior
    # days must remain complete.
    interior_days = rows_per_day[
        (rows_per_day.index.get_level_values("dia") > panel["dia"].min())
        & (rows_per_day.index.get_level_values("dia") < panel["dia"].max())
    ]
    incomplete_days = int((interior_days != 48).sum())
    calendar_days = pd.date_range(panel["dia"].min(), panel["dia"].max(), freq="D")
    missing_days = calendar_days.difference(pd.DatetimeIndex(panel["dia"].unique()))
    return dict(nome="C1 grid and key", duplicatas=duplicates,
                dias_incompletos=incomplete_days,
                dias_ausentes=[str(day.date()) for day in missing_days],
                dias_no_calendario=len(calendar_days), bloqueante=True,
                passa=(duplicates == 0 and incomplete_days == 0
                       and len(missing_days) == MISSING_PANEL_DAYS))


def c2_target_range(panel):
    """Check that CMO is within its physical range and the retained target is complete."""
    out_of_range = int(((panel["y"] < CMO_MIN_VALUE) | (panel["y"] > CMO_MAX_VALUE)).sum())
    missing_targets = int(panel["y"].isna().sum())
    return dict(nome="C2 physical target range", fora_da_faixa=out_of_range,
                alvo_ausente=missing_targets, minimo=float(panel["y"].min()),
                maximo=float(panel["y"].max()), bloqueante=True,
                passa=(out_of_range == 0 and missing_targets == 0))


def c3_information_gate(panel, sources, rng):
    """Rebuild features with source data masked at issue time to detect leakage.

    The forecast for target day D is issued at 12:00 on D-1. Masking removes CMO
    from D onward, load and interchange from D-1 onward, and hydrology after
    D-3. Any feature using future information changes under masking. A mismatch
    in a single cell fails this control.
    """
    cmo_source, load_source, interchange_source, ear_source, sin_ear_source, ena_source = sources
    features = feature_columns(panel)
    days = pd.Series(sorted(panel["dia"].unique()))
    candidate_days = days[(days > days.min() + pd.Timedelta(days=14)) &
                          (days < days.max() - pd.Timedelta(days=1))]
    sampled_days = candidate_days.sample(n=min(SAMPLED_DAYS, len(candidate_days)),
                                         random_state=rng)

    mismatches, checked_cells = [], 0
    for target_day in sampled_days:
        masked_cmo = cmo_source.copy()
        masked_cmo[masked_cmo.index >= target_day] = np.nan
        masked_load = load_source.copy()
        masked_load[masked_load.index >= target_day - pd.Timedelta(days=LOAD_LAG_DAYS - 1)] = np.nan
        masked_interchange = interchange_source.copy()
        masked_interchange[masked_interchange.index >= target_day - pd.Timedelta(days=LOAD_LAG_DAYS - 1)] = np.nan
        masked_ear = ear_source.copy()
        masked_ear[masked_ear.index > target_day - pd.Timedelta(days=HYDRO_LAG_DAYS)] = np.nan
        masked_sin_ear = sin_ear_source.copy()
        masked_sin_ear[masked_sin_ear.index > target_day - pd.Timedelta(days=HYDRO_LAG_DAYS)] = np.nan
        masked_ena = ena_source.copy()
        masked_ena[masked_ena.index > target_day - pd.Timedelta(days=HYDRO_LAG_DAYS)] = np.nan

        reference = panel[panel["dia"] == target_day].sort_values(["sub", "t"])
        rebuilt = build_panel(masked_cmo, masked_load, masked_interchange,
                              masked_ear, masked_sin_ear, masked_ena, horizon=1)
        rebuilt = rebuilt[rebuilt["dia"] == target_day].sort_values(["sub", "t"])
        if len(rebuilt) != len(reference):
            mismatches.append((str(target_day.date()), "row_count"))
            continue
        for feature in features:
            checked_cells += len(reference)
            if not arrays_equal(reference[feature].to_numpy(), rebuilt[feature].to_numpy()):
                mismatches.append((str(target_day.date()), feature))

    mismatch_features = sorted({feature for _, feature in mismatches})
    return dict(nome="C3 information gate", dias_testados=len(sampled_days),
                celulas_conferidas=int(checked_cells), features_divergentes=mismatch_features,
                bloqueante=True, passa=(len(mismatches) == 0))


def c4_feature_coverage(panel):
    """Require every feature to cover at least MIN_FEATURE_COVERAGE of rows.

    This nonredundant check detects trailing whitespace in `id_subsistema` in
    EAR and ENA files. Without stripping it, the affected subsystem column is
    empty and feature coverage drops.
    """
    coverage = {column: float(panel[column].notna().mean())
                for column in feature_columns(panel)}
    below_threshold = {column: round(value, 4) for column, value in coverage.items()
                       if value < MIN_FEATURE_COVERAGE}
    return dict(nome="C4 feature coverage", limiar=MIN_FEATURE_COVERAGE,
                abaixo_do_limiar=below_threshold, pior=min(coverage.values()),
                bloqueante=True, passa=(len(below_threshold) == 0))


def c5_baselines(panel):
    """Check the expected ranking among naive baselines.

    If D-1 persistence did not beat half-hour climatology, the target would have
    no short-term memory and the experiment would lack its intended comparison.
    All baselines use the same saved panel.
    """
    mean_absolute_error = lambda prediction: float(np.abs(panel["y"] - prediction).mean())
    climatology = panel.groupby(["sub", "hh"])["y"].transform("mean")
    errors = dict(d1=mean_absolute_error(panel["cmo_l1"]),
                  d7=mean_absolute_error(panel["cmo_l7"]),
                  sazonal=mean_absolute_error(panel["naive_sazonal"]),
                  climatologia=mean_absolute_error(climatology))
    return dict(nome="C5 baseline ranking", mae=errors, bloqueante=True,
                passa=(errors["d1"] < errors["climatologia"]
                       and errors["sazonal"] <= errors["d7"]))


def c6_distinct_subsystems(panel):
    """Check that cross-subsystem features represent distinct series."""

    wide = panel.pivot_table(index="t", columns="sub", values="y")
    correlation = wide.corr()
    collapsed_pairs = [(first, second) for first in SUBSYSTEMS for second in SUBSYSTEMS
                       if first < second and correlation.loc[first, second] > 0.999]
    return dict(nome="C6 distinct subsystems",
                correlacao_maxima=float(correlation.where(
                    ~np.eye(len(correlation), dtype=bool)).max().max()),
                pares_colapsados=collapsed_pairs, bloqueante=True,
                passa=(len(collapsed_pairs) == 0))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL_PATH)
    sources = (cmo(), hourly_load(), net_interchange(), ear(), ear_sin(), ena())

    results = [c1_grid(panel), c2_target_range(panel),
               c3_information_gate(panel, sources, 7),
               c4_feature_coverage(panel), c5_baselines(panel),
               c6_distinct_subsystems(panel)]

    for result in results:
        print(f"[{'PASS' if result['passa'] else 'FAIL'}] {result['nome']}")
        for key, value in result.items():
            if key not in ("nome", "passa", "bloqueante"):
                print(f"    {key}: {value}")

    CONTROLS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    failures = [result["nome"] for result in results
                if result["bloqueante"] and not result["passa"]]
    if failures:
        raise SystemExit("blocking controls failed: " + "; ".join(failures))
    print("\nall blocking controls passed")


if __name__ == "__main__":
    main()
