"""Shared paths, schema conventions, information gate, and source readers.

Run this experiment from the repository root.

INFORMATION GATE
----------------
The experiment forecasts all 48 half-hours of day D at 12:00 on D-1. Source
availability at that issue time was measured from the difference between the
last record on disk and the file modification time. This is one observation per
source, a stated limitation rather than a general publication rule:

    Half-hourly CMO   downloaded 2026-08-27 10:08; last record 2026-08-27
                      23:30. The full day was already in the file: CMO is
                      published in advance, not ex post.
    Load curve        downloaded 2026-09-02 04:25; last record 2026-08-31 23:00
                      (about 1.2 days of lag).
    Interchange       downloaded 2026-09-02 04:44; last record 2026-08-31 23:00
                      (about 1.2 days of lag).
    Daily EAR         downloaded 2026-09-02 04:25; last record 2026-08-31
                      (about 2.2 days of lag).
    Daily ENA         downloaded 2026-09-06 11:22; last record 2026-09-04
                      (about 2.3 days of lag).

The resulting gate applies equally to models and baselines:

    CMO ................ through the end of D-1
    load, interchange .. through the end of D-2
    EAR, ENA ............ through D-3
    D's calendar ........ deterministic and available

Advance CMO publication does not make the task tautological: at 12:00 on D-1,
the operator's value for day D has not yet been published.

SOURCE READERS
--------------
ONS readers are in `lucertae.sources.series`; publication lags are in
`lucertae.gate`. The reader code was moved there from this experiment to avoid
duplicating it in `experiments/E-osciloscopio/_comum.py`.

DATA PROPERTIES THAT CONSTRAIN THE ANALYSIS
-------------------------------------------
1. Eight full CMO days are missing from the window (48 half-hours x 4
   subsystems). They remain missing and are counted, never interpolated;
   interpolation would invent targets that the operator did not publish. Each
   gap removes three panel days: the missing day, the next day without D-1, and
   the day seven days later without D-7.
2. CMO is bounded by regulatory floors and ceilings and reaches both. Between
   17% and 28% of half-hours are at or below 1 R$/MWh; the observed maximum is
   4,870.95. The distribution has mass at the floor and a heavy right tail.
3. Load and interchange are hourly; CMO is half-hourly. Join on the full hour,
   assigning the same hourly value to both half-hours.
"""
import numpy as np

from lucertae.paths import output_dir

OUTPUT_DIR = output_dir("E-cmo-price")

PANEL_PATH = OUTPUT_DIR / "painel.parquet"
CONTROLS_PATH = OUTPUT_DIR / "controles.json"
PREDICTIONS_PATH = OUTPUT_DIR / "previsoes.parquet"
RESULT_PATH = OUTPUT_DIR / "resultado.json"
DECOMPOSITION_PATH = OUTPUT_DIR / "decomposicao.json"

# Gate offsets are measured in days back from target day D; larger values refer
# to older information. The measurements are in `lucertae.gate` and can be
# reproduced with `lucertae gate` on the source files on disk.
from lucertae.gate import GATE_DAYS

CMO_LAG_DAYS = GATE_DAYS["cmo"]
LOAD_LAG_DAYS = GATE_DAYS["load"]
HYDRO_LAG_DAYS = GATE_DAYS["ear"]

# Physical CMO range in R$/MWh. These limits leave margin around the PLD
# regulatory floor and ceiling; the observed window ranges from -39.24 to
# 4,870.95.
CMO_MIN_VALUE = -100.0
CMO_MAX_VALUE = 6000.0

# Threshold used to calculate the fraction of half-hours at the marginal-cost floor.
CMO_FLOOR_THRESHOLD = 1.0


def seasonal_naive(cmo_lag_1, cmo_lag_7, day_of_week):
    """Canonical seasonal-naive baseline from the price-forecasting literature.

    Tuesday through Friday repeat D-1; Saturday through Monday repeat D-7,
    because their immediately preceding day has a different day-type profile.
    `day_of_week` follows pandas numbering, where 0 is Monday.
    """
    return np.where(np.isin(day_of_week, [1, 2, 3, 4]), cmo_lag_1, cmo_lag_7)
