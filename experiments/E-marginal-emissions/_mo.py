"""Read the hourly MCTI/SIRENE Operating Margin factor used by task family 14.

The UNFCCC Dispatch Data Analysis Method (Tool 07) spreadsheet provides the
Operating Margin in monthly, daily, and hourly blocks. The hourly block is a
day-by-hour-by-month grid, not a timestamp column.

IMPORTANT: the grid is rectangular and contains 31 days for every month.
Nonexistent dates (such as February 30) are filled with zero, not left empty.
Reading the grid without calendar filtering would add about 120 false zeros per
year to the target.

Run from the repository root: .venv/bin/python
    experiments/E-marginal-emissions/_mo.py
"""
import calendar
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen
import pandas as pd

SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
BASE = "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/"
SOURCES = {
    2024: BASE + "Despacho_2024_jandezcomcorrees_FE_MC.xlsx",
    2025: BASE + "Despacho_2025_jandez_corrigidacomMO.xlsx",
    2026: BASE + "Despacho_2026_janjul.xlsx",
}
RAW_DIR = Path("data/raw/mcti_mo")
MONTH_COLUMNS = ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"]


def _download_file(year, url):
    destination = RAW_DIR / f"despacho_{year}.xlsx"
    if not destination.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as r:
            destination.write_bytes(r.read())
    return destination


def _read_cells(path):
    """Convert a spreadsheet into one dictionary of column values per row."""
    workbook = zipfile.ZipFile(path)
    shared_strings = []
    if "xl/sharedStrings.xml" in workbook.namelist():
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        shared_strings = [
            "".join(text.text or "" for text in item.iter(SPREADSHEET_NS + "t"))
            for item in root.findall(SPREADSHEET_NS + "si")
        ]
    sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter(SPREADSHEET_NS + "row"):
        current_row = {}
        for cell in row.findall(SPREADSHEET_NS + "c"):
            column = re.match(r"([A-Z]+)", cell.get("r")).group(1)
            value_element = cell.find(SPREADSHEET_NS + "v")
            value = value_element.text if value_element is not None else None
            if cell.get("t") == "s" and value is not None:
                value = shared_strings[int(value)]
            current_row[column] = value
        rows.append(current_row)
    return rows


def _hourly_block_start(rows):
    """Find the first data row in the HOURLY block."""
    for index, row in enumerate(rows):
        label = row.get("F")
        if isinstance(label, str) and "HOR" in label.upper() and "FATOR" in label.upper():
            # The block contains a title, year row, day/hour/month header, then data.
            for header_index in range(index + 1, index + 6):
                if str(rows[header_index].get("A", "")).strip() == "Dia":
                    return header_index + 1
    raise AssertionError("hourly block not found in spreadsheet")


def read_year(year, url):
    rows = _read_cells(_download_file(year, url))
    first_data_row = _hourly_block_start(rows)
    records, day = [], None
    for row in rows[first_data_row:]:
        if row.get("A") not in (None, ""):
            day = int(float(row["A"]))
        if row.get("B") in (None, "") or day is None:
            continue
        hour = int(float(row["B"]))
        if not 1 <= hour <= 24:
            continue
        for month, column in enumerate(MONTH_COLUMNS, start=1):
            value = row.get(column)
            if value in (None, ""):
                continue
            # The grid is rectangular: discard dates that do not exist in the calendar.
            if day > calendar.monthrange(year, month)[1]:
                continue
            records.append((pd.Timestamp(year, month, day) + pd.Timedelta(hours=hour - 1), float(value)))
        if day == 31 and hour == 24:
            break
    series = pd.Series(dict(records)).sort_index()
    series.index.name = "h"
    series.name = "mo"
    return series


def main():
    series = pd.concat([read_year(year, url) for year, url in SOURCES.items()]).sort_index()

    # Data integrity controls.
    assert series.index.is_unique, "duplicate target timestamp"
    assert (series > 0).all(), f"{int((series <= 0).sum())} non-positive values survived calendar filtering"
    assert series.max() < 2.0, f"emission factor exceeds 2 tCO2/MWh: {series.max():.3f}"
    observations_per_day = series.groupby(series.index.normalize()).size()
    assert (observations_per_day == 24).all(), f"days without 24 hours: {int((observations_per_day != 24).sum())}"
    expected_index = pd.date_range(series.index.min(), series.index.max(), freq="h")
    missing_hours = expected_index.difference(series.index)
    print(f"target: {len(series):,} hours, {series.index.min()} -> {series.index.max()}")
    print(f"  missing hours in interval: {len(missing_hours):,}")
    print(f"  mean {series.mean():.4f}  median {series.median():.4f}  min {series.min():.4f}  max {series.max():.4f} tCO2/MWh")
    Path("data/interim").mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet("data/interim/mo_horario.parquet")
    print("Saved: data/interim/mo_horario.parquet")


if __name__ == "__main__":
    main()
