"""Shared definitions for the thermal-dispatch workflow.

This module contains only paths, schema names, and the accounting decomposition.
It is intentionally kept separate so all three steps refer to the same definitions.

Run from the repository root.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BRUTO = RAIZ / "data" / "raw" / "termica_despacho"
INTERIM = Path(os.environ.get("LUCERTAE_INTERIM", RAIZ / "data" / "interim"))
SAIDA = INTERIM / "E-despacho-termico"

PAINEL = SAIDA / "painel_usina_hora.parquet"
CONTROLES = SAIDA / "controles.json"
RESULTADO = SAIDA / "resultado.json"

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

MOTIVOS_FORA = [
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
MERITO_PARTES = ["ordemdemeritoacimadainflex", "inflexembutmerito"]

# Required columns in every raw file. The schema changed three times during the period,
# and these are the columns that survive across the three signatures.
CHAVES = ["din_instante", "nom_tipopatamar", "id_subsistema", "nom_usina",
          "cod_usinaplanejamento", "ceg"]


def colunas_valor():
    """Return prog_* and verif_* names for all terms in the decomposition."""
    partes = MERITO_PARTES + MOTIVOS_FORA
    return (["val_prog" + c for c in partes] + ["val_proggeracao"],
            ["val_verif" + c for c in partes] + ["val_verifgeracao"])


def arquivos():
    fs = sorted(BRUTO.glob("GERACAO_TERMICA_DESPACHO-2_*.csv"))
    if not fs:
        raise SystemExit(f"no input files found in {BRUTO}")
    return fs
