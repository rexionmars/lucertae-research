"""Step 5: identify sources of skill and run three additional controls.

Run from the repository root after step 3:
    .venv/bin/python experiments/E-cmo-price/5_ablacao.py

All three analyses use the same rolling-origin design and monthly
recalibration as step 3:

ABLATION     Four nested feature sets, from calendar plus own-subsystem CMO to
             the full panel. Interpret differences between adjacent sets, not
             each set's absolute skill.

PERMUTATION  Shuffle training features across rows while leaving the target
             unchanged. This breaks feature-target association without
             changing any column's distribution.

HORIZON      Repeat the design with a D+1 target and shift the full information
             gate by one day. Both model and baseline errors should increase.
             Skill intervals are reported because the amount of degradation is
             also a result.

LIMITATION
----------
The ablation removes feature families, not individual features. It identifies
which source contributes, not which column within a source. The nested order is
fixed, so a family may appear unhelpful if an earlier family contains the same
information.
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from _comum import (CMO_FLOOR_THRESHOLD, OUTPUT_DIR, PANEL_PATH, RESULT_PATH,
                    seasonal_naive)
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load, net_interchange)
from _modelos_comum import (BASELINE, INITIAL_TRAIN_FRACTION, N_BOOTSTRAP,
                            PARAMS, RANDOM_SEED)
from _painel import build_panel, feature_columns, model_columns

ABLATION_PATH = OUTPUT_DIR / "ablacao.json"


def feature_families(features):
    """Group features by source; every feature must belong to exactly one group."""
    families = {
        "calendario": [column for column in features if column in ("hh", "dow", "mes", "sub")],
        "cmo_cruzado": [column for column in features if column.startswith(("cmo_N", "cmo_NE",
                        "cmo_S", "cmo_SE", "cmomed_N", "cmomed_NE", "cmomed_S",
                        "cmomed_SE"))],
        "carga": [column for column in features if column.startswith(("carga", "interc"))],
        "hidro": [column for column in features if column.startswith(("ear", "ena"))],
    }
    assigned_features = {column for columns in families.values() for column in columns}
    families["cmo_proprio"] = [column for column in features if column not in assigned_features]
    unassigned = set(features) - {column for columns in families.values() for column in columns}
    if unassigned:
        raise SystemExit(f"features without a family: {sorted(unassigned)}")
    return families


def nested_feature_sets(features):
    """Build nested feature sets, each in the panel's canonical order.

    With `colsample_bytree` below 1, LightGBM samples columns by position, so
    permuting the same columns acts like changing the random seed. Before
    canonical ordering, the full set produced +4.40% skill versus +0.76% in
    step 3's canonical order, despite containing the same 41 features. Without
    this ordering, the ablation would mix fitting variance with family effects.
    """
    families = feature_families(features)
    positions = {column: index for index, column in enumerate(features)}
    canonical_order = lambda columns: sorted(columns, key=positions.__getitem__)
    a0 = canonical_order(families["calendario"] + families["cmo_proprio"])
    a1 = canonical_order(a0 + families["cmo_cruzado"])
    a2 = canonical_order(a1 + families["carga"])
    a3 = canonical_order(a2 + families["hidro"])
    return {"A0 calendario + CMO proprio": a0,
            "A1 + CMO dos outros subsistemas": a1,
            "A2 + carga e intercambio": a2,
            "A3 + hidrologia (completo)": a3}


def predict_month(train, test, feature_columns, variant, training_features):
    """Fit the requested variant on a training month and predict the test month."""
    if variant == "direto":
        model = lgb.LGBMRegressor(**PARAMS).fit(training_features, train["y"])
        return model.predict(test[feature_columns])
    if variant == "residual":
        model = lgb.LGBMRegressor(**PARAMS).fit(
            training_features, train["y"] - train["naive_sazonal"]
        )
        return test["naive_sazonal"].to_numpy() + model.predict(test[feature_columns])
    if variant == "duas_partes":
        at_floor = train["y"] <= CMO_FLOOR_THRESHOLD
        classifier = lgb.LGBMClassifier(**{**PARAMS, "objective": "binary"}).fit(
            training_features, at_floor.astype(int)
        )
        regressor = lgb.LGBMRegressor(**PARAMS).fit(
            training_features[~at_floor.to_numpy()], train.loc[~at_floor, "y"]
        )
        floor_probability = classifier.predict_proba(test[feature_columns])[:, 1]
        return np.where(
            floor_probability > 0.5, float(train.loc[at_floor, "y"].median()),
            regressor.predict(test[feature_columns])
        )
    raise SystemExit(f"unknown model variant: {variant}")


def run_rolling_origin(panel, feature_columns, test_days, variant,
                       shuffle_features=False, seed=RANDOM_SEED):
    """Use the same monthly rolling-origin schedule and recalibration as step 3."""
    prediction_frames = []
    rng = np.random.default_rng(seed)
    for month in sorted(pd.Series(test_days).dt.to_period("M").unique()):
        month_start = month.to_timestamp()
        next_month_start = month_start + pd.offsets.MonthBegin(1)
        train = panel[panel["dia"] < month_start]
        test = panel[(panel["dia"] >= month_start) & (panel["dia"] < next_month_start)]
        if test.empty:
            continue
        training_features = train[feature_columns]
        if shuffle_features:
            training_features = training_features.iloc[
                rng.permutation(len(training_features))
            ].reset_index(drop=True)
            training_features.index = train.index
        predictions = predict_month(train, test, feature_columns, variant,
                                    training_features)
        prediction_frames.append(pd.DataFrame({
            "dia": test["dia"].to_numpy(),
            "y": test["y"].to_numpy(),
            "adv": test["naive_sazonal"].to_numpy(),
            "p": predictions,
        }))
    return pd.concat(prediction_frames, ignore_index=True)


def skill_score(predictions):
    return 100.0 * (1 - np.abs(predictions["y"] - predictions["p"]).mean() /
                    np.abs(predictions["y"] - predictions["adv"]).mean())


def bootstrap_skill_interval(predictions, n_bootstrap=N_BOOTSTRAP, seed=RANDOM_SEED):
    grouped = predictions.groupby("dia")
    model_error = grouped.apply(
        lambda day: np.abs(day["y"] - day["p"]).sum(), include_groups=False
    ).to_numpy()
    baseline_error = grouped.apply(
        lambda day: np.abs(day["y"] - day["adv"]).sum(), include_groups=False
    ).to_numpy()
    group_sizes = grouped.size().to_numpy()
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(group_sizes), size=(n_bootstrap, len(group_sizes)))
    skill = 100.0 * (
        1 - (model_error[indices].sum(1) / group_sizes[indices].sum(1))
        / (baseline_error[indices].sum(1) / group_sizes[indices].sum(1))
    )
    return [float(np.percentile(skill, 2.5)), float(np.percentile(skill, 97.5))]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    step_3_results = json.loads(RESULT_PATH.read_text())
    # Use the variant with the lowest step 3 MAE; do not select it again here.
    candidate_errors = {
        variant: step_3_results["erros"][f"lgbm_{variant}"]["mae"]
        for variant in ("direto", "residual", "duas_partes")
    }
    selected_variant = min(candidate_errors, key=candidate_errors.get)
    print(f"ablation variant: {selected_variant} (step 3 MAE: "
          + ", ".join(f"{name} {value:.2f}" for name, value in candidate_errors.items()) + ")")

    panel = pd.read_parquet(PANEL_PATH)
    panel["sub"] = panel["sub"].astype("category")
    features = model_columns(panel)
    days = np.sort(panel["dia"].unique())
    test_days = days[days >= days[int(len(days) * INITIAL_TRAIN_FRACTION)]]

    start_time = time.time()
    output = {"variante_ablada": selected_variant, "adversario": BASELINE,
              "familias": {name: len(columns)
                           for name, columns in feature_families(features).items()},
              "ablacao": {}, "nulo": {}, "horizonte": {}}

    for set_name, columns in nested_feature_sets(features).items():
        predictions = run_rolling_origin(panel, columns, test_days, selected_variant)
        output["ablacao"][set_name] = dict(
            n_features=len(columns),
            mae=float(np.abs(predictions["y"] - predictions["p"]).mean()),
            habilidade=skill_score(predictions),
            ic95=bootstrap_skill_interval(predictions),
        )
        print(f"{set_name:34s} {len(columns):3d} features  "
              f"skill {output['ablacao'][set_name]['habilidade']:+.2f}%")

    shuffled_predictions = run_rolling_origin(
        panel, features, test_days, selected_variant, shuffle_features=True
    )
    output["nulo"] = dict(habilidade=skill_score(shuffled_predictions),
                          ic95=bootstrap_skill_interval(shuffled_predictions))
    print(f"{'PERMUTATION NULL':34s}      "
          f"skill {output['nulo']['habilidade']:+.2f}%")

    # Build a new panel with the target at D+1 and shift the full gate along
    # with it. Reuse the same test window as step 3.
    source_series = (cmo(), hourly_load(), net_interchange(), ear(), ear_sin(), ena())
    panel_d_plus_1 = build_panel(*source_series, horizon=2)
    panel_d_plus_1 = panel_d_plus_1[panel_d_plus_1["y"].notna()]
    lag_1, lag_7 = "cmo_l2", "cmo_l8"
    panel_d_plus_1 = panel_d_plus_1[
        panel_d_plus_1[lag_1].notna() & panel_d_plus_1[lag_7].notna()
    ].copy()
    panel_d_plus_1["naive_sazonal"] = seasonal_naive(
        panel_d_plus_1[lag_1].to_numpy(), panel_d_plus_1[lag_7].to_numpy(),
        panel_d_plus_1["dow"].to_numpy()
    )
    panel_d_plus_1["sub"] = panel_d_plus_1["sub"].astype("category")
    features_d_plus_1 = model_columns(panel_d_plus_1)
    days_d_plus_1 = np.sort(panel_d_plus_1["dia"].unique())
    days_d_plus_1 = days_d_plus_1[days_d_plus_1 >= test_days.min()]
    predictions_d_plus_1 = run_rolling_origin(
        panel_d_plus_1, features_d_plus_1, days_d_plus_1, selected_variant
    )
    predictions_d = run_rolling_origin(
        panel, features, days[days >= days_d_plus_1.min()], selected_variant
    )
    output["horizonte"] = {
        "D (passo 3)": dict(
            mae_modelo=float(np.abs(predictions_d["y"] - predictions_d["p"]).mean()),
            mae_adversario=float(np.abs(predictions_d["y"] - predictions_d["adv"]).mean()),
            habilidade=skill_score(predictions_d),
            ic95=bootstrap_skill_interval(predictions_d),
        ),
        "D+1": dict(
            mae_modelo=float(np.abs(predictions_d_plus_1["y"] - predictions_d_plus_1["p"]).mean()),
            mae_adversario=float(np.abs(predictions_d_plus_1["y"] - predictions_d_plus_1["adv"]).mean()),
            habilidade=skill_score(predictions_d_plus_1),
            ic95=bootstrap_skill_interval(predictions_d_plus_1),
        ),
    }
    horizon_results = output["horizonte"]
    output["horizonte"]["erro_cresce"] = bool(
        horizon_results["D+1"]["mae_modelo"] > horizon_results["D (passo 3)"]["mae_modelo"]
        and horizon_results["D+1"]["mae_adversario"] > horizon_results["D (passo 3)"]["mae_adversario"]
    )
    for horizon_label in ("D (passo 3)", "D+1"):
        print(f"horizon {horizon_label:12s} model {horizon_results[horizon_label]['mae_modelo']:6.2f}  "
              f"baseline {horizon_results[horizon_label]['mae_adversario']:6.2f}  "
              f"skill {horizon_results[horizon_label]['habilidade']:+6.2f}%  "
              f"95% CI [{horizon_results[horizon_label]['ic95'][0]:+.2f}; "
              f"{horizon_results[horizon_label]['ic95'][1]:+.2f}]")
    print(f"Error increases with horizon: {output['horizonte']['erro_cresce']}")

    output["custo_s"] = round(time.time() - start_time, 1)
    ABLATION_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    if not output["horizonte"]["erro_cresce"]:
        raise SystemExit("horizon control failed: error did not increase")


if __name__ == "__main__":
    main()
