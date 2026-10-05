"""Alvo da familia 14: fator de emissao da Margem de Operacao, horario, MCTI/SIRENE.

Metodo da Analise de Despacho (Tool 07 da UNFCCC). A planilha traz a Margem de
Operacao em tres blocos -- mensal, diario e horario -- e o horario vem em grade
Dia x Hora x Mes, nao em coluna de tempo.

ARMADILHA. A grade e retangular: 31 dias em todo mes. O dia que nao existe
(30 de fevereiro, 31 de abril) vem preenchido com ZERO, nao vazio. Ler sem
filtrar por calendario injeta ~120 zeros por ano no alvo.

Roda da raiz:  .venv/bin/python notebooks/emissao/_mo.py
"""
import re, zipfile, calendar
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen
import pandas as pd

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
BASE = "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/sirene/dados-e-ferramentas/fatores-de-emissao/arquivo/"
FONTES = {
    2024: BASE + "Despacho_2024_jandezcomcorrees_FE_MC.xlsx",
    2025: BASE + "Despacho_2025_jandez_corrigidacomMO.xlsx",
    2026: BASE + "Despacho_2026_janjul.xlsx",
}
BRUTO = Path("data/raw/mcti_mo")
COL_MES = ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"]


def _baixa(ano, url):
    dst = BRUTO / f"despacho_{ano}.xlsx"
    if not dst.exists():
        BRUTO.mkdir(parents=True, exist_ok=True)
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as r:
            dst.write_bytes(r.read())
    return dst


def _celulas(path):
    """Planilha -> lista de dicionarios {coluna: valor}, uma entrada por linha."""
    z = zipfile.ZipFile(path)
    comp = []
    if "xl/sharedStrings.xml" in z.namelist():
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        comp = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in raiz.findall(NS + "si")]
    folha = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    linhas = []
    for row in folha.iter(NS + "row"):
        cur = {}
        for c in row.findall(NS + "c"):
            ref = re.match(r"([A-Z]+)", c.get("r")).group(1)
            v = c.find(NS + "v")
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = comp[int(val)]
            cur[ref] = val
        linhas.append(cur)
    return linhas


def _bloco_horario(linhas):
    """Indice da primeira linha de dado do bloco HORARIO."""
    for i, r in enumerate(linhas):
        rot = r.get("F")
        if isinstance(rot, str) and "HOR" in rot.upper() and "FATOR" in rot.upper():
            # rotulo, linha do ano, cabecalho Dia/Hora/meses, entao os dados
            for j in range(i + 1, i + 6):
                if str(linhas[j].get("A", "")).strip() == "Dia":
                    return j + 1
    raise AssertionError("bloco horario nao encontrado na planilha")


def le_ano(ano, url):
    linhas = _celulas(_baixa(ano, url))
    ini = _bloco_horario(linhas)
    reg, dia = [], None
    for r in linhas[ini:]:
        if r.get("A") not in (None, ""):
            dia = int(float(r["A"]))
        if r.get("B") in (None, "") or dia is None:
            continue
        hora = int(float(r["B"]))
        if not 1 <= hora <= 24:
            continue
        for m, col in enumerate(COL_MES, start=1):
            v = r.get(col)
            if v in (None, ""):
                continue
            # A grade e retangular: descarta o dia que o calendario nao tem.
            if dia > calendar.monthrange(ano, m)[1]:
                continue
            reg.append((pd.Timestamp(ano, m, dia) + pd.Timedelta(hours=hora - 1), float(v)))
        if dia == 31 and hora == 24:
            break
    s = pd.Series(dict(reg)).sort_index()
    s.index.name = "h"
    s.name = "mo"
    return s


def main():
    s = pd.concat([le_ano(a, u) for a, u in FONTES.items()]).sort_index()

    # --- controles
    assert s.index.is_unique, "hora repetida no alvo"
    assert (s > 0).all(), f"{int((s <= 0).sum())} valores nao positivos sobreviveram ao filtro de calendario"
    assert s.max() < 2.0, f"fator acima de 2 tCO2/MWh: {s.max():.3f}"
    por_dia = s.groupby(s.index.normalize()).size()
    assert (por_dia == 24).all(), f"dias sem 24 horas: {int((por_dia != 24).sum())}"
    esp = pd.date_range(s.index.min(), s.index.max(), freq="h")
    falta = esp.difference(s.index)
    print(f"alvo: {len(s):,} horas, {s.index.min()} -> {s.index.max()}")
    print(f"  horas ausentes no intervalo: {len(falta):,}")
    print(f"  media {s.mean():.4f}  mediana {s.median():.4f}  min {s.min():.4f}  max {s.max():.4f} tCO2/MWh")
    Path("data/interim").mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet("data/interim/mo_horario.parquet")
    print("-> data/interim/mo_horario.parquet")


if __name__ == "__main__":
    main()
