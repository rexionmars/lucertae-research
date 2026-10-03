"""Result registry: one schema, and adapters that READ each artifact.

The models in this repository report in five formats: `resultado.json`, fold
CSV, summary CSV and prediction parquet. This module puts them in one table.

RULE OF THIS MODULE: no number is transcribed. Every adapter OPENS the artifact
the experiment wrote. Where the artifact stores the prediction row by row, the
loss and the interval are RECOMPUTED; where it stores only the summary, the
value is read and the `method` column says so. Where there is no artifact, the
row does not appear, and the reason appears in the collection report.

The verdict is also derived, not written: it comes from the sign of the CI
bounds.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not compare rows with each other. The losses differ in nature: MAE in
R$/MWh, RMSE in W/m2, AP and AUC dimensionless. The `loss` column is in the
table to prevent reading the highest skill as the best model. Skill is only
comparable within the same estimand.

NAMES THAT STAY IN PORTUGUESE
-----------------------------
Keys and columns read from an artifact (`adversario`, `habilidade_mae`,
`horizonte`, ...) are the interface the experiments wrote and stay as they are.
"""
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluation import mae, skill, skill_ci
from .paths import PROCESSED_DIR, interim_dir

# Tolerance when a stored skill is recomputed from the stored losses.
RECHECK_TOLERANCE = 1e-4

# The fold CSV of the load-risk experiment names its baselines by position.
# The script that writes it prints what each one is, in this order.
_RISK_BASELINE_LABEL = {
    "ap_subsis_1": "subsystem",
    "ap_hora_2": "subsystem × hour",
    "ap_hora_3": "subsystem × month × hour",
}


@dataclass
class ResultRow:
    predictor: str
    role: str             # 'adversary', 'model', 'oracle', 'null', 'baseline'
    value: float
    skill: float | None = None
    ci95: tuple[float, float] | None = None

    @property
    def verdict(self) -> str:
        if self.role == "adversary":
            return "adversary"
        if self.ci95 is None:
            return "no CI"
        low, high = self.ci95
        if low > 0:
            return "beats"
        if high < 0:
            return "loses"
        return "ties"


@dataclass
class Result:
    experiment: str
    family: str
    estimand: str
    loss: str
    unit: str
    adversary: str
    n: int
    method: str                     # 'recomputed', 'read' or 'partial'
    provenance: list[str]
    rows: list[ResultRow] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        record = asdict(self)
        record["rows"] = [dict(asdict(row), verdict=row.verdict)
                          for row in self.rows]
        return record


def _day_blocks(timestamps) -> np.ndarray:
    """Day of each timestamp: the block of the bootstrap."""
    series = pd.to_datetime(pd.Series(np.asarray(timestamps)))
    return series.dt.normalize().to_numpy()


# --- adapters ---------------------------------------------------------
# One per producer. Each returns a Result or raises FileNotFoundError.

def _cmo_price() -> Result:
    path = interim_dir() / "E-cmo-price" / "resultado.json"
    stored = json.loads(path.read_text())
    adversary = stored["adversario"]
    rows = [ResultRow(adversary, "adversary", stored["erros"][adversary]["mae"])]
    role_of = {"oraculo_nivel": "oracle", "climatologia": "baseline",
               "cmo_l1": "baseline", "cmo_l7": "baseline"}
    # The artifact stores skill and its interval in percent.
    for predictor, entry in stored["habilidade"].items():
        low, high = entry["ic95"]
        rows.append(ResultRow(
            predictor, role_of.get(predictor, "model"),
            stored["erros"][predictor]["mae"],
            entry["habilidade_mae"] / 100.0, (low / 100.0, high / 100.0)))
    return Result(
        experiment="E-cmo-price", family="F11",
        estimand="half-hourly CMO of day D", loss="MAE", unit="R$/MWh",
        adversary=adversary, n=stored["n_linhas"], method="read",
        provenance=[str(path)], rows=rows,
        note="CI by resampling days, 2,000 repetitions")


