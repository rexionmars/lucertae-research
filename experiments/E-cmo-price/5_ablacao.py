"""Passo 5 -- de onde vem a habilidade, e tres controles que exigem reajuste.

Rodar da raiz do repositorio, depois do passo 3:
    .venv/bin/python experiments/E-preco-cmo/5_ablacao.py

Tres coisas, todas com o MESMO esquema de origem movel e recalibracao mensal do
passo 3, para que os numeros se comparem:

ABLACAO      quatro conjuntos de feature, encaixados, do calendario mais o CMO
             proprio ate o painel inteiro. A leitura util e a diferenca entre
             conjuntos vizinhos, e nao a habilidade absoluta de cada um.

NULO         as features embaralhadas entre as linhas do treino, alvo intacto.
             Destroi a associacao sem mexer na distribuicao de nenhuma coluna.
             Se a habilidade do modelo completo nao cair para perto de zero
             aqui, ela nao vinha das features.

HORIZONTE    o mesmo desenho com o alvo em D+1 em vez de D, portao inteiro
             deslocado de um dia. O erro TEM de crescer, para os dois termos.
             Se nao crescesse, a informacao usada nao seria a informacao
             recente, e o resultado do passo 3 seria artefato. A habilidade
             sai com IC porque nao e so controle: o quanto cada termo se
             degrada e resultado.

O QUE ESTE PASSO NAO TESTA
--------------------------
A ablacao remove FAMILIA de feature, nao feature. Ela diz de qual fonte vem o
ganho, nao qual coluna dentro da fonte. E a ordem de encaixe e uma so: um
conjunto pode parecer inutil por chegar depois de outro que ja trazia o mesmo.
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from _comum import LIMIAR_PISO, PAINEL, RESULTADO, SAIDA, naive_sazonal
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load as carga,
    net_interchange as intercambio_liquido)
from _modelos_comum import (ADVERSARIO, B_BOOT, FRACAO_TREINO_INICIAL, PARAMS,
                            SEMENTE)
from _painel import colunas_feature, colunas_modelo, construir

ABLACAO = SAIDA / "ablacao.json"


def familias(feats):
    """Reparte as features por FONTE. Toda feature cai em exatamente uma."""
    f = {
        "calendario": [c for c in feats if c in ("hh", "dow", "mes", "sub")],
        "cmo_cruzado": [c for c in feats if c.startswith(("cmo_N", "cmo_NE",
                        "cmo_S", "cmo_SE", "cmomed_N", "cmomed_NE", "cmomed_S",
                        "cmomed_SE"))],
        "carga": [c for c in feats if c.startswith(("carga", "interc"))],
        "hidro": [c for c in feats if c.startswith(("ear", "ena"))],
    }
    usadas = {c for v in f.values() for c in v}
    f["cmo_proprio"] = [c for c in feats if c not in usadas]
    sobra = set(feats) - {c for v in f.values() for c in v}
    if sobra:
        raise SystemExit(f"feature sem familia: {sorted(sobra)}")
    return f


def conjuntos(feats):
    """Conjuntos encaixados, cada um na ORDEM CANONICA do painel.

    A ordem importa e nao deveria: com `colsample_bytree` menor que 1 o
    LightGBM sorteia coluna por posicao, entao permutar as mesmas colunas e o
    mesmo que trocar a semente. Medido antes desta correcao: o conjunto
    completo, com as colunas na ordem em que a ablacao as concatenava, deu
    +4,40% de habilidade contra +0,76% na ordem canonica do passo 3 -- as
    mesmas 41 features. Sem reordenar, a escada de ablacao mediria variancia de
    ajuste junto com efeito de familia.
    """
    f = familias(feats)
    pos = {c: i for i, c in enumerate(feats)}
    canon = lambda cols: sorted(cols, key=pos.__getitem__)
    a0 = canon(f["calendario"] + f["cmo_proprio"])
    a1 = canon(a0 + f["cmo_cruzado"])
    a2 = canon(a1 + f["carga"])
    a3 = canon(a2 + f["hidro"])
    return {"A0 calendario + CMO proprio": a0,
            "A1 + CMO dos outros subsistemas": a1,
            "A2 + carga e intercambio": a2,
            "A3 + hidrologia (completo)": a3}


def _prever_mes(tr, te, feats, variante, X):
    """Ajusta a variante pedida no treino `tr`/`X` e preve o mes `te`."""
    if variante == "direto":
        m = lgb.LGBMRegressor(**PARAMS).fit(X, tr["y"])
        return m.predict(te[feats])
    if variante == "residual":
        m = lgb.LGBMRegressor(**PARAMS).fit(X, tr["y"] - tr["naive_sazonal"])
        return te["naive_sazonal"].to_numpy() + m.predict(te[feats])
    if variante == "duas_partes":
        piso = tr["y"] <= LIMIAR_PISO
        clf = lgb.LGBMClassifier(**{**PARAMS, "objective": "binary"}).fit(
            X, piso.astype(int))
        reg = lgb.LGBMRegressor(**PARAMS).fit(X[~piso.to_numpy()],
                                              tr.loc[~piso, "y"])
        prob = clf.predict_proba(te[feats])[:, 1]
        return np.where(prob > 0.5, float(tr.loc[piso, "y"].median()),
                        reg.predict(te[feats]))
    raise SystemExit(f"variante desconhecida: {variante}")


def rodar(pan, feats, dias_teste, variante, embaralhar=False, semente=SEMENTE):
    """Origem movel mensal, mesma janela e mesma recalibracao do passo 3."""
    saida = []
    rng = np.random.default_rng(semente)
    for m in sorted(pd.Series(dias_teste).dt.to_period("M").unique()):
        ini, fim = m.to_timestamp(), m.to_timestamp() + pd.offsets.MonthBegin(1)
        tr = pan[pan["dia"] < ini]
        te = pan[(pan["dia"] >= ini) & (pan["dia"] < fim)]
        if te.empty:
            continue
        X = tr[feats]
        if embaralhar:
            X = X.iloc[rng.permutation(len(X))].reset_index(drop=True)
            X.index = tr.index
        pv = _prever_mes(tr, te, feats, variante, X)
        saida.append(pd.DataFrame({"dia": te["dia"].to_numpy(),
                                   "y": te["y"].to_numpy(),
                                   "adv": te["naive_sazonal"].to_numpy(),
                                   "p": pv}))
    return pd.concat(saida, ignore_index=True)


def habilidade(d):
    return 100.0 * (1 - np.abs(d["y"] - d["p"]).mean() /
                    np.abs(d["y"] - d["adv"]).mean())


def ic_habilidade(d, b=B_BOOT, semente=SEMENTE):
    g = d.groupby("dia")
    em = g.apply(lambda x: np.abs(x["y"] - x["p"]).sum(), include_groups=False).to_numpy()
    ea = g.apply(lambda x: np.abs(x["y"] - x["adv"]).sum(), include_groups=False).to_numpy()
    n = g.size().to_numpy()
    rng = np.random.default_rng(semente)
    i = rng.integers(0, len(n), size=(b, len(n)))
    h = 100.0 * (1 - (em[i].sum(1) / n[i].sum(1)) / (ea[i].sum(1) / n[i].sum(1)))
    return [float(np.percentile(h, 2.5)), float(np.percentile(h, 97.5))]


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    res3 = json.loads(RESULTADO.read_text())
    # A variante ablada e a de menor MAE no passo 3, e nao uma escolhida aqui.
    cand = {v: res3["erros"][f"lgbm_{v}"]["mae"]
            for v in ("direto", "residual", "duas_partes")}
    variante = min(cand, key=cand.get)
    print(f"variante ablada: {variante} (MAE no passo 3: "
          + ", ".join(f"{k} {v:.2f}" for k, v in cand.items()) + ")")

    pan = pd.read_parquet(PAINEL)
    pan["sub"] = pan["sub"].astype("category")
    feats = colunas_modelo(pan)
    dias = np.sort(pan["dia"].unique())
    dias_teste = dias[dias >= dias[int(len(dias) * FRACAO_TREINO_INICIAL)]]

    t0 = time.time()
    out = {"variante_ablada": variante, "adversario": ADVERSARIO,
           "familias": {k: len(v) for k, v in familias(feats).items()},
           "ablacao": {}, "nulo": {}, "horizonte": {}}

    for nome, cols in conjuntos(feats).items():
        d = rodar(pan, cols, dias_teste, variante)
        out["ablacao"][nome] = dict(n_features=len(cols),
                                    mae=float(np.abs(d["y"] - d["p"]).mean()),
                                    habilidade=habilidade(d), ic95=ic_habilidade(d))
        print(f"{nome:34s} {len(cols):3d} feats  "
              f"hab {out['ablacao'][nome]['habilidade']:+.2f}%")

    d = rodar(pan, feats, dias_teste, variante, embaralhar=True)
    out["nulo"] = dict(habilidade=habilidade(d), ic95=ic_habilidade(d))
    print(f"{'NULO por permutacao de feature':34s}      "
          f"hab {out['nulo']['habilidade']:+.2f}%")

    # Horizonte: painel novo com o alvo um dia adiante e o portao inteiro
    # deslocado junto. Comparar com o passo 3 exige a mesma janela de teste,
    # entao o corte de dias e recalculado sobre o painel novo.
    fontes = (cmo(), carga(), intercambio_liquido(), ear(), ear_sin(), ena())
    p2 = construir(*fontes, horizonte=2)
    p2 = p2[p2["y"].notna()]
    l1, l7 = "cmo_l2", "cmo_l8"
    p2 = p2[p2[l1].notna() & p2[l7].notna()].copy()
    p2["naive_sazonal"] = naive_sazonal(p2[l1].to_numpy(), p2[l7].to_numpy(),
                                        p2["dow"].to_numpy())
    p2["sub"] = p2["sub"].astype("category")
    f2 = colunas_modelo(p2)
    dt2 = np.sort(p2["dia"].unique())
    dt2 = dt2[dt2 >= dias_teste.min()]
    d2 = rodar(p2, f2, dt2, variante)
    d1 = rodar(pan, feats, dias[dias >= dt2.min()], variante)
    out["horizonte"] = {
        "D (passo 3)": dict(mae_modelo=float(np.abs(d1["y"] - d1["p"]).mean()),
                            mae_adversario=float(np.abs(d1["y"] - d1["adv"]).mean()),
                            habilidade=habilidade(d1), ic95=ic_habilidade(d1)),
        "D+1": dict(mae_modelo=float(np.abs(d2["y"] - d2["p"]).mean()),
                    mae_adversario=float(np.abs(d2["y"] - d2["adv"]).mean()),
                    habilidade=habilidade(d2), ic95=ic_habilidade(d2)),
    }
    h = out["horizonte"]
    out["horizonte"]["erro_cresce"] = bool(
        h["D+1"]["mae_modelo"] > h["D (passo 3)"]["mae_modelo"] and
        h["D+1"]["mae_adversario"] > h["D (passo 3)"]["mae_adversario"])
    for k in ("D (passo 3)", "D+1"):
        print(f"horizonte {k:12s} modelo {h[k]['mae_modelo']:6.2f}  "
              f"adversario {h[k]['mae_adversario']:6.2f}  "
              f"hab {h[k]['habilidade']:+6.2f}%  "
              f"IC [{h[k]['ic95'][0]:+.2f}; {h[k]['ic95'][1]:+.2f}]")
    print(f"erro cresce com o horizonte: {out['horizonte']['erro_cresce']}")

    out["custo_s"] = round(time.time() - t0, 1)
    ABLACAO.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    if not out["horizonte"]["erro_cresce"]:
        raise SystemExit("controle de horizonte reprovado: erro nao cresceu")


if __name__ == "__main__":
    main()
