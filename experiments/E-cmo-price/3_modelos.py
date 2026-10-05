"""Step 3: evaluate baselines and models with rolling-origin validation.

Run from the repository root after step 2 passes:
    .venv/bin/python experiments/E-cmo-price/3_modelos.py

DESIGN
------
Estimand: CMO in R$/MWh for each of the 48 half-hours on target day D across
four subsystems, forecast at 12:00 on D-1.

Baseline: the canonical seasonal-naive price-forecasting baseline. Tuesday
through Friday repeat D-1; Saturday through Monday repeat D-7. This is not the
simple naive baseline: for price series, the previous day's value already
carries the intraday shape and level that a model must improve upon.

Loss: MAE, selected before examining the results because it supports comparison
across price-forecasting studies and is less dominated by the heavy CMO tail
than RMSE. RMSE is secondary; any disagreement between the two is a result.

Monthly recalibration with an expanding training window: the model is refit on
the first day of each test month using all available history. Without this,
one fit would span 14 months while the naive baseline updates every day.

POSITIVE CONTROL
----------------
The level oracle receives the true mean for target day D and shifts the naive
forecast to that level while preserving its shape. If the oracle did not show
substantial skill, the design could not detect gains and negative model results
would be uninformative.

LIMITATION
----------
There is one hyperparameter configuration and one random seed. The confidence
interval covers variation across test days, not fitting variance, seed variance,
or variation in the train/test cutoff.
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from _comum import (CMO_FLOOR_THRESHOLD, OUTPUT_DIR, PANEL_PATH,
                    PREDICTIONS_PATH, RESULT_PATH, SUBSYSTEMS)
from _modelos_comum import (BASELINE, INITIAL_TRAIN_FRACTION, N_BOOTSTRAP,
                            PARAMS, PREDICTORS, RANDOM_SEED)
from _painel import model_columns


def mean_absolute_error(actual, predicted):
    return float(np.abs(actual - predicted).mean())


def root_mean_squared_error(actual, predicted):
    return float(np.sqrt(((actual - predicted) ** 2).mean()))


def fit_and_predict(panel, feature_columns, test_days):
    """Use rolling-origin evaluation with monthly recalibration and an expanding window."""
    prediction_frames, fit_seconds = [], 0.0
    test_months = sorted(pd.Series(test_days).dt.to_period("M").unique())
    for month in test_months:
        month_start = month.to_timestamp()
        next_month_start = month_start + pd.offsets.MonthBegin(1)
        train = panel[panel["dia"] < month_start]
        test = panel[(panel["dia"] >= month_start) & (panel["dia"] < next_month_start)]
        if test.empty:
            continue
        start_time = time.time()
        direct_model = lgb.LGBMRegressor(**PARAMS).fit(train[feature_columns], train["y"])
        # The residual model learns a correction to the naive forecast rather
        # than the price level. It has a different inductive bias but uses the
        # same inputs.
        residual_model = lgb.LGBMRegressor(**PARAMS).fit(
            train[feature_columns], train["y"] - train["naive_sazonal"]
        )
        # CMO has mass at the floor and a long right tail. A single regressor
        # rarely predicts the floor exactly. The two-part rule predicts the
        # floor when its estimated probability is greater than 0.5.
        at_floor = train["y"] <= CMO_FLOOR_THRESHOLD
        floor_classifier = lgb.LGBMClassifier(
            **{**PARAMS, "objective": "binary"}
        ).fit(train[feature_columns], at_floor.astype(int))
        positive_regressor = lgb.LGBMRegressor(**PARAMS).fit(
            train.loc[~at_floor, feature_columns], train.loc[~at_floor, "y"]
        )
        floor_value = float(train.loc[at_floor, "y"].median())
        fit_seconds += time.time() - start_time

        predictions = test[["t", "sub", "dia", "hh", "dow", "y", "cmo_l1", "cmo_l7",
                            "naive_sazonal"]].copy()
        predictions["climatologia"] = train.groupby(["sub", "hh"])["y"].mean().reindex(
            pd.MultiIndex.from_arrays([test["sub"], test["hh"]])
        ).to_numpy()
        predictions["lgbm_direto"] = direct_model.predict(test[feature_columns])
        predictions["lgbm_residual"] = (
            test["naive_sazonal"].to_numpy()
            + residual_model.predict(test[feature_columns])
        )
        floor_probability = floor_classifier.predict_proba(test[feature_columns])[:, 1]
        predictions["lgbm_duas_partes"] = np.where(
            floor_probability > 0.5, floor_value,
            positive_regressor.predict(test[feature_columns])
        )
        prediction_frames.append(predictions)
    return pd.concat(prediction_frames, ignore_index=True), fit_seconds


def level_oracle(predictions):
    """Shift the seasonal-naive forecast by the true daily median residual; this is not a forecast.

    The median, not the mean, minimizes the declared MAE loss. Using the mean
    would measure the analyst's choice of statistic rather than level recovery.
    """
    residual = predictions["y"] - predictions["naive_sazonal"]
    return predictions["naive_sazonal"] + residual.groupby(
        [predictions["sub"], predictions["dia"]]
    ).transform("median")


def bootstrap_skill_interval(predictions, predictor, baseline,
                             n_bootstrap=N_BOOTSTRAP, seed=RANDOM_SEED):
    """Estimate a skill interval by resampling whole days, not individual rows.

    Half-hour errors within a day are correlated. Resampling rows would produce
    an overly narrow interval. Each block is a full day with all four
    subsystems, which also move together.
    """
    grouped = predictions.groupby("dia")
    model_error = grouped.apply(
        lambda day: np.abs(day["y"] - day[predictor]).sum(), include_groups=False
    )
    baseline_error = grouped.apply(
        lambda day: np.abs(day["y"] - day[baseline]).sum(), include_groups=False
    )
    group_sizes = grouped.size()
    model_error = model_error.to_numpy()
    baseline_error = baseline_error.to_numpy()
    group_sizes = group_sizes.to_numpy()
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(group_sizes), size=(n_bootstrap, len(group_sizes)))
    model_mae = model_error[indices].sum(1) / group_sizes[indices].sum(1)
    baseline_mae = baseline_error[indices].sum(1) / group_sizes[indices].sum(1)
    skill = 100.0 * (1.0 - model_mae / baseline_mae)
    return float(np.percentile(skill, 2.5)), float(np.percentile(skill, 97.5))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL_PATH)
    panel["sub"] = panel["sub"].astype("category")
    feature_columns = model_columns(panel)

    days = np.sort(panel["dia"].unique())
    cutoff = days[int(len(days) * INITIAL_TRAIN_FRACTION)]
    test_days = days[days >= cutoff]

    start_time = time.time()
    predictions, fit_seconds = fit_and_predict(panel, feature_columns, test_days)
    predictions["oraculo_nivel"] = level_oracle(predictions)
    predictions.to_parquet(PREDICTIONS_PATH, index=False)

    target = predictions["y"].to_numpy()
    errors = {
        key: dict(mae=mean_absolute_error(target, predictions[key].to_numpy()),
                  rmse=root_mean_squared_error(target, predictions[key].to_numpy()))
        for key in PREDICTORS
    }
    baseline_mae = errors[BASELINE]["mae"]
    skills = {}
    for predictor in PREDICTORS:
        if predictor == BASELINE:
            continue
        lower, upper = bootstrap_skill_interval(predictions, predictor, BASELINE)
        skills[predictor] = dict(
            habilidade_mae=100.0 * (1 - errors[predictor]["mae"] / baseline_mae),
            ic95=[lower, upper],
            habilidade_rmse=100.0 * (1 - errors[predictor]["rmse"] /
                                     errors[BASELINE]["rmse"]),
        )

    mae_by_subsystem = {}
    for subsystem in SUBSYSTEMS:
        subset = predictions[predictions["sub"] == subsystem]
        mae_by_subsystem[subsystem] = {
            key: mean_absolute_error(subset["y"].to_numpy(), subset[key].to_numpy())
            for key in PREDICTORS
        }
    mae_by_month = (
        predictions.assign(m=predictions["dia"].dt.to_period("M").astype(str))
        .groupby("m").apply(
            lambda month: pd.Series({
                key: mean_absolute_error(month["y"].to_numpy(), month[key].to_numpy())
                for key in PREDICTORS
            }), include_groups=False
        )
    )

    result = dict(
        janela_teste=[str(predictions["t"].min()), str(predictions["t"].max())],
        n_linhas=int(len(predictions)), n_dias=int(predictions["dia"].nunique()),
        n_features=len(feature_columns),
        recalibracoes=int(predictions["dia"].dt.to_period("M").nunique()),
        adversario=BASELINE, erros=errors, habilidade=skills,
        mae_por_subsistema=mae_by_subsystem,
        mae_por_mes=mae_by_month.round(2).to_dict(orient="index"),
        custo_s=dict(ajuste=round(fit_seconds, 1),
                     total=round(time.time() - start_time, 1)),
    )
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(f"test: {result['n_linhas']} rows, {result['n_dias']} days, "
          f"{result['recalibracoes']} recalibrations, {len(feature_columns)} features")
    print(f"{'predictor':16s} {'MAE':>8s} {'RMSE':>8s} {'MAE skill':>9s} {'95% CI':>20s}")
    for predictor in PREDICTORS:
        skill = skills.get(predictor)
        interval = f"[{skill['ic95'][0]:+.2f}; {skill['ic95'][1]:+.2f}]" if skill else ""
        skill_value = f"{skill['habilidade_mae']:+.2f}%" if skill else "baseline"
        print(f"{predictor:16s} {errors[predictor]['mae']:8.2f} "
              f"{errors[predictor]['rmse']:8.2f} {skill_value:>9s} {interval:>20s}")
    print(f"fit time: {result['custo_s']['ajuste']:.0f} s")


if __name__ == "__main__":
    main()
