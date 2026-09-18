"""Improvement experiments over the baselines, motivated by the literature.

Stages (uv run python -m terra_energy_research.experiments <stage>):
  select   chooses configurations WITHOUT touching the test: trains up to Jun 2025, early stopping on
           Jul–Aug 2025 and compares on validation (Sep 2025–Feb 2026)
  final    evaluates the given configurations on the test, with the baseline.py protocol
           (early stopping on validation, retraining on train + validation)
  walk     monthly walk-forward on the test: for each month, retrains on everything that came before.
           With --calibrate, corrects the month's forecasts using the previous CALIB_WINDOW_DAYS days (out of sample):
           multiplicative factor for the curtailed fraction and isotonic regression for the probability

Configurations:
  base     "+plan" features from baseline.py, direct regression (cross-entropy)
  lit      base + literature features (dataset.add_literature_features)
  hurdle   lit, two-stage model: P(curtailment > 0) × E[fraction | curtailment > 0]
  recency  lit with recency weighting (180-day half-life)
  l1       lit with L1 loss (median): optimizes MAE, but not total energy
  core*    base + literature without hydrology/interchange (H1, H2, H4), with recency and/or two stages
  *_wx     + archived ECMWF weather forecast (wx1 day ahead, wx2 two days ahead)
  d2*      two days ahead (D+2) horizon: only information available at the end of D-2 (no plan or scheduled load)
  *_cmo    + SIN marginal operating cost (CMO) on D-1: level, daily minimum and share at the floor
  wind_*   same ideas for the wind clusters (--data ...curtailment_wind_halfhour.parquet)

Results and choice (core_recency with monthly retraining): reports/experiments_curtailment.md
"""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from terra_energy_research.baseline import (
    CALENDARIO_LAGS, LGB_PARAMS, PLANO, SISTEMA, classification_metrics, regression_metrics,
)
from terra_energy_research.dataset import DEFAULT_OUT, TRAIN_END, VALID_END

LITERATURA = [
    "plan_day_cut_frac", "plan_day_sin_vre_cut_frac",
    "lit_sin_mmgd_share", "lit_ne_net_load_forecast", "lit_se_net_load_forecast", "lit_ne_vre_forecast",
    "lit_sin_net_load_ramp_1h", "lit_sin_net_load_daymin", "lit_sin_net_load_above_daymin",
    "lag1d_sin_load_forecast_error",
    *[f"lag1d_{s}_{v}" for s in ("n", "ne", "s", "se") for v in ("ena_pct_mlt", "ear_pct")],
    "lag1d_flow_ne_se", "lag1d_flow_n_se", "lag1d_flow_n_ne", "lag1d_flow_se_s",
]
CMO = ["lag1d_sin_cmo", "lag1d_sin_cmo_daymin", "lag1d_sin_cmo_floor_share"]
HIDRO_INTERCAMBIO = [c for c in LITERATURA if c.startswith(("lag1d_n_", "lag1d_ne_", "lag1d_s_", "lag1d_se_", "lag1d_flow_"))]
LIT_CORE = [c for c in LITERATURA if c not in HIDRO_INTERCAMBIO]  # H1, H2, H4 (without H3)
BASE = CALENDARIO_LAGS + SISTEMA + PLANO
LIT = BASE + LITERATURA

# archived ECMWF weather forecast (weather.py): wx1 = issued 24h before, wx2 = 48h before
WX = ["ghi", "cloud", "sin_solar_ghi", "ne_wind_speed", "ne_wind_cf"]
WX1 = [f"wx1_{c}" for c in WX]
WX2 = [f"wx2_{c}" for c in WX]
# wind: at the cluster the forecast wind is used, not the irradiance
WX_WIND = ["wind_speed", "sin_solar_ghi", "ne_wind_speed", "ne_wind_cf"]
WX1_WIND = [f"wx1_{c}" for c in WX_WIND]
WX2_WIND = [f"wx2_{c}" for c in WX_WIND]

