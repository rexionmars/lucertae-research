"""Step 4: locate model errors without fitting additional models.

Run from the repository root after step 3:
    .venv/bin/python experiments/E-cmo-price/4_decomposicao.py

Analyze prediction errors by quantile, at the CMO floor, and after separating
daily level from within-day shape. MAE weights every row equally while RMSE
weights the tail more heavily; the quantile table shows where metric rankings
diverge.

The decomposition separates the daily mean level, influenced by hydrology and
energy balance, from each half-hour's deviation around that mean, influenced by
load and same-day solar generation. The two components have different natural
predictors, and the decomposition indicates where each predictor gains or
loses.

MAE is not additive over this decomposition: a row's error is the sum of level
and shape errors, while |a+b| is not |a|+|b|. A predictor can therefore improve
both components separately yet lose on the total; this is a possible result,
not an inconsistency.

Regime analysis uses `cmopiso_d1` and `cmomed_d1`, the previous day's floor
fraction and mean. Conditioning on D-1 respects the information gate; using
target-day values would condition on the answer.
"""
import json

import numpy as np
import pandas as pd

from _comum import (CMO_FLOOR_THRESHOLD, DECOMPOSITION_PATH, OUTPUT_DIR,
                    PANEL_PATH, PREDICTIONS_PATH)
from _modelos_comum import BASELINE, PREDICTORS


def mean_absolute_error(actual, predicted):
    return float(np.abs(np.asarray(actual) - np.asarray(predicted)).mean())


def metrics_by_bin(predictions, column, bin_edges, labels):
    bins = pd.cut(predictions[column], bins=bin_edges, labels=labels, include_lowest=True)
    output = {}
    for label in labels:
        subset = predictions[bins == label]
        if len(subset) == 0:
            continue
        output[label] = dict(
            n=int(len(subset)),
            **{key: round(mean_absolute_error(subset["y"], subset[key]), 2)
               for key in PREDICTORS},
        )
    return output


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    predictions = pd.read_parquet(PREDICTIONS_PATH)
    panel_features = pd.read_parquet(PANEL_PATH)[["t", "sub", "cmopiso_d1", "cmomed_d1"]]
    predictions = predictions.merge(panel_features, on=["t", "sub"], how="left",
                                    validate="one_to_one")

    daily_group = ["sub", "dia"]
    level = predictions.groupby(daily_group)[["y"] + PREDICTORS].mean()
    shape = predictions.copy()
    for column in ["y"] + PREDICTORS:
        shape[column] = predictions[column] - predictions.groupby(daily_group)[column].transform("mean")

    absolute_errors = {key: np.abs(predictions["y"] - predictions[key])
                       for key in PREDICTORS}
    at_floor = (predictions["y"] <= CMO_FLOOR_THRESHOLD).to_numpy()
    upper_tail = (predictions["y"] > predictions["y"].quantile(0.95)).to_numpy()

    decomposition = dict(
        n_linhas=int(len(predictions)), n_dias_sub=int(len(level)),
        nivel={key: round(mean_absolute_error(level["y"], level[key]), 2) for key in PREDICTORS},
        forma={key: round(mean_absolute_error(shape["y"], shape[key]), 2) for key in PREDICTORS},
        completo={key: round(mean_absolute_error(predictions["y"], predictions[key]), 2) for key in PREDICTORS},
        fracao_variancia_do_nivel=float(
            predictions.groupby(daily_group)["y"].transform("mean").var() / predictions["y"].var()),
        fracao_variancia_do_nivel_por_sub={
            subsystem: float(group.groupby("dia")["y"].transform("mean").var() / group["y"].var())
            for subsystem, group in predictions.groupby("sub", observed=True)},
        por_piso_da_vespera=metrics_by_bin(
            predictions, "cmopiso_d1", [-0.001, 0.05, 0.35, 0.65, 1.0],
            ["ate 5%", "5 a 35%", "35 a 65%", "acima de 65%"]),
        por_nivel_da_vespera=metrics_by_bin(
            predictions, "cmomed_d1", [-100, 20, 80, 200, 10000],
            ["ate 20", "20 a 80", "80 a 200", "acima de 200"]),
        por_meia_hora={int(hour): {key: round(mean_absolute_error(group["y"], group[key]), 2)
                                   for key in PREDICTORS}
                       for hour, group in predictions.groupby("hh")},
        fracao_alvo_no_piso=float(at_floor.mean()),
        quantis_do_erro={
            str(quantile): {key: round(float(absolute_errors[key].quantile(quantile)), 2)
                            for key in PREDICTORS}
            for quantile in (0.25, 0.5, 0.75, 0.9, 0.95, 0.99)},
        fracao_de_linhas_melhor_que_adversario={
            key: float((absolute_errors[key] < absolute_errors[BASELINE]).mean())
            for key in PREDICTORS if key != BASELINE},
        no_piso={key: dict(
            preve_no_piso=float((predictions[key].to_numpy()[at_floor] <= CMO_FLOOR_THRESHOLD).mean()),
            erro_mediano=round(float(np.median(absolute_errors[key].to_numpy()[at_floor])), 2),
            erro_mediano_fora=round(float(np.median(absolute_errors[key].to_numpy()[~at_floor])), 2))
            for key in PREDICTORS},
        cauda_alta={key: round(float(absolute_errors[key].to_numpy()[upper_tail].mean()), 2)
                    for key in PREDICTORS},
        limiar_cauda_alta=round(float(predictions["y"].quantile(0.95)), 2),
    )
    DECOMPOSITION_PATH.write_text(json.dumps(decomposition, indent=2, ensure_ascii=False))

    variance_by_subsystem = decomposition["fracao_variancia_do_nivel_por_sub"]
    print(f"CMO variance explained by daily level: "
          f"{100 * decomposition['fracao_variancia_do_nivel']:.1f}% overall, "
          f"{100 * min(variance_by_subsystem.values()):.1f}% to "
          f"{100 * max(variance_by_subsystem.values()):.1f}% within subsystems")
    print(f"\n{'predictor':16s} {'overall':>10s} {'level':>10s} {'shape':>10s}")
    for predictor in PREDICTORS:
        print(f"{predictor:16s} {decomposition['completo'][predictor]:10.2f} "
              f"{decomposition['nivel'][predictor]:10.2f} {decomposition['forma'][predictor]:10.2f}")
    print(f"\n{'predictor':16s} " +
          " ".join(f"{'q' + str(quantile):>8s}" for quantile in (0.25, 0.5, 0.9, 0.95)))
    for predictor in PREDICTORS:
        print(f"{predictor:16s} " + " ".join(
            f"{decomposition['quantis_do_erro'][str(quantile)][predictor]:8.2f}"
            for quantile in (0.25, 0.5, 0.9, 0.95)))

    print(f"\nTarget at the floor in {100 * decomposition['fracao_alvo_no_piso']:.1f}% of rows")
    for predictor in PREDICTORS:
        floor_metrics = decomposition["no_piso"][predictor]
        print(f"  {predictor:16s} predicts the floor in {100 * floor_metrics['preve_no_piso']:5.1f}% of cases, "
              f"median error {floor_metrics['erro_mediano']:7.2f} (outside: {floor_metrics['erro_mediano_fora']:6.2f})")

    print("\nMAE by previous-day floor fraction")
    for label, values in decomposition["por_piso_da_vespera"].items():
        print(f"  {label:14s} n={values['n']:6d} " +
              " ".join(f"{key}={values[key]}" for key in
                       ("naive_sazonal", "lgbm_direto", "lgbm_residual",
                        "lgbm_duas_partes")))


if __name__ == "__main__":
    main()
