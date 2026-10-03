"""Measured publication lag of the ONS sources, and the gate derived from it.

The gate is data, not a comment, so that any experiment can read it and a
control can check it.

HOW THE LAG IS MEASURED, and what that limits
---------------------------------------------
One observation per source: the difference between the LAST RECORD in the file
on disk and the file's MODIFICATION TIME. ONS files carry no publication
stamp; the modification time is the only evidence available, and it measures
when the file was downloaded, not when it was published. It is therefore an
UPPER bound on the lag, never the exact lag.

CMO has a NEGATIVE lag: the file downloaded at 10:08 on 2026-08-27 already held
the 48 half-hours of that same day. CMO is an output of the dispatch model, not
an ex-post measurement, and that separates the price family from the others.

`measure_lag` repeats the measurement on the files on disk NOW, so the table
can be checked instead of trusted.
"""
from dataclasses import dataclass

import pandas as pd

from .paths import RAW_DIR

SECONDS_PER_DAY = 86400

# One full day of slack over the measured lag, rounded up. The consumer needs
# the most recent COMPLETE day, not the instant: a feature such as "mean of
# day D-k" requires day D-k to have closed.
GATE_DAYS = {"cmo": 1, "load": 2, "interchange": 2, "ear": 3, "ena": 3}

# Reference measurement, taken on 2026-09-06 and 2026-09-07. `measure_lag`
# recomputes it.
REFERENCE_MEASUREMENT = {
    "cmo":         dict(downloaded="2026-08-27 10:08", last_record="2026-08-27 23:30"),
    "load":        dict(downloaded="2026-09-02 04:25", last_record="2026-08-31 23:00"),
    "interchange": dict(downloaded="2026-09-02 04:44", last_record="2026-08-31 23:00"),
    "ear":         dict(downloaded="2026-09-02 04:25", last_record="2026-08-31 00:00"),
    "ena":         dict(downloaded="2026-09-06 11:22", last_record="2026-09-04 00:00"),
}

# File measured for each source, relative to `RAW_DIR`, and its time column.
_SOURCE_FILE = {
    "cmo": "cmo/cmo_2026.csv",
    "load": "curva_carga/CURVA_CARGA_2026.csv",
    "interchange": "intercambio/INTERCAMBIO_NACIONAL_2026.csv",
    "ear": "ear_subsistema/EAR_DIARIO_SUBSISTEMA_2026.csv",
    "ena": "ena_subsistema/ENA_DIARIO_SUBSISTEMA_2026.csv",
}
_TIME_COLUMN = {
    "cmo": "din_instante",
    "load": "din_instante",
    "interchange": "din_instante",
    "ear": "ear_data",
    "ena": "ena_data",
}


@dataclass
class PublicationLag:
    source: str
    downloaded: pd.Timestamp
    last_record: pd.Timestamp
    days: float


def measure_lag(source: str) -> PublicationLag:
    """Repeat the measurement on the file on disk: one observation.

    Raises `FileNotFoundError` when the source file is not on disk.
    """
    path = RAW_DIR / _SOURCE_FILE[source]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is not on disk: the lag cannot be measured")
    downloaded = pd.Timestamp.fromtimestamp(path.stat().st_mtime)
    timestamps = pd.read_csv(path, sep=";")[_TIME_COLUMN[source]]
    last_record = pd.to_datetime(timestamps).max()
    days = (downloaded - last_record).total_seconds() / SECONDS_PER_DAY
    return PublicationLag(source, downloaded, last_record, days)


def lag_table() -> pd.DataFrame:
    """Measured lag and declared gate, one row per source.

    A source whose file is missing keeps its row, with the reason in `error`.
    """
    rows = []
    for source in _SOURCE_FILE:
        row = dict(source=source, downloaded=None, last_record=None,
                   lag_days=None, gate_days=GATE_DAYS[source])
        try:
            lag = measure_lag(source)
        except FileNotFoundError as error:
            row["error"] = str(error)
        else:
            row.update(downloaded=lag.downloaded, last_record=lag.last_record,
                       lag_days=round(lag.days, 2))
        rows.append(row)
    return pd.DataFrame(rows)


def check_gate(margin_days: float = 0.5) -> list[str]:
    """Gate failures: sources whose measured lag exceeds the declared gate.

    A falsifiable control, independent of any result: if ONS delays
    publication, the gate in `GATE_DAYS` starts to allow a feature that would
    not be available, and this function reports it.

    It does not test sources whose file is missing from disk: they are
    skipped, and `lag_table` shows them.
    """
    failures = []
    for source in _SOURCE_FILE:
        try:
            lag = measure_lag(source)
        except FileNotFoundError:
            continue
        if lag.days > GATE_DAYS[source] + margin_days:
            failures.append(f"{source}: measured lag {lag.days:.2f} d > gate "
                            f"{GATE_DAYS[source]} d")
    return failures
