"""Curtailment forecasting baselines on the 30-min dataset.

Two tasks, evaluated on validation and test (temporal split of the dataset). The number of
trees is chosen on validation; for the test, models and climatology are refit on
train + validation.
  - classification: will there be curtailment (y_is_curtailed)?
  - regression: curtailed fraction of the reference (y_curtailed_frac)

Models: D-1 and D-7 persistence, climatology (cluster × hour × day of week,
training mean), the ONS day-ahead (D-1) plan itself (scheduled curtailment fraction) and LightGBM
with growing feature sets:
  calendar_lags    calendar, cluster attributes and curtailment lags
  +system          scheduled load and wind/solar forecasts for the subsystem and the SIN (D-1)
  +plan            ONS D-1 dispatch plan (scheduled curtailment for the cluster and the system)
  +oracle          verified values at the same instant (ceiling, not usable in operation)

    uv run python -m terra_energy_research.baseline
"""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, roc_auc_score

from terra_energy_research.dataset import DEFAULT_OUT

CALENDARIO_LAGS = [
    "id_ons", "uf", "subsystem", "lon", "lat", "conn_voltage_kv", "capacity_mw_est",
    # trend_days is left out: in the test it falls outside the training range and trees do not extrapolate
    "hour", "dow", "month", "doy", "is_weekend", "is_holiday",
    "lag1d_is_curtailed", "lag1d_curtailed_frac", "lag7d_is_curtailed", "lag7d_curtailed_frac",
    "lag1d_sys_share_curtailed", "lag1d_sys_curtailed_frac",
    "roll7d_curtailed_frac", "sys_roll7d_curtailed_frac",
]
SISTEMA = [
    f"{scope}_{name}"
    for scope in ("sub", "sin")
    for name in ("load_programmed", "wind_forecast", "solar_forecast", "solar_distributed_programmed",
                 "net_load_forecast", "vre_share_forecast")
] + [f"lag1d_{scope}_{name}" for scope in ("sub", "sin") for name in ("load_verified", "wind_verified", "net_load_verified")]
PLANO = [
    "plan_forecast_mw", "plan_programmed_mw", "plan_cut_mw", "plan_cut_frac",
    *[f"plan_{scope}_{name}" for scope in ("sub", "sin")
      for name in ("wind_cut_frac", "solar_cut_frac", "hydro_programmed", "thermal_programmed")],
]
ORACLE = [
    "oracle_poa_mean", "oracle_reference_cf", "oracle_sys_reference_mw", "oracle_sub_reference_mw",
    *[f"oracle_{scope}_{name}" for scope in ("sub", "sin") for name in ("load_verified", "wind_verified", "net_load_verified")],
]
FEATURE_SETS = {
    "calendar_lags": CALENDARIO_LAGS,
    "+system": CALENDARIO_LAGS + SISTEMA,
    "+plan": CALENDARIO_LAGS + SISTEMA + PLANO,
    "+oracle": CALENDARIO_LAGS + SISTEMA + PLANO + ORACLE,
}

LGB_PARAMS = dict(learning_rate=0.05, num_leaves=63, min_child_samples=200, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, n_estimators=2000, verbose=-1)


def classification_metrics(y: pd.Series, p: pd.Series) -> dict:
    p = p.clip(0, 1)
    return {
        "auc": roc_auc_score(y, p),
        "avg_precision": average_precision_score(y, p),
        "brier": brier_score_loss(y, p),
    }


def regression_metrics(f: pd.DataFrame, p: pd.Series) -> dict:
    p = p.clip(0, 1)
    true_mw = f["y_curtailed_frac"] * f["reference"]
    pred_mw = p * f["reference"]
    return {
        "mae_frac": mean_absolute_error(f["y_curtailed_frac"], p),
        "mae_mw": mean_absolute_error(true_mw, pred_mw),
        "energy_true_gwh": true_mw.sum() / 2000,
        "energy_pred_gwh": pred_mw.sum() / 2000,
    }


def climatology(train: pd.DataFrame, target: str, frame: pd.DataFrame) -> pd.Series:
    keys = ["id_ons", "hour", "dow"]
    table = train.groupby(keys, observed=True)[target].mean().rename("clim")
    return frame[keys].merge(table.reset_index(), on=keys, how="left")["clim"].set_axis(frame.index)