# D+2 horizon: forecast issued after the close of D-2, without the ONS plan or scheduled load
D2_BASE = [
    "id_ons", "uf", "subsystem", "lon", "lat", "conn_voltage_kv", "capacity_mw_est",
    "hour", "dow", "month", "doy", "is_weekend", "is_holiday",
    "lag2d_is_curtailed", "lag2d_curtailed_frac", "lag7d_is_curtailed", "lag7d_curtailed_frac",
    "lag2d_sys_share_curtailed", "lag2d_sys_curtailed_frac",
    "roll7d_d2_curtailed_frac", "sys_roll7d_d2_curtailed_frac",
    *[f"lag2d_{scope}_{v}" for scope in ("sub", "sin") for v in ("load_verified", "wind_verified", "net_load_verified", "cmo")],
]

INNER_END = pd.Timestamp("2025-07-01")  # selection: early stopping on Jul–Aug 2025
HALF_LIFE_DAYS = 180
CALIB_WINDOW_DAYS = 60   # calibration window (out of sample)
CALIB_DAMPING = 0.5      # shrinks the factor toward 1: the raw monthly factor is too noisy
REPORTS = Path("reports")

CONFIGS = {
    "base": dict(features=BASE, kind="direct"),
    "lit": dict(features=LIT, kind="direct"),
    "hurdle": dict(features=LIT, kind="hurdle"),
    "recency": dict(features=LIT, kind="direct", recency=True),
    "l1": dict(features=LIT, kind="direct", objective="l1"),
    # second round: separates H3 (hydrology and interchange) from the other hypotheses
    "base_recency": dict(features=BASE, kind="direct", recency=True),
    "core": dict(features=BASE + LIT_CORE, kind="direct"),
    "core_recency": dict(features=BASE + LIT_CORE, kind="direct", recency=True),
    "core_recency_hurdle": dict(features=BASE + LIT_CORE, kind="hurdle", recency=True),
    # third round: weather forecast
    "core_recency_wx": dict(features=BASE + LIT_CORE + WX1, kind="direct", recency=True),
    "d2_recency": dict(features=D2_BASE, kind="direct", recency=True),
    "d2_recency_wx": dict(features=D2_BASE + WX2, kind="direct", recency=True),
    # fourth round: lagged CMO (marginal operating cost)
    "core_recency_wx_cmo": dict(features=BASE + LIT_CORE + WX1 + CMO, kind="direct", recency=True),
    "d2_recency_wx_cmo": dict(features=D2_BASE + WX2 + CMO, kind="direct", recency=True),
    # wind (--data data/processed/curtailment_wind_halfhour.parquet)
    "wind_base": dict(features=BASE, kind="direct"),
    "wind_core_recency": dict(features=BASE + LIT_CORE, kind="direct", recency=True),
    "wind_core_recency_wx_cmo": dict(features=BASE + LIT_CORE + WX1_WIND + CMO, kind="direct", recency=True),
    "wind_d2_recency_wx_cmo": dict(features=D2_BASE + WX2_WIND + CMO, kind="direct", recency=True),
}


def _weights(frame: pd.DataFrame, cfg: dict) -> np.ndarray | None:
    if not cfg.get("recency"):
        return None
    age = (frame["instante"].max() - frame["instante"]).dt.total_seconds() / 86400
    return np.power(0.5, age / HALF_LIFE_DAYS).to_numpy()


def _fit(model_cls, objective, X, y, w, X_stop=None, y_stop=None, n_estimators=None):
    params = {**LGB_PARAMS, "objective": objective}
    if n_estimators is not None:
        params["n_estimators"] = n_estimators
        return model_cls(**params).fit(X, y, sample_weight=w)
    return model_cls(**params).fit(
        X, y, sample_weight=w, eval_X=(X_stop,), eval_y=(y_stop,),
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )


