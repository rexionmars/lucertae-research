"""Loss, skill and block-bootstrap confidence interval.

SIGN CONVENTION. Skill is `1 - model_loss / adversary_loss`, positive when the
model errs less. Negative skill is a result, not a failure.

THE METRIC THAT SELECTS IS THE METRIC THAT REPORTS (guide rule 12). `loss` is
an explicit argument of every function here: the caller states MAE or RMSE.

COST. The bootstrap index of each block is grouped once, before resampling.
Building it with `np.where(days == d)` inside the resampling loop costs
O(resamples x days x n) and does not finish on a large panel.
"""
from collections.abc import Callable, Iterable, Iterator

import numpy as np
import pandas as pd

DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 1

LossFunction = Callable[..., float]


def mae(y_true, y_pred) -> float:
    """Mean absolute error."""
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return float(np.abs(y_true - y_pred).mean())


def rmse(y_true, y_pred) -> float:
    """Root mean squared error."""
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return float(np.sqrt(((y_true - y_pred) ** 2).mean()))


def skill(y_true, model, adversary, loss: LossFunction = mae) -> float:
    """1 - loss(model) / loss(adversary), as a fraction."""
    adversary_loss = loss(y_true, adversary)
    if adversary_loss == 0:
        raise ValueError("adversary has zero loss: skill is undefined")
    return 1.0 - loss(y_true, model) / adversary_loss


def _block_aggregates(y_true, y_pred, blocks,
                      squared: bool) -> tuple[np.ndarray, np.ndarray]:
    """Error sum and row count per block, in sorted block order.

    With these two arrays the bootstrap computes each resampled loss as a
    ratio of sums, without touching the rows again.
    """
    error = np.asarray(y_true, float) - np.asarray(y_pred, float)
    error = error ** 2 if squared else np.abs(error)
    frame = pd.DataFrame({"block": np.asarray(blocks), "error": error})
    grouped = frame.groupby("block", sort=True)["error"]
    return grouped.sum().to_numpy(), grouped.size().to_numpy()


def skill_ci(y_true, model, adversary, blocks: Iterable,
             loss: LossFunction = mae, n_resamples: int = DEFAULT_RESAMPLES,
             seed: int = DEFAULT_SEED) -> tuple[float, float]:
    """95% CI of the skill, resampling BLOCKS, not rows.

    The block is the unit of dependence, typically the day. Resampling rows
    would treat half-hours of the same day as independent and return an
    interval that is too narrow.

    Valid for MAE and RMSE because both are ratios of aggregates: the sum of
    |e| or of e^2 per block, divided by the row count. It does not hold for a
    metric that cannot be written this way; AP and AUC, for example, need
    another method, and any other `loss` raises `ValueError`.
    """
    if loss is not mae and loss is not rmse:
        raise ValueError("skill_ci supports only mae and rmse as loss")
    squared = loss is rmse
    model_error, rows = _block_aggregates(y_true, model, blocks, squared)
    adversary_error, _ = _block_aggregates(y_true, adversary, blocks, squared)

    rng = np.random.default_rng(seed)
    n_blocks = len(rows)
    draws = rng.integers(0, n_blocks, size=(n_resamples, n_blocks))
    resampled_rows = rows[draws].sum(axis=1)
    model_loss = model_error[draws].sum(axis=1) / resampled_rows
    adversary_loss = adversary_error[draws].sum(axis=1) / resampled_rows
    if squared:
        model_loss, adversary_loss = np.sqrt(model_loss), np.sqrt(adversary_loss)

    resampled_skill = 1.0 - model_loss / adversary_loss
    return (float(np.percentile(resampled_skill, 2.5)),
            float(np.percentile(resampled_skill, 97.5)))


def expanding_folds(days: np.ndarray, n_folds: int = 3,
                    initial_fraction: float = 0.5
                    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Rolling origin with an expanding training window.

    Yields `(train_days, test_days)` for each fold.
    """
    unique_days = np.sort(np.unique(days))
    first_test = int(len(unique_days) * initial_fraction)
    edges = np.linspace(first_test, len(unique_days), n_folds + 1).astype(int)
    for fold in range(n_folds):
        yield (unique_days[:edges[fold]],
               unique_days[edges[fold]:edges[fold + 1]])


def monthly_test_windows(days: np.ndarray, initial_fraction: float = 0.55
                         ) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
    """Monthly recalibration: `(start, end)` of each month in the test window.

    `end` is exclusive: the first day of the following month.
    """
    unique_days = pd.Series(np.sort(np.unique(days)))
    test_start = unique_days.iloc[int(len(unique_days) * initial_fraction)]
    test_days = unique_days[unique_days >= test_start]
    for month in sorted(test_days.dt.to_period("M").unique()):
        start = month.to_timestamp()
        yield start, start + pd.offsets.MonthBegin(1)
