"""Step 3 -- measurement and evaluation of the decision rule.

Refuses to run if step 2 marked the panel as blocked.

PART A, descriptive, before any model: how much of the thermal generation in the SIN is
operational decision and not price, scheduled and verified, by reason and by month.
The residual identity bucket enters as its own bucket and is never redistributed.

PART B, decision: does the day-ahead schedule hold? The target is the bias
b = verified_out_of_merit - scheduled_out_of_merit, aggregated at the SIN level by hour.
The question is not "do I forecast well?" but "is there a persistent bias that someone
exposed to the obligation could correct the day before?"

The design constraint comes from control C5: month M data are only published at the end of
month M+1. Therefore, for an hour in month M, the most recent knowable verified value is the
one from month M-2. Every comparison base respects this and none uses the previous 7 days,
which would introduce leakage of 30-60 days.

Output: data/interim/E-despacho-termico/resultado.json
"""
import json
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _comum import CONTROLS_PATH, OUT_OF_MERIT_REASONS, PANEL_PATH, RESULT_PATH

RNG = np.random.default_rng(20260906)
N_BOOTSTRAP = 2000


def require_controls():
    if not CONTROLS_PATH.exists():
        sys.exit("run 2_controles.py before this step")
    controls = json.loads(CONTROLS_PATH.read_text())
    if controls["bloqueado"]:
        sys.exit("controls BLOCKED the panel; step 3 will not run")
    return controls


def part_a(panel):
    """Descriptive summary. No model involved."""
    output = {}
    for side in ("prog", "verif"):
        total = panel[f"{side}_total_pub"].sum()
        merit = panel[f"{side}_merito"].sum()
        out_of_merit = panel[f"{side}_fora"].sum()
        residual = total - merit - out_of_merit
        output[side] = {"total_TWh": total / 1e6, "merito_TWh": merit / 1e6,
                        "fora_TWh": out_of_merit / 1e6, "residuo_TWh": residual / 1e6,
                        "fracao_fora": float(out_of_merit / total)}
        print(f"\n{side.upper()}  total {total/1e6:8.2f} TWh")
        print(f"  merit order          {merit/1e6:8.2f} TWh   {merit/total:6.2%}")
        print(f"  OUT of merit         {out_of_merit/1e6:8.2f} TWh   {out_of_merit/total:6.2%}")
        print(f"  residual             {residual/1e6:7.3f} TWh   {residual/total:6.3%}")
        print("  by reason:")
        reasons = {}
        for reason in OUT_OF_MERIT_REASONS:
            value = panel[f"val_{side}{reason}"].sum()
            reasons[reason] = value / 1e6
            if value > 0:
                print(f"    {reason:22s} {value/1e6:8.3f} TWh   {value/total:6.3%} of total   {value/out_of_merit:6.2%} of out-of-merit")
        output[side]["motivos_TWh"] = reasons
    return output


def sin_series(panel):
    """Aggregate to the SIN level by hour; the decision is at the system level, not the plant."""
    series = panel.groupby("din_instante").agg(
        prog_total=("prog_total_pub", "sum"), verif_total=("verif_total_pub", "sum"),
        prog_fora=("prog_fora", "sum"), verif_fora=("verif_fora", "sum")).sort_index()
    series["d"] = series.verif_fora - series.prog_fora
    series["mes"] = series.index.to_period("M")
    series["hora"] = series.index.hour
    return series


def known_baselines(series):
    """Build comparison baselines that respect publication timing: for month M, only months <= M-2.

    Central estimator: MEDIAN, not mean. The reported loss is MAE, and the constant that
    minimizes MAE is the median. Using the mean here would penalize the baseline for an
    estimator incompatible with the loss, and the result would reflect the analyst's choice
    rather than the publication delay. Mean remains only as a descriptive statistic in the printout.
    """
    months = sorted(series.mes.unique())
    positions = {month: idx for idx, month in enumerate(months)}
    series = series.copy()
    series["b0"] = 0.0
    series["b1"] = np.nan          # median by hour of day, last published month
    series["b2"] = np.nan          # median of the last published month
    series["b_oraculo"] = np.nan   # positive control: median of the same month
    for month in months:
        idx = positions[month]
        target = series.mes == month
        if idx >= 2:
            source = series[series.mes == months[idx - 2]]
            by_hour = source.groupby("hora").d.median()
            series.loc[target, "b1"] = series.loc[target, "hora"].map(by_hour).values
            series.loc[target, "b2"] = source.d.median()
        series.loc[target, "b_oraculo"] = series.loc[target, "d"].median()
    return series


