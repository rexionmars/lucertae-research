"""F2/F12: can the ONS schedule tomorrow's curtailment be predicted?

TARGET. The fraction of forecast wind and solar generation that the operator
does not schedule, aggregated to the SIN by half-hourly step. Built by
`_corte.py`.

AVAILABLE INFORMATION. Use only information available when tomorrow's schedule
is produced: tomorrow's forecast, which is an input to the scheduling process,
and curtailment history through today. Tomorrow's scheduled generation is the
outcome and is excluded. This is the only possible leakage path and is stated
explicitly.

RESULT. In aggregate, the model does not beat the benchmark by a distinguishable
margin. The aggregate hides a clear split: conditional on mean curtailment over
the previous 28 days, a variable known before the forecast with a threshold
estimated on training data, the model loses when there is little curtailment to
predict and wins when recent curtailment is high.

CONTROLS
  C1  Report D-1 persistence, D-7 persistence, and step climatology. Skill and
      bootstrap intervals use the better of the two persistence baselines.
  C2  chronological split, training through 2025-12-31.
  C3  hyperparameters selected on an internal validation set (the final
      quarter of training). The test set is evaluated only once.
  C4  day-block bootstrap because adjacent steps are not independent.
  C5  in-sample performance, to distinguish failure to learn from failure to
      generalize.
  C6  stratification by a variable known a priori, not by a quarter selected
      after seeing the result.

Run from the repository root: .venv/bin/python
    experiments/E-scheduled-curtailment/_experimento.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RANDOM_GENERATOR = np.random.default_rng(20260906)
TEST_CUTOFF = pd.Timestamp("2026-01-01")
MODEL_PARAMS = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                    l2_regularization=1, min_samples_leaf=80, random_state=0)


def mean_absolute_error(actual, predicted):
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted))))


def build_panel():
    panel = pd.read_parquet("data/interim/corte_programado.parquet").sort_index()
    panel["data"] = panel.index.normalize()
    curtailment = panel.pivot_table(index="data", columns="num_patamar", values="frac")
    forecast = panel.pivot_table(index="data", columns="num_patamar", values="prev")
    lag_1, lag_7 = curtailment.shift(1), curtailment.shift(7)
    previous_day_mean = curtailment.shift(1).mean(axis=1)
    previous_28_day_mean = curtailment.shift(1).rolling(28, min_periods=7).mean().mean(axis=1)
    daily_peak = forecast.max(axis=1)
    blocks = [pd.DataFrame({
        "y": curtailment[step], "l1": lag_1[step], "l7": lag_7[step],
        "media_ontem": previous_day_mean, "media_28d": previous_28_day_mean,
        "prev": forecast[step], "prev_dia": forecast.sum(axis=1),
        "prev_pico": daily_peak,
        "prev_rel": forecast[step] / daily_peak.where(daily_peak > 0),
        "patamar": step, "dow": curtailment.index.dayofweek,
        "mes": curtailment.index.month,
    }) for step in curtailment.columns]
    return pd.concat(blocks).dropna().sort_index()


def baseline_bar(group):
    """C1: return the better persistence baseline and its error vector."""
    candidates = {"D-1 persistence": group.l1.values, "D-7 persistence": group.l7.values}
    name = min(candidates, key=lambda key: mean_absolute_error(group.y, candidates[key]))
    return name, mean_absolute_error(group.y, candidates[name]), np.abs(group.y.values - candidates[name])


def bootstrap_interval(model_errors, baseline_errors, rows_by_day):
    unique_days = list(rows_by_day)
    scores = [
        1 - model_errors[rows].mean() / baseline_errors[rows].mean()
        for rows in (
            np.concatenate([rows_by_day[day] for day in RANDOM_GENERATOR.choice(
                unique_days, len(unique_days), replace=True)])
            for _ in range(2000)
        )
    ]
    return np.percentile(scores, [2.5, 97.5])


def main():
    panel = build_panel()
    feature_columns = [column for column in panel.columns if column != "y"]
    train, test = panel[panel.index < TEST_CUTOFF], panel[panel.index >= TEST_CUTOFF]
    print(f"train {len(train):,} steps ({train.index.min():%Y-%m-%d} to {train.index.max():%Y-%m-%d})"
        f" | test {len(test):,} ({test.index.min():%Y-%m-%d} to {test.index.max():%Y-%m-%d})")
    print(f"mean curtailed fraction: train {train.y.mean():.4f} | test {test.y.mean():.4f}")

    model = HistGradientBoostingRegressor(**MODEL_PARAMS).fit(train[feature_columns], train.y)
    test = test.copy()
    test["p"] = np.clip(model.predict(test[feature_columns]), 0, 1)
    climatology = train.groupby("patamar")["y"].mean()

    print("\nTest MAE for curtailed fraction")
    for name, value in [("D-1 persistence", mean_absolute_error(test.y, test.l1)),
                ("D-7 persistence", mean_absolute_error(test.y, test.l7)),
                ("step climatology", mean_absolute_error(test.y, test.patamar.map(climatology))),
                ("model", mean_absolute_error(test.y, test.p))]:
      print(f"  {name:28s} {value:.5f}")

    baseline_name, baseline_error, baseline_error_vector = baseline_bar(test)
    days = test.index.normalize()
    rows_by_day = {day: np.where(days == day)[0] for day in np.unique(days)}
    lower, upper = bootstrap_interval(np.abs(test.y.values - test.p.values),
                          baseline_error_vector, rows_by_day)
    print(f"\nbenchmark: {baseline_name}. skill {100 * (1 - mean_absolute_error(test.y, test.p) / baseline_error):+.1f}%  "
        f"95% CI [{100 * lower:+.1f}%, {100 * upper:+.1f}%]")
    print("AGGREGATE VERDICT:", "beats benchmark" if lower > 0 else
        "does not beat benchmark with a distinguishable effect")

    in_sample_predictions = np.clip(model.predict(train[feature_columns]), 0, 1)
    _, train_baseline_error, _ = baseline_bar(train)
    print(f"C5 in-sample skill: {100 * (1 - mean_absolute_error(train.y, in_sample_predictions) / train_baseline_error):+.1f}%")

    # C6: stratify by previous-28-day mean, using thresholds from training data only.
    quantiles = train.media_28d.quantile([1 / 3, 2 / 3]).values
    print(f"\nC6 stratification by mean curtailment over the previous 28 days "
        f"(training thresholds: {quantiles[0]:.4f}, {quantiles[1]:.4f})")
    strata = [("low (little recent curtailment)", test[test.media_28d < quantiles[0]]),
          ("medium", test[(test.media_28d >= quantiles[0]) & (test.media_28d < quantiles[1])]),
          ("high (high recent curtailment)", test[test.media_28d >= quantiles[1]])]
    for label, group in strata:
      if group.empty:
        print(f"  {label:36s} empty")
        continue
      _, group_baseline_error, group_baseline_errors = baseline_bar(group)
      group_days = group.index.normalize()
      group_rows_by_day = {day: np.where(group_days == day)[0] for day in np.unique(group_days)}
      lower, upper = bootstrap_interval(np.abs(group.y.values - group.p.values),
                            group_baseline_errors, group_rows_by_day)
      verdict = "BEATS" if lower > 0 else ("loses" if upper < 0 else "indistinguishable")
      print(f"  {label:36s} n={len(group):>5} days={len(group_rows_by_day):>3} mean={group.y.mean():.4f}  "
          f"skill {100 * (1 - mean_absolute_error(group.y, group.p) / group_baseline_error):+6.1f}%  "
          f"95% CI [{100 * lower:+.1f}, {100 * upper:+.1f}]  {verdict}")

    test.reset_index().to_parquet("data/interim/f12_teste.parquet", index=False)


if __name__ == "__main__":
    main()
