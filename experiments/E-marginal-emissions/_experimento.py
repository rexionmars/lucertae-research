"""F14: forecast the marginal emission factor 24 hours ahead against persistence.

WHY 24 HOURS INSTEAD OF THE CURRENT HOUR. The MCTI Operating Margin factor is
derived from dispatch, and the panel features are dispatch variables. Fitting
MO(h) to state(h) would reproduce the MCTI formula and succeed by construction:
that would be a tautology, not a result. The meaningful question is predictive:
can today's information forecast tomorrow's factor, which is what a load shift
requires, using only information available by h to predict h+24?

CONTROLS
  C1  24-hour persistence is the benchmark. Failure to beat it is reported as
      a negative result.
  C2  hour-by-month climatology, fitted on the training set only.
  C3  chronological split: train through 2025-12-31 and test in 2026.
  C4  day-block bootstrap because adjacent hours are not independent.
  C5  POSITIVE CONTROL: MO(h) ~ state(h). If the pipeline cannot recover this
      signal, the negative C1 result indicates a join bug, not a finding.
  C6  alternative split at 2025-H2. A negative result at only one cutoff may
      indicate a regime effect rather than a feature limitation.

Run from the repository root: .venv/bin/python
    experiments/E-marginal-emissions/_experimento.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RNG = np.random.default_rng(20260906)
TEST_CUTOFF = pd.Timestamp("2026-01-01")
FORECAST_HORIZON_HOURS = 24


def mean_absolute_error(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def main():
    target_series = pd.read_parquet("data/interim/mo_horario.parquet")["mo"]
    features = pd.read_parquet("data/interim/painel_sistema_limpo.parquet")

    # The target is h+24 and features are at h, so only past information enters.
    forecast_target = target_series.shift(-FORECAST_HORIZON_HOURS).rename("y")
    panel = (features.join(forecast_target, how="inner")
             .join(target_series.rename("mo_agora"), how="inner").dropna())
    # Persistence uses today's factor at the same hour to forecast tomorrow's.
    panel["persist"] = panel["mo_agora"]

    train, test = panel[panel.index < TEST_CUTOFF], panel[panel.index >= TEST_CUTOFF]
    feature_columns = list(features.columns) + ["mo_agora"]
    print(f"train {len(train):,} h ({train.index.min():%Y-%m-%d} to {train.index.max():%Y-%m-%d}) | "
          f"test {len(test):,} h ({test.index.min():%Y-%m-%d} to {test.index.max():%Y-%m-%d})")

    # C2: hour-by-month climatology, fitted on the training set only.
    climatology = train.groupby([train.index.month, train.index.hour])["y"].mean()
    test_climatology = np.array([
        climatology.get((timestamp.month, timestamp.hour), train["y"].mean())
        for timestamp in test.index
    ])

    model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, random_state=0
    ).fit(train[feature_columns], train["y"])
    predictions = model.predict(test[feature_columns])

    errors = {"24-hour persistence": mean_absolute_error(test["y"], test["persist"]),
              "hour-by-month climatology": mean_absolute_error(test["y"], test_climatology),
              "model (system state + current factor)": mean_absolute_error(test["y"], predictions)}
    print("\nTest MAE, tCO2/MWh")
    for label, value in errors.items():
        print(f"  {label:38s} {value:.5f}")

    baseline_error = errors["24-hour persistence"]
    skill = 1 - errors["model (system state + current factor)"] / baseline_error
    print(f"\nSkill over persistence: {100 * skill:+.1f}%")

    # C4: day-block bootstrap.
    days = test.index.normalize()
    unique_days = np.unique(days)
    model_errors = np.abs(test["y"].values - predictions)
    persistence_errors = np.abs(test["y"].values - test["persist"].values)
    bootstrap_scores = []
    for _ in range(2000):
        sampled_days = RNG.choice(unique_days, size=len(unique_days), replace=True)
        selected_rows = np.concatenate([np.where(days == day)[0] for day in sampled_days])
        bootstrap_scores.append(
            1 - model_errors[selected_rows].mean() / persistence_errors[selected_rows].mean()
        )
    lower, upper = np.percentile(bootstrap_scores, [2.5, 97.5])
    print(f"95% day-block CI ({len(unique_days)} days): [{100 * lower:+.1f}%, {100 * upper:+.1f}%]")
    print("VERDICT:", "beats persistence" if lower > 0 else
          "does not beat persistence with a distinguishable effect")

    pd.DataFrame({"h": test.index, "y": test["y"].values, "modelo": predictions,
                  "persist": test["persist"].values, "clim": test_climatology}
                 ).to_parquet("data/interim/f14_teste.parquet", index=False)




def run_controls():
    """Run C5 and C6 separately: do they test whether the negative result is real?"""
    target_series = pd.read_parquet("data/interim/mo_horario.parquet")["mo"]
    features = pd.read_parquet("data/interim/painel_sistema_limpo.parquet")

    # C5 positive control: predict the current-hour factor from the current state.
    control_panel = features.join(target_series.rename("y"), how="inner").dropna()
    train = control_panel[control_panel.index < TEST_CUTOFF]
    test = control_panel[control_panel.index >= TEST_CUTOFF]
    model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, random_state=0
    ).fit(train[features.columns], train["y"])
    predictions = model.predict(test[features.columns])
    r2 = 1 - np.var(test["y"] - predictions) / np.var(test["y"])
    print(f"\nC5 positive control MO(h) ~ state(h): MAE {mean_absolute_error(test['y'], predictions):.5f}  R2 {r2:.3f}")
    assert r2 > 0.3, "pipeline cannot recover the contemporaneous signal; the negative result may be a bug"

    forecast_panel = (features.join(
        target_series.shift(-FORECAST_HORIZON_HOURS).rename("y"), how="inner"
    ).join(target_series.rename("mo_agora"), how="inner").dropna())
    feature_columns = list(features.columns) + ["mo_agora"]

    # In-sample: the model learns, but may also learn the period.
    train = forecast_panel[forecast_panel.index < TEST_CUTOFF]
    in_sample_model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, random_state=0
    ).fit(train[feature_columns], train["y"])
    in_sample_predictions = in_sample_model.predict(train[feature_columns])
    in_sample_skill = 1 - mean_absolute_error(train["y"], in_sample_predictions) / mean_absolute_error(
        train["y"], train["mo_agora"]
    )
    print(f"   in-sample skill: {100 * in_sample_skill:+.1f}%")

    # C6: alternative cutoff.
    alternative_cutoff = pd.Timestamp("2025-07-01")
    train_alt = forecast_panel[forecast_panel.index < alternative_cutoff]
    test_alt = forecast_panel[
        (forecast_panel.index >= alternative_cutoff)
        & (forecast_panel.index < TEST_CUTOFF)
    ]
    alternative_model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, random_state=0
    ).fit(train_alt[feature_columns], train_alt["y"])
    alternative_predictions = alternative_model.predict(test_alt[feature_columns])
    alternative_skill = 1 - mean_absolute_error(
        test_alt["y"], alternative_predictions
    ) / mean_absolute_error(test_alt["y"], test_alt["mo_agora"])
    print(f"C6 alternative cutoff 2025-H2 (n={len(test_alt):,}): skill {100 * alternative_skill:+.1f}%")


if __name__ == "__main__":
    main()
    run_controls()
