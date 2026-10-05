"""Step 1: build the subsystem-by-half-hour panel and count every exclusion.

Read CMO, load, interchange, EAR, and ENA sources and write the panel and an
exclusion inventory. This step does not assess the target; step 2 validates the
panel.

Run from the repository root:
    .venv/bin/python experiments/E-cmo-price/1_painel.py
"""
import json

import pandas as pd

from _comum import (CMO_FLOOR_THRESHOLD, CMO_MAX_VALUE, CMO_MIN_VALUE,
                    OUTPUT_DIR, PANEL_PATH, SUBSYSTEMS, seasonal_naive)
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load, net_interchange)
from _painel import build_panel, feature_columns


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmo_frame, load_frame = cmo(), hourly_load()
    interchange_frame, ear_frame, sin_ear, ena_frame = (
        net_interchange(), ear(), ear_sin(), ena()
    )

    grid_size = len(cmo_frame) * len(SUBSYSTEMS)
    missing_cmo_days = sorted({
        str(day.date())
        for day in cmo_frame.index[cmo_frame[SUBSYSTEMS[0]].isna()].normalize().unique()
    })

    panel = build_panel(cmo_frame, load_frame, interchange_frame, ear_frame,
                        sin_ear, ena_frame, horizon=1)
    if len(panel) != grid_size:
        raise SystemExit(f"panel has {len(panel)} rows; expected {grid_size}")

    # Count exclusions in the order they are applied.
    initial_rows = len(panel)
    panel = panel[panel["y"].notna()]
    rows_without_target = initial_rows - len(panel)

    # Keep the target and both persistence terms on the same rows so baseline
    # comparisons use identical samples.
    lag_1, lag_7 = "cmo_l1", "cmo_l7"
    rows_before_baseline_filter = len(panel)
    panel = panel[panel[lag_1].notna() & panel[lag_7].notna()]
    rows_without_baseline = rows_before_baseline_filter - len(panel)

    panel["naive_sazonal"] = seasonal_naive(
        panel[lag_1].to_numpy(), panel[lag_7].to_numpy(), panel["dow"].to_numpy()
    )

    features = feature_columns(panel)
    coverage = {column: float(panel[column].notna().mean()) for column in features}

    panel.to_parquet(PANEL_PATH, index=False)

    inventory = {
        "janela": [str(panel["t"].min()), str(panel["t"].max())],
        "grade_completa": int(grid_size),
        "linhas_gravadas": int(len(panel)),
        "descarte_sem_alvo": int(rows_without_target),
        "descarte_sem_base": int(rows_without_baseline),
        "dias_de_cmo_ausentes": missing_cmo_days,
        "n_features": len(features),
        "features": features,
        "cobertura_minima": min(coverage.values()),
        "feature_menos_coberta": min(coverage, key=coverage.get),
        "cmo_fracao_no_piso": float((panel["y"] <= CMO_FLOOR_THRESHOLD).mean()),
        "cmo_min": float(panel["y"].min()),
        "cmo_max": float(panel["y"].max()),
        "cmo_fora_da_faixa": int(
            ((panel["y"] < CMO_MIN_VALUE) | (panel["y"] > CMO_MAX_VALUE)).sum()
        ),
    }
    inventory_path = OUTPUT_DIR / "janelas.json"
    inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False))

    print(f"panel: {len(panel)} rows, {len(features)} features, "
          f"{inventory['janela'][0][:10]} to {inventory['janela'][1][:10]}")
    missing_panel_days = pd.date_range(
        panel["dia"].min(), panel["dia"].max(), freq="D"
    ).difference(pd.DatetimeIndex(panel["dia"].unique()))
    inventory["dias_ausentes_no_painel"] = [str(day.date()) for day in missing_panel_days]
    inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False))

    print(f"excluded: {rows_without_target} without target "
          f"({len(missing_cmo_days)} missing CMO days), "
          f"{rows_without_baseline} without D-1 or D-7")
    print(f"panel omits {len(missing_panel_days)} days: each source gap also removes "
          "the following day (no D-1) and the day seven days later (no D-7)")
    print(f"floor: {100 * inventory['cmo_fracao_no_piso']:.1f}% of half-hours "
          f"have CMO <= {CMO_FLOOR_THRESHOLD} R$/MWh")


if __name__ == "__main__":
    main()