def monthly_drift(series):
    """How much the bias moves from month to month. This is what determines whether a month
    published with a two-month delay still describes the current month."""
    grouped = series.groupby("mes").d.median()
    step = grouped.diff().abs()
    print("\n  bias drift (median deviation, MWh/h):")
    print(f"    range {grouped.min():+.0f} to {grouped.max():+.0f}  |  amplitude {grouped.max()-grouped.min():.0f}")
    print(f"    month-to-month step: median {step.median():.0f}, max {step.max():.0f}")
    print(f"    typical step / bias amplitude = {step.median()/(grouped.max()-grouped.min()):.2f}")
    return {"mediana_por_mes": {str(key): float(value) for key, value in grouped.items()},
            "passo_mediano": float(step.median()), "passo_max": float(step.max()),
            "amplitude": float(grouped.max() - grouped.min())}


def mae(y, y_pred):
    return float(np.mean(np.abs(y - y_pred)))


def bootstrap_skill(y, base, alternative, days, n=N_BOOTSTRAP):
    """Day-block bootstrap for the skill of `alternative` over `base`."""
    unique_days = np.unique(days)
    scores = np.empty(n)
    idx = {day: np.where(days == day)[0] for day in unique_days}
    for k in range(n):
        pick = RNG.choice(unique_days, size=len(unique_days), replace=True)
        selected = np.concatenate([idx[day] for day in pick])
        mb, ma = mae(y[selected], base[selected]), mae(y[selected], alternative[selected])
        scores[k] = (mb - ma) / mb if mb > 0 else np.nan
    return float(np.nanpercentile(scores, 2.5)), float(np.nanpercentile(scores, 97.5))


def part_b(series):
    series = known_baselines(series)
    available = series.dropna(subset=["b1", "b2"]).copy()
    y = available.d.values
    days = available.index.normalize().values
    print(f"\n\nPART B -- schedule deviation, {len(available):,} available hours "
          f"from {len(series):,} ({available.index.min().date()} to {available.index.max().date()})")
    print("  the first two months are excluded: no prior published month exists")
    print("\n  deviation d = verified_out_of_merit - scheduled_out_of_merit")
    print(f"    mean {y.mean():+10.1f} MWh/h   median {np.median(y):+10.1f}   "
          f"std {y.std():9.1f}")
    print(f"    mean scheduled out-of-merit {available.prog_fora.mean():,.0f} MWh/h "
          f"-> relative bias {y.mean()/available.prog_fora.mean():+.2%}")

    result = {"horas": int(len(available)), "inicio": str(available.index.min()), "fim": str(available.index.max()),
              "d_media": float(y.mean()), "d_mediana": float(np.median(y)),
              "fora_prog_medio": float(available.prog_fora.mean()), "bases": {}}

    baseline_mae = mae(y, available.b0.values)
    print(f"\n  {'base':34s} {'MAE (MWh/h)':>13s} {'skill':>11s}  {'IC 95%':>20s}")
    print(f"  {'B0  unbiased schedule':34s} {baseline_mae:13.1f} {'--':>11s}")
    for name, column in [("B1  median by hour, month M-2", "b1"),
                         ("B2  median of month M-2", "b2"),
                         ("ORACLE  median of same month", "b_oraculo")]:
        model_mae = mae(y, available[column].values)
        skill = (baseline_mae - model_mae) / baseline_mae
        lo, hi = bootstrap_skill(y, available.b0.values, available[column].values, days)
        print(f"  {name:34s} {model_mae:13.1f} {skill:+10.2%}  [{lo:+7.2%}, {hi:+7.2%}]")
        result["bases"][column] = {"nome": name, "mae": model_mae, "habilidade": float(skill),
                                   "ic95": [lo, hi]}
    result["bases"]["b0"] = {"nome": "B0 unbiased schedule", "mae": baseline_mae,
                              "habilidade": 0.0, "ic95": [0.0, 0.0]}
    result["deriva"] = monthly_drift(available)
    return result


def main():
    require_controls()
    panel = pd.read_parquet(PANEL_PATH)
    print(f"panel available: {len(panel):,} rows, {panel.din_instante.min()} to {panel.din_instante.max()}")

    analysis_a = part_a(panel)
    system = sin_series(panel)
    analysis_b = part_b(system)

    RESULT_PATH.write_text(json.dumps({"parte_a": analysis_a, "parte_b": analysis_b}, indent=1, ensure_ascii=False))
    print(f"\nsaved: {RESULT_PATH}")


if __name__ == "__main__":
    main()
