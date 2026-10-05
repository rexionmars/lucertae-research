"""Step 1 -- build the plant-hour panel from the raw data.

This step does not aggregate, filter by data quality, or apply any correction.
The validation step decides whether a row is valid; this stage only reads, stacks,
 and stamps provenance. The separation exists so that the control layer can reject
 the entire panel without silently applying a correction earlier than intended.

Output: data/interim/E-despacho-termico/painel_usina_hora.parquet
"""
import sys
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _comum import (KEY_COLUMNS, MERIT_COMPONENTS, OUT_OF_MERIT_REASONS,
                    OUTPUT_DIR, PANEL_PATH, RAW_DIR, input_files)


def read_file(file_path):
    frame = pd.read_csv(file_path, sep=";", low_memory=False)
    frame["arquivo"] = file_path.name
    # `din_publicacao` only exists from Apr/2026 onward. Where it is missing, the timestamp
    # indicating when a row became knowable is absent and the column stays empty rather than
    # receiving an invented substitute.
    if "din_publicacao" not in frame.columns:
        frame["din_publicacao"] = pd.NaT
    return frame


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = input_files()
    print(f"Reading {len(files)} files from {RAW_DIR}")

    components = MERIT_COMPONENTS + OUT_OF_MERIT_REASONS
    required_columns = (
        KEY_COLUMNS + ["din_publicacao", "arquivo"]
        + ["val_prog" + column for column in components]
        + ["val_proggeracao", "val_progordemmerito"]
        + ["val_verif" + column for column in components]
        + ["val_verifgeracao", "val_verifordemmerito"]
    )

    blocks = []
    for file_path in files:
        frame = read_file(file_path)
        missing = [col for col in required_columns if col not in frame.columns]
        if missing:
            raise SystemExit(f"{file_path.name}: missing required columns {missing}")
        blocks.append(frame[required_columns])
        print(f"  {file_path.name}  {len(frame):>7,} rows")

    panel = pd.concat(blocks, ignore_index=True)
    panel["din_instante"] = pd.to_datetime(panel.din_instante)
    panel["din_publicacao"] = pd.to_datetime(panel.din_publicacao, errors="coerce")

    # Derived sums. These are written here and checked in step 2 against the published total-
    # generation column. This is the only way to make a decomposition error appear as a number
    # rather than vanish during aggregation.
    for side in ("prog", "verif"):
        panel[f"{side}_merito"] = sum(
            panel[f"val_{side}{column}"] for column in MERIT_COMPONENTS
        )
        panel[f"{side}_fora"] = sum(
            panel[f"val_{side}{column}"] for column in OUT_OF_MERIT_REASONS
        )
        panel[f"{side}_total_pub"] = panel[f"val_{side}geracao"]
        panel[f"{side}_total_soma"] = panel[f"{side}_merito"] + panel[f"{side}_fora"]

    panel = panel.sort_values(["din_instante", "nom_usina"]).reset_index(drop=True)
    panel.to_parquet(PANEL_PATH, index=False)

    print(f"\npanel: {len(panel):,} rows, {panel.nom_usina.nunique()} plants, "
          f"{panel.din_instante.nunique():,} instants")
    print(f"period: {panel.din_instante.min()} .. {panel.din_instante.max()}")
    print(f"Saved: {PANEL_PATH}")


if __name__ == "__main__":
    main()
