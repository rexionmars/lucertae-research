"""Alvo da F2/F12: o vao entre o que o ONS PREVE e o que ele PROGRAMA.

`programacao_x_previsao` traz, por usina eolica e solar e por patamar de meia
hora, a previsao de geracao e o valor programado. A diferenca nao e erro de
previsao: e DECISAO DE DESPACHO -- quanto da geracao prevista o operador escolhe
nao programar, um dia antes. E o constrained-off visto do lado da programacao,
e nao do lado da medicao.

Agrega ao SIN por patamar. Nao precisa de crosswalk: previsao e programado estao
no mesmo arquivo, na mesma linha.

Roda da raiz:  .venv/bin/python notebooks/despacho/_corte.py
"""
import glob
from pathlib import Path
import pandas as pd

def main():
    arqs = sorted(glob.glob("data/raw/programacao_previsao/*.parquet"))
    assert len(arqs) > 600, f"so {len(arqs)} arquivos"
    fr = []
    for a in arqs:
        d = pd.read_parquet(a, columns=["dat_programacao", "num_patamar",
                                        "val_previsao", "val_programado"])
        # O parquet do ONS traz os dois valores como TEXTO. Converter em silencio
        # esconderia celula nao numerica, entao a conversao e checada por arquivo.
        for c in ("val_previsao", "val_programado"):
            bruto = d[c]
            d[c] = pd.to_numeric(bruto, errors="coerce")
            perdidas = int(d[c].isna().sum() - bruto.isna().sum())
            assert perdidas == 0, f"{a}: {perdidas} celulas de {c} nao viraram numero"
        fr.append(d.groupby(["dat_programacao", "num_patamar"])
                   .agg(prev=("val_previsao", "sum"),
                        prog=("val_programado", "sum"),
                        n_usinas=("val_previsao", "size")).reset_index())
    d = pd.concat(fr, ignore_index=True)
    d["data"] = pd.to_datetime(d.dat_programacao.astype(str), format="%Y%m%d")
    d["h"] = d.data + pd.to_timedelta((d.num_patamar - 1) * 30, unit="min")
    d = d.sort_values("h").set_index("h")
    d["corte"] = d.prev - d.prog
    d["frac"] = (d.corte / d.prev.where(d.prev > 0)).clip(lower=0)

    # --- controles
    assert d.index.is_unique, "patamar repetido"
    assert (d.num_patamar.between(1, 48)).all(), "patamar fora de 1..48"
    por_dia = d.groupby(d.data).size()
    incompletos = int((por_dia != 48).sum())
    neg = int((d.corte < -1e-6).sum())
    print(f"{len(d):,} patamares, {d.data.nunique():,} dias, "
          f"{d.index.min():%Y-%m-%d} a {d.index.max():%Y-%m-%d}")
    print(f"  dias sem 48 patamares: {incompletos}")
    print(f"  usinas por patamar: mediana {int(d.n_usinas.median())}, "
          f"min {int(d.n_usinas.min())}, max {int(d.n_usinas.max())}")
    print(f"  patamares com programado > previsto: {neg:,} ({100*neg/len(d):.2f}%)")
    print(f"  fracao cortada: media {d.frac.mean():.4f}  mediana {d.frac.median():.4f}  "
          f"p95 {d.frac.quantile(.95):.4f}  max {d.frac.max():.4f}")
    print(f"  energia prevista {d.prev.sum()/2/1e6:.2f} TWh, "
          f"programada {d.prog.sum()/2/1e6:.2f} TWh, "
          f"corte {d.corte.clip(lower=0).sum()/2/1e6:.2f} TWh")
    Path("data/interim").mkdir(parents=True, exist_ok=True)
    d[["num_patamar", "prev", "prog", "corte", "frac", "n_usinas"]].to_parquet(
        "data/interim/corte_programado.parquet")
    print("-> data/interim/corte_programado.parquet")

if __name__ == "__main__":
    main()
