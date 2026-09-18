"""Trains, saves and uses the chosen curtailment forecasting model.

Unlike `experiments.py` (which compares configurations and discards the models), here the model is
trained on all available data and **written to disk**, together with the feature list, the
number of trees, the calibration factor and the training metadata.

    uv run python -m terra_energy_research.model train --tech solar
    uv run python -m terra_energy_research.model train --tech wind
    uv run python -m terra_energy_research.model predict --tech solar --start 2026-08-01 --end 2026-08-31

Default model per technology: see DEFAULT_CONFIG. The calibration factor is estimated on the last
CALIB_WINDOW_DAYS days, with forecasts from a model that did not see them, and is applied at prediction.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from terra_energy_research.dataset import TECH
from terra_energy_research.experiments import (
    CALIB_WINDOW_DAYS, CONFIGS, CurtailmentModel, _calibrators, regression_metrics, classification_metrics,
)

MODELS = Path("models")
DEFAULT_CONFIG = {"solar": "core_recency_wx_cmo", "wind": "wind_core_recency_wx_cmo"}
ITERATIONS = Path("reports/experiments_iterations.json")


def _iterations(config: str) -> dict:
    """Number of trees chosen on validation (`final` stage of experiments.py)."""
    saved = json.loads(ITERATIONS.read_text()) if ITERATIONS.exists() else {}
    if config not in saved:
        raise SystemExit(f"Run first: experiments final --configs {config}")
    return saved[config]


def train(tech: str, config: str, out_dir: Path) -> dict:
    df = pd.read_parquet(TECH[tech]["out"])
    iterations = _iterations(config)

    # calibration: model trained up to the start of the window, evaluated on the window (out of sample)
    cutoff = df["instante"].max().normalize() - pd.Timedelta(days=CALIB_WINDOW_DAYS)
    window = df[df["instante"] >= cutoff]
    previous = CurtailmentModel(CONFIGS[config]).fit(df[df["instante"] < cutoff].copy(), iterations=iterations)
    scale, isotonic = _calibrators(previous, window)
    holdout = {
        **classification_metrics(window["y_is_curtailed"], previous.predict_proba(window)),
        **regression_metrics(window[window["y_curtailed_frac"].notna()],
                             previous.predict_frac(window[window["y_curtailed_frac"].notna()])),
    }

    model = CurtailmentModel(CONFIGS[config]).fit(df.copy(), iterations=iterations)

    out_dir.mkdir(parents=True, exist_ok=True)
    boosters = {"clf": model.clf} | ({"occ": model.occ, "size": model.size}
                                     if CONFIGS[config]["kind"] == "hurdle" else {"reg": model.reg})
    for name, booster in boosters.items():
        booster.booster_.save_model(str(out_dir / f"{name}.txt"))
    meta = {
        "tech": tech,
        "config": config,
        "features": model.features,
        "kind": CONFIGS[config]["kind"],
        "iterations": iterations,
        "calibration_scale": scale,
        "isotonic_x": list(isotonic.X_thresholds_),
        "isotonic_y": list(isotonic.y_thresholds_),
        "trained_on": {"rows": len(df), "start": str(df["instante"].min()), "end": str(df["instante"].max())},
        "calibration_window": {"start": str(cutoff), "days": CALIB_WINDOW_DAYS},
        "holdout_metrics": {k: round(float(v), 4) for k, v in holdout.items()},
        "dataset": str(TECH[tech]["out"]),
        "trained_at": str(date.today()),
    }
    (out_dir / "model.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"{tech}/{config} saved to {out_dir}")
    print(json.dumps(meta["holdout_metrics"], indent=2))
    return meta


def load(out_dir: Path) -> dict:
    meta = json.loads((out_dir / "model.json").read_text())
    meta["boosters"] = {p.stem: lgb.Booster(model_file=str(p)) for p in out_dir.glob("*.txt")}
    return meta


def predict(frame: pd.DataFrame, meta: dict, calibrate: bool = True) -> pd.DataFrame:
    """Curtailment probability and expected curtailed fraction, already calibrated."""
    X = frame[meta["features"]]
    boosters = meta["boosters"]
    proba = pd.Series(boosters["clf"].predict(X), index=frame.index)
    if calibrate:  # isotonic saved as (x, y) points; applying = interpolating between them
        proba = pd.Series(np.interp(proba, meta["isotonic_x"], meta["isotonic_y"]), index=frame.index)
    if meta["kind"] == "hurdle":
        frac = boosters["occ"].predict(X) * boosters["size"].predict(X)
    else:
        frac = boosters["reg"].predict(X)
    frac = pd.Series(frac, index=frame.index).clip(0, 1)
    if calibrate:
        frac = (frac * meta["calibration_scale"]).clip(0, 1)
    return pd.DataFrame({
        "id_ons": frame["id_ons"], "instante": frame["instante"],
        "curtailment_probability": proba.clip(0, 1),
        "curtailed_fraction": frac,
        "curtailment_forecast_mw": frac * frame["reference"],
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["train", "predict"])
    parser.add_argument("--tech", choices=tuple(TECH), default="solar")
    parser.add_argument("--config")
    parser.add_argument("--dir", type=Path)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--out", type=Path, default=Path("data/processed/predictions.parquet"))
    args = parser.parse_args()

    config = args.config or DEFAULT_CONFIG[args.tech]
    out_dir = args.dir or MODELS / args.tech
    if args.command == "train":
        train(args.tech, config, out_dir)
        return

    meta = load(out_dir)
    df = pd.read_parquet(TECH[args.tech]["out"])
    if args.start:
        df = df[df["instante"] >= pd.Timestamp(args.start)]
    if args.end:
        df = df[df["instante"] < pd.Timestamp(args.end) + pd.Timedelta(days=1)]
    out = predict(df, meta)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"{len(out):,} predictions -> {args.out}")
    print(out.describe().round(3))


if __name__ == "__main__":
    main()