def fit_lgb(kind: str, features: list[str], train: pd.DataFrame, valid: pd.DataFrame, target: str):
    model_cls = lgb.LGBMClassifier if kind == "clf" else lgb.LGBMRegressor
    objective = "binary" if kind == "clf" else "cross_entropy"  # fraction in [0, 1]
    model = model_cls(objective=objective, **LGB_PARAMS)
    model.fit(
        train[features], train[target],
        eval_X=(valid[features],), eval_y=(valid[target],),
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


def refit(model, kind: str, features: list[str], frame: pd.DataFrame, target: str):
    """Retrains with the number of trees chosen on validation, using train + validation."""
    model_cls = lgb.LGBMClassifier if kind == "clf" else lgb.LGBMRegressor
    params = {**LGB_PARAMS, "n_estimators": model.best_iteration_ or LGB_PARAMS["n_estimators"]}
    objective = "binary" if kind == "clf" else "cross_entropy"
    return model_cls(objective=objective, **params).fit(frame[features], frame[target])


def predict(model, kind: str, frame: pd.DataFrame, features: list[str]) -> pd.Series:
    values = model.predict_proba(frame[features])[:, 1] if kind == "clf" else model.predict(frame[features])
    return pd.Series(values, index=frame.index)


def evaluate(task: str, split: str, frame: pd.DataFrame, preds: dict[str, pd.Series], metric_fn) -> list[dict]:
    """Metrics for all models on the same rows (where no baseline is null)."""
    common = pd.concat(preds, axis=1).notna().all(axis=1)
    rows = []
    for name, pred in preds.items():
        target = frame.loc[common, "y_is_curtailed"] if task == "classification" else frame.loc[common]
        rows.append({
            "task": task, "split": split, "model": name,
            "n": int(common.sum()), "coverage_own": float(pred.notna().mean()),
            **metric_fn(target, pred[common]),
        })
    return rows


def run(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    parts = {name: df[df["split"] == name] for name in ("train", "valid", "test")}
    rows, importances = [], {}

    tasks = {
        "classification": dict(kind="clf", target="y_is_curtailed", metric=classification_metrics,
                              lag1="lag1d_is_curtailed", lag7="lag7d_is_curtailed"),
        "regression": dict(kind="reg", target="y_curtailed_frac", metric=regression_metrics,
                          lag1="lag1d_curtailed_frac", lag7="lag7d_curtailed_frac"),
    }
    for task, cfg in tasks.items():
        target = cfg["target"]
        task_parts = {k: v[v[target].notna()] for k, v in parts.items()}
        train = task_parts["train"]
        train_valid = pd.concat([train, task_parts["valid"]])
        tuned = {name: fit_lgb(cfg["kind"], feats, train, task_parts["valid"], target) for name, feats in FEATURE_SETS.items()}
        refitted = {name: refit(m, cfg["kind"], FEATURE_SETS[name], train_valid, target) for name, m in tuned.items()}
        for split in ("valid", "test"):
            frame = task_parts[split]
            # validation: models trained on train only; test: retrained on train + validation
            models = tuned if split == "valid" else refitted
            history = train if split == "valid" else train_valid
            naive = {
                "persistence_D-1": frame[cfg["lag1"]].astype(float),
                "persistence_D-7": frame[cfg["lag7"]].astype(float),
                "climatology": climatology(history, target, frame).astype(float),
            }
            learned = {f"lightgbm_{name}": predict(m, cfg["kind"], frame, FEATURE_SETS[name]) for name, m in models.items()}
            # (1) all clusters, without the ONS plan as a baseline
            rows += [dict(scope="all", **r) for r in evaluate(task, split, frame, naive | learned, cfg["metric"])]
            # (2) only where the cluster's D-1 plan exists, with the plan as a baseline
            plan = {"ons_plan_D-1": frame["plan_cut_frac"].astype(float)}
            rows += [dict(scope="with_plan", **r) for r in evaluate(task, split, frame, plan | naive | learned, cfg["metric"])]
        importances[task] = top_importance(refitted["+plan"], FEATURE_SETS["+plan"])

    return pd.DataFrame(rows), importances


def top_importance(model, features: list[str], n: int = 12) -> dict:
    gain = model.booster_.feature_importance(importance_type="gain")
    share = gain / gain.sum()
    order = np.argsort(share)[::-1][:n]
    return {features[i]: round(float(share[i]), 4) for i in order}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out", type=Path, default=Path("reports/baseline_metrics"))
    args = parser.parse_args()

    df = pd.read_parquet(args.data)
    metrics, importances = run(df)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_name(args.out.name + "_importance.json").write_text(json.dumps(importances, indent=2))

    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.4f}".format):
        for (task, scope), group in metrics.groupby(["task", "scope"], sort=False):
            print(f"\n== {task} · {scope} ==")
            print(group.drop(columns=["task", "scope"]).dropna(axis=1, how="all").to_string(index=False))
    print(json.dumps(importances, indent=2))


if __name__ == "__main__":
    main()