def _poa_nowcasting() -> Result:
    skill_path = PROCESSED_DIR / "nowcast_habilidade.csv"
    controls_path = PROCESSED_DIR / "nowcast_controles.csv"
    intervals = pd.read_csv(controls_path)[["horizonte", "ic_lo", "ic_hi"]]
    table = pd.read_csv(skill_path).merge(intervals, on="horizonte")
    # Recheck: the stored skill must follow from the stored RMSEs.
    recomputed = 1 - table["rmse_LightGBM"] / table["rmse_inteligente"]
    if not np.allclose(recomputed, table["habilidade"], atol=RECHECK_TOLERANCE):
        raise ValueError(
            "nowcast: stored skill does not match the stored RMSEs")
    adversary = "clear-sky index persistence"
    rows = [ResultRow(adversary, "adversary",
                      float(table["rmse_inteligente"].mean()))]
    for _, horizon in table.iterrows():
        rows.append(ResultRow(
            f"LightGBM {horizon['horizonte']}", "model",
            float(horizon["rmse_LightGBM"]), float(horizon["habilidade"]),
            (float(horizon["ic_lo"]), float(horizon["ic_hi"]))))
    return Result(
        experiment="E-nowcasting-poa", family="F1/F2", estimand="POA at t+h",
        loss="RMSE", unit="W/m2", adversary=adversary,
        n=int(table["n"].sum()), method="recomputed",
        provenance=[str(skill_path), str(controls_path)], rows=rows,
        note="three horizons; the adversary RMSE is the mean of the three")


def _poa_neighbourhood() -> Result:
    path = PROCESSED_DIR / "nowcast_vizinhanca.csv"
    table = pd.read_csv(path)
    adversary = "own past only"
    rows = [ResultRow(adversary, "adversary", float("nan"),
                      float(table["hab_proprio"].iloc[0]))]
    for _, horizon in table.iterrows():
        rows.append(ResultRow(
            f"+ 4 neighbours {horizon['horizonte']}", "model", float("nan"),
            float(horizon["ganho"]),
            (float(horizon["ic_lo"]), float(horizon["ic_hi"]))))
        rows.append(ResultRow(
            f"spatial null {horizon['horizonte']}", "null", float("nan"),
            float(horizon["hab_nulo"])))
    return Result(
        experiment="E-nowcasting-poa · neighbourhood", family="F1/F2",
        estimand="POA with neighbours", loss="RMSE", unit="W/m2",
        adversary=adversary, n=int(table["n"].sum()), method="read",
        provenance=[str(path)], rows=rows,
        note="the gain is over the plant's own past; the spatial null "
             "permutes which neighbour goes to which plant")


def _curtailment_models() -> Result:
    path = PROCESSED_DIR / "ml_modelos.csv"
    table = pd.read_csv(path)
    rows = [ResultRow(model["modelo"].strip(), "model",
                      float(model["auc_global"]))
            for _, model in table.iterrows()]
    return Result(
        experiment="E-when-which", family="F12",
        estimand="curtailment in the hour, by plant", loss="AUC", unit="—",
        adversary="no naive adversary", n=int(table["n_treino"].iloc[0]),
        method="read", provenance=[str(path)], rows=rows,
        note="nested models: the reading is the contrast between them, not "
             "the skill over a baseline. The CI cannot be recomputed as a "
             "ratio of aggregates, which is the method of "
             "`evaluation.skill_ci`")


def _scheduled_curtailment() -> Result:
    path = interim_dir() / "f12_teste.parquet"
    test = pd.read_parquet(path)
    blocks = _day_blocks(test["data"])
    candidates = {"persistence D-1": test["l1"], "persistence D-7": test["l7"]}
    # The adversary is the candidate baseline with the lowest loss.
    adversary = min(candidates, key=lambda name: mae(test["y"], candidates[name]))
    adversary_pred = candidates[adversary]
    rows = [ResultRow(adversary, "adversary", mae(test["y"], adversary_pred))]
    for name, prediction in candidates.items():
        if name != adversary:
            rows.append(ResultRow(name, "baseline", mae(test["y"], prediction)))
    rows.append(ResultRow(
        "LightGBM", "model", mae(test["y"], test["p"]),
        skill(test["y"], test["p"], adversary_pred),
        skill_ci(test["y"], test["p"], adversary_pred, blocks)))
    return Result(
        experiment="E-scheduled-curtailment", family="F12/F2",
        estimand="curtailed fraction, D+1", loss="MAE", unit="fraction",
        adversary=adversary, n=len(test), method="recomputed",
        provenance=[str(path)], rows=rows,
        note="aggregated over the SIN; the result conditioned on recent "
             "curtailment is not in the artifact and is not in this table")


def _marginal_emissions() -> Result:
    path = interim_dir() / "f14_teste.parquet"
    test = pd.read_parquet(path)
    blocks = _day_blocks(test["h"])
    adversary = "24 h persistence"
    rows = [
        ResultRow(adversary, "adversary", mae(test["y"], test["persist"])),
        ResultRow("hour × month climatology", "baseline",
                  mae(test["y"], test["clim"])),
        ResultRow("LightGBM + system state", "model",
                  mae(test["y"], test["modelo"]),
                  skill(test["y"], test["modelo"], test["persist"]),
                  skill_ci(test["y"], test["modelo"], test["persist"], blocks)),
    ]
    return Result(
        experiment="E-marginal-emissions", family="F14",
        estimand="marginal emission factor, 24 h", loss="MAE",
        unit="tCO2/MWh", adversary=adversary, n=len(test),
        method="recomputed", provenance=[str(path)], rows=rows,
        note="CI recomputed by day block, 2,000 repetitions")


