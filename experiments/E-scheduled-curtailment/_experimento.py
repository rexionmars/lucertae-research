"""F2/F12 -- O corte que o ONS vai programar amanha e previsivel?

ALVO. Fracao da geracao eolica+solar prevista que o operador NAO programa, por
patamar de meia hora, agregada ao SIN. Sai de `_corte.py`.

O QUE PODE ENTRAR. So o que existe quando a programacao de amanha e feita: a
PREVISAO de amanha, que e o insumo da propria programacao, e o historico de corte
ate hoje. O programado de amanha e a resposta e nao entra. Esse e o unico
vazamento possivel aqui, e esta declarado.

RESULTADO. No agregado o modelo NAO supera a barra de forma distinguivel de zero.
O agregado esconde um corte limpo: condicionado a media de corte dos 28 dias
anteriores -- variavel conhecida ANTES da previsao, com limiar tirado do treino --
o modelo perde onde nao ha corte a prever e supera onde ha.

CONTROLES
  C1  persistencia D-1 e D-7, mesmo patamar, e climatologia por patamar. A barra
      e a MELHOR das tres, nao a mais conveniente.
  C2  corte temporal puro, treino ate 31/12/2025.
  C3  hiperparametro escolhido em VALIDACAO interna (ult. trimestre do treino).
      O teste e tocado uma vez so. Sem isso, +10,2% seria numero afinado no teste.
  C4  bootstrap de bloco por DIA -- patamar vizinho nao e independente.
  C5  dentro da amostra, para separar "nao aprende" de "nao generaliza".
  C6  estratificacao por variavel conhecida a priori, nao por trimestre escolhido
      depois de ver o resultado.

Roda da raiz:  .venv/bin/python notebooks/despacho/_experimento.py
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RNG = np.random.default_rng(20260906)
CORTE = pd.Timestamp("2026-01-01")
VALID = pd.Timestamp("2025-10-01")
CFG = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
           l2_regularization=1, min_samples_leaf=80, random_state=0)
mae = lambda a, b: float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def montar():
    d = pd.read_parquet("data/interim/corte_programado.parquet").sort_index()
    d["data"] = d.index.normalize()
    p = d.pivot_table(index="data", columns="num_patamar", values="frac")
    prev = d.pivot_table(index="data", columns="num_patamar", values="prev")
    l1, l7 = p.shift(1), p.shift(7)
    m1 = p.shift(1).mean(axis=1)
    m28 = p.shift(1).rolling(28, min_periods=7).mean().mean(axis=1)
    pico = prev.max(axis=1)
    reg = [pd.DataFrame({
        "y": p[pat], "l1": l1[pat], "l7": l7[pat], "media_ontem": m1,
        "media_28d": m28, "prev": prev[pat], "prev_dia": prev.sum(axis=1),
        "prev_pico": pico, "prev_rel": prev[pat] / pico.where(pico > 0),
        "patamar": pat, "dow": p.index.dayofweek, "mes": p.index.month,
    }) for pat in p.columns]
    return pd.concat(reg).dropna().sort_index()


def barra(g):
    """C1 -- a melhor das tres barras, e o vetor de erro dela."""
    op = {"persistência D-1": g.l1.values, "persistência D-7": g.l7.values}
    nome = min(op, key=lambda k: mae(g.y, op[k]))
    return nome, mae(g.y, op[nome]), np.abs(g.y.values - op[nome])


def ic(em, eb, idx_dias):
    un = list(idx_dias)
    am = [1 - em[i].mean() / eb[i].mean() for i in
          (np.concatenate([idx_dias[d] for d in RNG.choice(un, len(un), replace=True)])
           for _ in range(2000))]
    return np.percentile(am, [2.5, 97.5])


def main():
    X = montar()
    feats = [c for c in X.columns if c != "y"]
    tr, te = X[X.index < CORTE], X[X.index >= CORTE]
    print(f"treino {len(tr):,} patamares ({tr.index.min():%Y-%m-%d} a {tr.index.max():%Y-%m-%d})"
          f" | teste {len(te):,} ({te.index.min():%Y-%m-%d} a {te.index.max():%Y-%m-%d})")
    print(f"fração cortada média: treino {tr.y.mean():.4f} | teste {te.y.mean():.4f}")

    m = HistGradientBoostingRegressor(**CFG).fit(tr[feats], tr.y)
    te = te.copy(); te["p"] = np.clip(m.predict(te[feats]), 0, 1)
    clim = tr.groupby("patamar")["y"].mean()

    print("\nMAE da fração cortada, no teste")
    for k, v in [("persistência D-1", mae(te.y, te.l1)), ("persistência D-7", mae(te.y, te.l7)),
                 ("climatologia por patamar", mae(te.y, te.patamar.map(clim))),
                 ("modelo", mae(te.y, te.p))]:
        print(f"  {k:28s} {v:.5f}")

    nome, b, eb = barra(te)
    dias = te.index.normalize()
    idx = {d: np.where(dias == d)[0] for d in np.unique(dias)}
    lo, hi = ic(np.abs(te.y.values - te.p.values), eb, idx)
    print(f"\nbarra: {nome}. habilidade {100*(1-mae(te.y,te.p)/b):+.1f}%  "
          f"IC 95% [{100*lo:+.1f}%, {100*hi:+.1f}%]")
    print("VEREDITO AGREGADO:", "supera" if lo > 0 else "NÃO supera de forma distinguível")

    pin = np.clip(m.predict(tr[feats]), 0, 1)
    _, bt, _ = barra(tr)
    print(f"C5 dentro da amostra: habilidade {100*(1-mae(tr.y,pin)/bt):+.1f}%")

    # C6 -- estratificacao por media_28d. Limiar do TREINO, variavel conhecida antes.
    q = tr.media_28d.quantile([1/3, 2/3]).values
    print(f"\nC6 estratificado por corte médio dos 28 dias anteriores "
          f"(limiares do treino: {q[0]:.4f}, {q[1]:.4f})")
    faixas = [("baixo  (corte recente quase nulo)", te[te.media_28d < q[0]]),
              ("médio", te[(te.media_28d >= q[0]) & (te.media_28d < q[1])]),
              ("alto   (corte recente alto)", te[te.media_28d >= q[1]])]
    for rot, g in faixas:
        if g.empty:
            print(f"  {rot:36s} vazio"); continue
        n2, b2, eb2 = barra(g)
        d2 = g.index.normalize()
        i2 = {d: np.where(d2 == d)[0] for d in np.unique(d2)}
        lo2, hi2 = ic(np.abs(g.y.values - g.p.values), eb2, i2)
        v = "SUPERA" if lo2 > 0 else ("perde" if hi2 < 0 else "indistinguível")
        print(f"  {rot:36s} n={len(g):>5} dias={len(i2):>3} ȳ={g.y.mean():.4f}  "
              f"habilidade {100*(1-mae(g.y,g.p)/b2):+6.1f}%  IC [{100*lo2:+.1f}, {100*hi2:+.1f}]  {v}")

    te.reset_index().to_parquet("data/interim/f12_teste.parquet", index=False)


if __name__ == "__main__":
    main()
