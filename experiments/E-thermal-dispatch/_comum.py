"""Shared definitions for the thermal-dispatch workflow.

This module contains only paths, schema names, and the accounting decomposition.
It is intentionally kept separate so all three steps refer to the same definitions.

Run from the repository root.
"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "termica_despacho"
INTERIM_DIR = Path(os.environ.get("LUCERTAE_INTERIM", ROOT_DIR / "data" / "interim"))
OUTPUT_DIR = INTERIM_DIR / "E-despacho-termico"

PANEL_PATH = OUTPUT_DIR / "painel_usina_hora.parquet"
CONTROLS_PATH = OUTPUT_DIR / "controles.json"
RESULT_PATH = OUTPUT_DIR / "resultado.json"

# --- accounting decomposition -------------------------------------------
# Discovered empirically rather than from a manual. The identity that closes the
# line-by-line balance is:
#
#   generation = merit_order_above_inflex + inflexibility + REST
#
# Since `inflexibility = inflex_embut_merito + inflex_pura` closes 100% of the
# scheduled lines, it can be rewritten in economic form:
#
#   generation = MERIT + OUT_OF_MERIT
#   MERIT = merit_order_above_inflex + inflex_embut_merito
#   OUT_OF_MERIT = inflex_pura + the eight REST reasons
#
# Interpretation of MERIT: generation that the merit-order dispatch would have
# produced regardless, including the inflexible share that happens to land in it.
# Interpretation of OUT_OF_MERIT: generation driven by operational decisions, not by price.
#
# `ordemmerito` is intentionally excluded from the sum because it is redundant with
# `ordemdemeritoacimadainflex + inflexembutmerito`; this redundancy fails in some rows,
# and control C1b tracks that gap instead of hiding it.

OUT_OF_MERIT_REASONS = [
    "inflexpura",
    "razaoeletrica",
    "garantiaenergetica",
    "gfom",
    "reposicaoperdas",
    "exportacao",
    "reservapotencia",
    "gsub",
    "unitcommitment",
]
MERIT_COMPONENTS = ["ordemdemeritoacimadainflex", "inflexembutmerito"]

# Required columns in every raw file. The schema changed three times during the period,
# and these are the columns that survive across the three signatures.
KEY_COLUMNS = ["din_instante", "nom_tipopatamar", "id_subsistema", "nom_usina",
               "cod_usinaplanejamento", "ceg"]


def value_columns():
    """Return prog_* and verif_* names for all terms in the decomposition."""
    components = MERIT_COMPONENTS + OUT_OF_MERIT_REASONS
    return (["val_prog" + column for column in components] + ["val_proggeracao"],
            ["val_verif" + column for column in components] + ["val_verifgeracao"])


def input_files():
    files = sorted(RAW_DIR.glob("GERACAO_TERMICA_DESPACHO-2_*.csv"))
    if not files:
        raise SystemExit(f"no input files found in {RAW_DIR}")
    return files
