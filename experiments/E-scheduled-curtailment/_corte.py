"""Build the F2/F12 target: the gap between ONS forecasts and schedules.

`programacao_x_previsao` contains forecast generation and scheduled generation
for each wind and solar plant and half-hourly step. Their difference is not
forecast error; it is a dispatch decision: how much of the forecast output the
operator chooses not to schedule one day ahead. This is constrained-off from
the scheduling perspective, not the measurement perspective.

Aggregate to the SIN by step. No crosswalk is needed because forecast and
scheduled values are on the same row of the same file.

Run from the repository root: .venv/bin/python
    experiments/E-scheduled-curtailment/_corte.py
"""
import glob
from pathlib import Path
import pandas as pd

def main():
    input_files = sorted(glob.glob("data/raw/programacao_previsao/*.parquet"))
    assert len(input_files) > 600, f"only {len(input_files)} input files found"
    daily_frames = []
    for file_path in input_files:
        frame = pd.read_parquet(file_path, columns=["dat_programacao", "num_patamar",
                               "val_previsao", "val_programado"])
        # The ONS parquet stores both values as text. Check each file after conversion
        # so non-numeric cells cannot be silently discarded.
        for c in ("val_previsao", "val_programado"):
            raw_values = frame[c]
            frame[c] = pd.to_numeric(raw_values, errors="coerce")
            invalid_count = int(frame[c].isna().sum() - raw_values.isna().sum())
            assert invalid_count == 0, f"{file_path}: {invalid_count} values in {c} are not numeric"
        daily_frames.append(frame.groupby(["dat_programacao", "num_patamar"])
                    .agg(prev=("val_previsao", "sum"),
                     prog=("val_programado", "sum"),
                     n_usinas=("val_previsao", "size")).reset_index())
    panel = pd.concat(daily_frames, ignore_index=True)
    panel["data"] = pd.to_datetime(panel.dat_programacao.astype(str), format="%Y%m%d")
    panel["h"] = panel.data + pd.to_timedelta((panel.num_patamar - 1) * 30, unit="min")
    panel = panel.sort_values("h").set_index("h")
    panel["corte"] = panel.prev - panel.prog
    panel["frac"] = (panel.corte / panel.prev.where(panel.prev > 0)).clip(lower=0)

    # Data integrity controls.
    assert panel.index.is_unique, "duplicate scheduling step"
    assert panel.num_patamar.between(1, 48).all(), "step outside 1..48"
    observations_per_day = panel.groupby(panel.data).size()
    incomplete_days = int((observations_per_day != 48).sum())
    negative_curtailment = int((panel.corte < -1e-6).sum())
    print(f"{len(panel):,} steps, {panel.data.nunique():,} days, "
        f"{panel.index.min():%Y-%m-%d} to {panel.index.max():%Y-%m-%d}")
    print(f"  days without 48 steps: {incomplete_days}")
    print(f"  plants per step: median {int(panel.n_usinas.median())}, "
        f"min {int(panel.n_usinas.min())}, max {int(panel.n_usinas.max())}")
    print(f"  steps with scheduled > forecast: {negative_curtailment:,} ({100 * negative_curtailment / len(panel):.2f}%)")
    print(f"  curtailed fraction: mean {panel.frac.mean():.4f}  median {panel.frac.median():.4f}  "
        f"p95 {panel.frac.quantile(.95):.4f}  max {panel.frac.max():.4f}")
    print(f"  forecast energy {panel.prev.sum() / 2 / 1e6:.2f} TWh, "
        f"scheduled {panel.prog.sum() / 2 / 1e6:.2f} TWh, "
        f"curtailment {panel.corte.clip(lower=0).sum() / 2 / 1e6:.2f} TWh")
    Path("data/interim").mkdir(parents=True, exist_ok=True)
    panel[["num_patamar", "prev", "prog", "corte", "frac", "n_usinas"]].to_parquet(
        "data/interim/corte_programado.parquet")
    print("Saved: data/interim/corte_programado.parquet")

if __name__ == "__main__":
    main()