class CurtailmentModel:
    """Curtailment classifier + curtailed-fraction regressor (direct or two-stage)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.features = cfg["features"]
        self.iterations: dict[str, int] = {}

    def fit(self, train: pd.DataFrame, stop: pd.DataFrame | None = None, iterations: dict | None = None):
        f, w = self.features, _weights(train, self.cfg)
        its = iterations or {}

        def fit_one(name, model_cls, objective, rows, target, stop_rows):
            X, y = train.loc[rows, f], train.loc[rows, target]
            ww = None if w is None else w[rows.to_numpy()]
            if stop is not None:
                m = _fit(model_cls, objective, X, y, ww, stop.loc[stop_rows, f], stop.loc[stop_rows, target])
                self.iterations[name] = m.best_iteration_ or LGB_PARAMS["n_estimators"]
            else:
                m = _fit(model_cls, objective, X, y, ww, n_estimators=its[name])
                self.iterations[name] = its[name]
            return m

        all_rows = pd.Series(True, index=train.index)
        stop_all = None if stop is None else pd.Series(True, index=stop.index)
        self.clf = fit_one("clf", lgb.LGBMClassifier, "binary", all_rows, "y_is_curtailed", stop_all)

        has_frac = train["y_curtailed_frac"].notna()
        stop_frac = None if stop is None else stop["y_curtailed_frac"].notna()
        if self.cfg["kind"] == "hurdle":
            pos = has_frac & (train["y_curtailed_frac"] > 0)
            stop_pos = None if stop is None else stop_frac & (stop["y_curtailed_frac"] > 0)
            # stage 1: P(fraction > 0) among rows with a defined fraction
            train["_pos"] = (train["y_curtailed_frac"] > 0).astype(int)
            if stop is not None:
                stop["_pos"] = (stop["y_curtailed_frac"] > 0).astype(int)
            self.occ = fit_one("occ", lgb.LGBMClassifier, "binary", has_frac, "_pos", stop_frac)
            # stage 2: E[fraction | fraction > 0]
            self.size = fit_one("size", lgb.LGBMRegressor, "cross_entropy", pos, "y_curtailed_frac", stop_pos)
        else:
            objective = self.cfg.get("objective", "cross_entropy")
            self.reg = fit_one("reg", lgb.LGBMRegressor, objective, has_frac, "y_curtailed_frac", stop_frac)
        return self

    def predict_proba(self, frame: pd.DataFrame) -> pd.Series:
        return pd.Series(self.clf.predict_proba(frame[self.features])[:, 1], index=frame.index)

    def predict_frac(self, frame: pd.DataFrame) -> pd.Series:
        X = frame[self.features]
        if self.cfg["kind"] == "hurdle":
            values = self.occ.predict_proba(X)[:, 1] * self.size.predict(X)
        else:
            values = self.reg.predict(X)
        return pd.Series(np.clip(values, 0, 1), index=frame.index)


def score(model: CurtailmentModel, frame: pd.DataFrame) -> dict:
    reg_rows = frame[frame["y_curtailed_frac"].notna()]
    return {
        **classification_metrics(frame["y_is_curtailed"], model.predict_proba(frame)),
        **regression_metrics(reg_rows, model.predict_frac(reg_rows)),
    }


def _format(results: pd.DataFrame) -> str:
    results = results.copy()
    results["energy_bias_pct"] = 100 * (results["energy_pred_gwh"] / results["energy_true_gwh"] - 1)
    cols = ["auc", "avg_precision", "brier", "mae_frac", "mae_mw", "energy_bias_pct"]
    return results[[c for c in results.columns if c not in cols + ["energy_pred_gwh", "energy_true_gwh"]] + cols].round(4).to_string(index=False)


def select(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    inner_train = df[df["instante"] < INNER_END].copy()
    inner_stop = df[(df["instante"] >= INNER_END) & (df["instante"] < TRAIN_END)].copy()
    valid = df[df["split"] == "valid"]
    rows = []
    for name in names:
        model = CurtailmentModel(CONFIGS[name]).fit(inner_train, inner_stop)
        rows.append({"config": name, **model.iterations, **score(model, valid)})
        print(f"{name}: ok {model.iterations}", flush=True)
    return pd.DataFrame(rows)


def final(df: pd.DataFrame, names: list[str]) -> tuple[pd.DataFrame, dict]:
    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    train_valid = pd.concat([train, valid])
    test = df[df["split"] == "test"]
    rows, iterations = [], {}
    for name in names:
        tuned = CurtailmentModel(CONFIGS[name]).fit(train, valid)
        model = CurtailmentModel(CONFIGS[name]).fit(train_valid, iterations=tuned.iterations)
        iterations[name] = tuned.iterations
        rows.append({"config": name, **score(model, test)})
        if name in ("base", "lit"):
            importance = pd.Series(model.clf.booster_.feature_importance("gain"), index=model.features)
            (REPORTS / f"importance_{name}_clf.csv").write_text((importance / importance.sum()).sort_values(ascending=False).to_csv())
        print(f"{name}: ok", flush=True)
    return pd.DataFrame(rows), iterations


def _calibrators(model: CurtailmentModel, window: pd.DataFrame):
    """Calibration estimated on out-of-sample data (the CALIB_WINDOW_DAYS days before the forecast month).

    Fraction: multiplicative factor that equates forecast curtailed energy with actual, shrunk
    by CALIB_DAMPING toward 1 (the raw factor swings too much from month to month).
    Probability: isotonic regression (monotonic, so it does not change the AUC).
    """
    rows = window[window["y_curtailed_frac"].notna()]
    pred_mw = model.predict_frac(rows) * rows["reference"]
    true_mw = rows["y_curtailed_frac"] * rows["reference"]
    scale = float(true_mw.sum() / pred_mw.sum()) if pred_mw.sum() > 0 else 1.0
    scale = 1 + CALIB_DAMPING * (scale - 1)
    isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
        model.predict_proba(window), window["y_is_curtailed"]
    )
    return np.clip(scale, 0.5, 2.0), isotonic


def walk_forward(df: pd.DataFrame, names: list[str], iterations: dict, calibrate: bool = False) -> pd.DataFrame:
    """For each test month, trains on all prior history (iterations fixed in 'final')."""
    test = df[df["split"] == "test"]
    months = test["instante"].dt.to_period("M").unique()
    preds = {name: {"proba": [], "frac": []} for name in names}
    for month in months:
        start = month.start_time
        history = df[df["instante"] < start].copy()
        frame = test[test["instante"].dt.to_period("M") == month]
        reg_rows = frame[frame["y_curtailed_frac"].notna()]
        # calibration window: CALIB_WINDOW_DAYS days before the month, forecast by a model that did not see it
        window = df[(df["instante"] >= start - pd.Timedelta(days=CALIB_WINDOW_DAYS)) & (df["instante"] < start)]
        for name in names:
            model = CurtailmentModel(CONFIGS[name]).fit(history, iterations=iterations[name])
            scale, isotonic = 1.0, None
            if calibrate:
                previous = CurtailmentModel(CONFIGS[name]).fit(
                    df[df["instante"] < window["instante"].min()].copy(), iterations=iterations[name]
                )
                scale, isotonic = _calibrators(previous, window)
            proba = model.predict_proba(frame)
            if isotonic is not None:
                proba = pd.Series(isotonic.predict(proba), index=proba.index)
            preds[name]["proba"].append(proba)
            preds[name]["frac"].append((model.predict_frac(reg_rows) * scale).clip(0, 1))
        print(f"walk-forward {month}: ok (factor {scale:.3f})", flush=True)
    rows = []
    reg_test = test[test["y_curtailed_frac"].notna()]
    for name in names:
        proba = pd.concat(preds[name]["proba"]).reindex(test.index)
        frac = pd.concat(preds[name]["frac"]).reindex(reg_test.index)
        rows.append({"config": name, **classification_metrics(test["y_is_curtailed"], proba),
                     **regression_metrics(reg_test, frac)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["select", "final", "walk"])
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--calibrate", action="store_true", help="calibrates with the days before the month (walk stage only)")
    parser.add_argument("--data", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    df = pd.read_parquet(args.data)
    REPORTS.mkdir(exist_ok=True)
    names = args.configs.split(",")
    if args.stage == "select":
        out = REPORTS / "experiments_select.csv"
        results = select(df, names)
        if out.exists():  # accumulates runs, keeping the most recent of each configuration
            results = pd.concat([pd.read_csv(out), results]).drop_duplicates("config", keep="last")
        results.to_csv(out, index=False)
    elif args.stage == "final":
        results, iterations = final(df, names)
        out, its_path = REPORTS / "experiments_final.csv", REPORTS / "experiments_iterations.json"
        if out.exists():
            results = pd.concat([pd.read_csv(out), results]).drop_duplicates("config", keep="last")
        if its_path.exists():
            iterations = json.loads(its_path.read_text()) | iterations
        results.to_csv(out, index=False)
        its_path.write_text(json.dumps(iterations, indent=2))
    else:
        iterations = json.loads((REPORTS / "experiments_iterations.json").read_text())
        results = walk_forward(df, names, iterations, calibrate=args.calibrate)
        if args.calibrate:
            results["config"] += "_cal"
        out = REPORTS / "experiments_walk.csv"
        if out.exists():
            results = pd.concat([pd.read_csv(out), results]).drop_duplicates("config", keep="last")
        results.to_csv(out, index=False)
    print(_format(results))


if __name__ == "__main__":
    main()
