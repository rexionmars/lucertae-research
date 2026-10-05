"""F14 -- Previsao do fator de emissao marginal a 24 h, contra persistencia.

POR QUE 24 H, E NAO A HORA CORRENTE. O fator de Margem de Operacao e DERIVADO
do despacho pelo metodo do MCTI, e as features do painel sao despacho. Ajustar
MO(h) contra estado(h) reescreve a formula do MCTI e acerta por construcao: seria
tautologia, nao resultado. A pergunta com conteudo e de previsao -- saber hoje o
fator de amanha, que e o que um deslocamento de carga precisa -- usando so
informacao disponivel ate h para prever h+24.

CONTROLES
  C1  persistencia de 24 h e a barra. Nao superar => resultado negativo, e sai
      como negativo.
  C2  climatologia hora x mes, ajustada so no treino.
  C3  corte temporal puro: treino ate 31/12/2025, teste em 2026. Sem embaralhar.
  C4  bootstrap de bloco por DIA, porque hora vizinha nao e independente.
  C5  CONTROLE POSITIVO: MO(h) ~ estado(h). Se o pipeline nao achar nem esse
      sinal, o negativo do C1 e bug de juncao, nao achado.
  C6  corte alternativo em 2025-S2. Um negativo que so aparece num corte e
      regime, nao propriedade das features.

Roda da raiz:  .venv/bin/python notebooks/emissao/_experimento.py
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RNG = np.random.default_rng(20260906)
CORTE = pd.Timestamp("2026-01-01")
H = 24


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def main():
    y = pd.read_parquet("data/interim/mo_horario.parquet")["mo"]
    X = pd.read_parquet("data/interim/painel_sistema_limpo.parquet")

    # alvo em h+24, features em h -> so passado entra
    alvo = y.shift(-H).rename("y")
    d = X.join(alvo, how="inner").join(y.rename("mo_agora"), how="inner").dropna()
    # persistencia: o fator da mesma hora de HOJE prevendo o de amanha
    d["persist"] = d["mo_agora"]

    tr, te = d[d.index < CORTE], d[d.index >= CORTE]
    feats = [c for c in X.columns] + ["mo_agora"]
    print(f"treino {len(tr):,} h ({tr.index.min():%Y-%m-%d} a {tr.index.max():%Y-%m-%d}) | "
          f"teste {len(te):,} h ({te.index.min():%Y-%m-%d} a {te.index.max():%Y-%m-%d})")

    # C2 climatologia hora x mes, ajustada SO no treino
    clim = tr.groupby([tr.index.month, tr.index.hour])["y"].mean()
    te_clim = np.array([clim.get((t.month, t.hour), tr["y"].mean()) for t in te.index])

    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06,
                                      random_state=0).fit(tr[feats], tr["y"])
    pred = m.predict(te[feats])

    r = {"persistência 24 h": mae(te["y"], te["persist"]),
         "climatologia hora×mês": mae(te["y"], te_clim),
         "modelo (estado do sistema + fator corrente)": mae(te["y"], pred)}
    print("\nMAE no teste, tCO2/MWh")
    for k, v in r.items():
        print(f"  {k:38s} {v:.5f}")

    base = r["persistência 24 h"]
    hab = 1 - r["modelo (estado do sistema + fator corrente)"] / base
    print(f"\nhabilidade sobre persistência: {100*hab:+.1f}%")

    # C4 bootstrap de bloco por dia
    dias = te.index.normalize()
    unicos = np.unique(dias)
    err_m = np.abs(te["y"].values - pred)
    err_p = np.abs(te["y"].values - te["persist"].values)
    amostras = []
    for _ in range(2000):
        esc = RNG.choice(unicos, size=len(unicos), replace=True)
        idx = np.concatenate([np.where(dias == dd)[0] for dd in esc])
        amostras.append(1 - err_m[idx].mean() / err_p[idx].mean())
    lo, hi = np.percentile(amostras, [2.5, 97.5])
    print(f"IC 95% por bloco de dia ({len(unicos)} dias): [{100*lo:+.1f}%, {100*hi:+.1f}%]")
    print("VEREDITO:", "supera a persistência" if lo > 0 else
          "NÃO supera a persistência de forma distinguível de zero")

    pd.DataFrame({"h": te.index, "y": te["y"].values, "modelo": pred,
                  "persist": te["persist"].values, "clim": te_clim}
                 ).to_parquet("data/interim/f14_teste.parquet", index=False)




def controles():
    """C5 e C6. Rodam separado porque respondem 'o negativo e real?', nao 'quanto'."""
    y = pd.read_parquet("data/interim/mo_horario.parquet")["mo"]
    X = pd.read_parquet("data/interim/painel_sistema_limpo.parquet")

    # C5 -- controle positivo: fator da hora corrente a partir do estado da hora corrente
    c = X.join(y.rename("y"), how="inner").dropna()
    tr, te = c[c.index < CORTE], c[c.index >= CORTE]
    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06,
                                      random_state=0).fit(tr[X.columns], tr["y"])
    p = m.predict(te[X.columns])
    r2 = 1 - np.var(te["y"] - p) / np.var(te["y"])
    print(f"\nC5 controle positivo  MO(h) ~ estado(h): MAE {mae(te['y'], p):.5f}  R2 {r2:.3f}")
    assert r2 > 0.3, "pipeline nao acha nem o sinal contemporaneo: o negativo seria bug"

    d = X.join(y.shift(-H).rename("y"), how="inner").join(y.rename("mo_agora"), how="inner").dropna()
    feats = list(X.columns) + ["mo_agora"]

    # dentro da amostra: o modelo aprende, mas aprende o periodo
    tr = d[d.index < CORTE]
    pr = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06,
                                       random_state=0).fit(tr[feats], tr["y"]).predict(tr[feats])
    print(f"   dentro da amostra: habilidade {100*(1-mae(tr['y'],pr)/mae(tr['y'],tr['mo_agora'])):+.1f}%")

    # C6 -- corte alternativo
    c2 = pd.Timestamp("2025-07-01")
    tr2 = d[d.index < c2]
    te2 = d[(d.index >= c2) & (d.index < CORTE)]
    pr2 = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06,
                                        random_state=0).fit(tr2[feats], tr2["y"]).predict(te2[feats])
    h2 = 1 - mae(te2["y"], pr2) / mae(te2["y"], te2["mo_agora"])
    print(f"C6 corte alternativo 2025-S2 (n={len(te2):,}): habilidade {100*h2:+.1f}%")


if __name__ == "__main__":
    main()
    controles()