def _load_risk() -> Result:
    """F9 from the fold CSV, and what the CSV does NOT allow recomputing.

    The published F9 number (AP 0.0143 for the model against 0.0190 for the
    table) comes from the STACKED aggregate: the out-of-fold predictions
    concatenated before computing AP. That stacked panel is not written, only
    the per-fold summary is, so the published number has no machine-readable
    source on disk. For that reason this adapter does NOT derive skill: AP is
    not linear, and the mean across folds is a different estimator, not an
    approximation of the same one.

    What it adds is the per-fold count, which the artifact supports.
    """
    path = PROCESSED_DIR / "risco_interrupcao_dobras.csv"
    folds = pd.read_csv(path)
    events = folds["ev_te"].to_numpy(float)

    def event_weighted_mean(column: str) -> float:
        return float(np.average(folds[column].to_numpy(float), weights=events))

    def label(column: str) -> str:
        return _RISK_BASELINE_LABEL.get(column, column)

    baselines = [column for column in folds.columns
                 if column.startswith("ap_") and column != "ap_ml"]
    folds_won = {label(column): int((folds["ap_ml"] > folds[column]).sum())
                 for column in baselines}
    best_baseline = max(baselines, key=event_weighted_mean)

    rows = [ResultRow("prevalence", "baseline", event_weighted_mean("base"))]
    rows += [ResultRow(label(column),
                       "adversary" if column == best_baseline else "baseline",
                       event_weighted_mean(column))
             for column in baselines]
    rows.append(ResultRow("LightGBM + system state", "model",
                          event_weighted_mean("ap_ml")))
    fold_count = ", ".join(f"{won} of {len(folds)} ({name})"
                           for name, won in folds_won.items())
    return Result(
        experiment="E-load-risk", family="F9",
        estimand="load interruption, next hour", loss="AP", unit="—",
        adversary="subsystem × hour table", n=int(folds["n_te"].sum()),
        method="partial", provenance=[str(path)], rows=rows,
        note=f"mean AP over {len(folds)} folds, weighted by event. The "
             "published number comes from the STACKED out-of-fold panel, "
             "which is not written: it cannot be recomputed from here, and "
             "so no skill is derived. Per fold, the model beats each "
             f"baseline in {fold_count}; the published stacked aggregate "
             "says the opposite, which is a divergence between estimators "
             "and not an error in either.")


ADAPTERS: dict[str, Callable[[], Result]] = {
    "E-cmo-price": _cmo_price,
    "E-nowcasting-poa": _poa_nowcasting,
    "E-nowcasting-poa · neighbourhood": _poa_neighbourhood,
    "E-when-which": _curtailment_models,
    "E-scheduled-curtailment": _scheduled_curtailment,
    "E-marginal-emissions": _marginal_emissions,
    "E-load-risk": _load_risk,
}


def collect() -> tuple[list[Result], dict[str, str]]:
    """Run the adapters. Return the results and the reason for each absence."""
    results, missing = [], {}
    for name, adapter in ADAPTERS.items():
        try:
            results.append(adapter())
        except OSError as error:        # includes FileNotFoundError
            missing[name] = f"missing artifact: {error}"
        # Any other failure of one adapter is reported, not raised: the
        # remaining experiments must still be collected.
        except Exception as error:      # noqa: BLE001
            missing[name] = f"{type(error).__name__}: {error}"
    return results, missing


def to_table(results: list[Result]) -> pd.DataFrame:
    """One line per predictor of each result."""
    records = []
    for result in results:
        for row in result.rows:
            low, high = row.ci95 if row.ci95 else (None, None)
            records.append(dict(
                experiment=result.experiment, family=result.family,
                estimand=result.estimand, loss=result.loss, unit=result.unit,
                predictor=row.predictor, role=row.role, value=row.value,
                skill=row.skill, ci_low=low, ci_high=high,
                verdict=row.verdict, method=result.method, n=result.n))
    return pd.DataFrame(records)


def write(results: list[Result], missing: dict[str, str]) -> tuple[Path, Path]:
    """Write `registry.json` and `table.csv`; return the two paths."""
    directory = interim_dir() / "registry"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "registry.json"
    json_path.write_text(json.dumps(dict(
        generated_at=pd.Timestamp.now().isoformat(timespec="seconds"),
        results=[result.to_dict() for result in results],
        missing=missing), indent=2, ensure_ascii=False))
    csv_path = directory / "table.csv"
    to_table(results).to_csv(csv_path, index=False)
    return json_path, csv_path
