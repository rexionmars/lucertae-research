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
from _comum import BRUTO, SAIDA, PAINEL, CHAVES, MOTIVOS_FORA, MERITO_PARTES, arquivos


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
    SAIDA.mkdir(parents=True, exist_ok=True)
    files = arquivos()
    print(f"reading {len(files)} files from {BRUTO}")

    partes = MERITO_PARTES + MOTIVOS_FORA
    required_columns = (
        CHAVES + ["din_publicacao", "arquivo"]
        + ["val_prog" + c for c in partes] + ["val_proggeracao", "val_progordemmerito"]
        + ["val_verif" + c for c in partes] + ["val_verifgeracao", "val_verifordemmerito"]
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
        panel[f"{side}_merito"] = sum(panel[f"val_{side}{c}"] for c in MERITO_PARTES)
        panel[f"{side}_fora"] = sum(panel[f"val_{side}{c}"] for c in MOTIVOS_FORA)
        panel[f"{side}_total_pub"] = panel[f"val_{side}geracao"]
        panel[f"{side}_total_soma"] = panel[f"{side}_merito"] + panel[f"{side}_fora"]

    panel = panel.sort_values(["din_instante", "nom_usina"]).reset_index(drop=True)
    panel.to_parquet(PAINEL, index=False)

    print(f"\npanel: {len(panel):,} rows, {panel.nom_usina.nunique()} plants, "
          f"{panel.din_instante.nunique():,} instants")
    print(f"period: {panel.din_instante.min()} .. {panel.din_instante.max()}")
    print(f"saved: {PAINEL}")


if __name__ == "__main__":
    main()
