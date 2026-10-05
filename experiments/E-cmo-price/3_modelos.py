"""Passo 3 -- linhas de base, modelos e habilidade, com origem movel.

Rodar da raiz do repositorio, depois do passo 2 ter passado:
    .venv/bin/python experiments/E-preco-cmo/3_modelos.py

DESENHO
-------
Estimando: CMO em R$/MWh de cada uma das 48 meias-horas do dia D, nos quatro
subsistemas, com previsao emitida as 12:00 do dia D-1.

Adversario: a ingenua sazonal da literatura de previsao de preco -- terca a
sexta repetem D-1, sabado a segunda repetem D-7. Nao a ingenua simples: em
serie de preco horario a repeticao do dia anterior ja carrega a forma diurna e
o nivel, e e ela que um modelo precisa bater para acrescentar alguma coisa.

Perda: MAE, e ela e escolhida ANTES de olhar o resultado, pelas duas razoes que
a literatura da area registra -- e a metrica em que a serie de preco se compara
entre estudos, e o CMO tem cauda pesada o bastante para o RMSE virar relatorio
de meia duzia de horas. O RMSE sai como secundario, e a divergencia entre os
dois, se houver, e resultado e nao ruido.

Recalibracao MENSAL com janela expansiva: o modelo e reajustado no primeiro dia
de cada mes de teste com todo o passado disponivel. Sem recalibrar, um unico
ajuste teria de valer por 14 meses, e a ingenua -- que se atualiza sozinha todo
dia -- ganharia por desenho e nao por merito.

CONTROLE POSITIVO
-----------------
O oraculo de nivel recebe a media verdadeira do dia D e desloca a ingenua ate
ela, mantendo a forma. Se ele nao mostrasse habilidade grande, o desenho seria
incapaz de detectar ganho e nenhum numero negativo do modelo significaria nada.

O QUE ESTE PASSO NAO TESTA
--------------------------
Uma configuracao de hiperparametro e uma semente. O IC cobre a variacao entre
dias do periodo de teste; nao cobre variancia de ajuste, de semente, nem da
data de corte entre treino e teste.
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from _comum import (LIMIAR_PISO, PAINEL, PREVISOES, RESULTADO, SAIDA,
                    SUBSISTEMAS)
from _modelos_comum import (ADVERSARIO, B_BOOT, FRACAO_TREINO_INICIAL, PARAMS,
                            PREDITORES, SEMENTE)
from _painel import colunas_modelo


def mae(y, p):
    return float(np.abs(y - p).mean())


def rmse(y, p):
    return float(np.sqrt(((y - p) ** 2).mean()))


def ajustar_e_prever(pan, feats, dias_teste):
    """Origem movel com recalibracao mensal e janela de treino expansiva."""
    saida, custo = [], 0.0
    meses = sorted(pd.Series(dias_teste).dt.to_period("M").unique())
    for m in meses:
        ini, fim = m.to_timestamp(), m.to_timestamp() + pd.offsets.MonthBegin(1)
        tr = pan[pan["dia"] < ini]
        te = pan[(pan["dia"] >= ini) & (pan["dia"] < fim)]
        if te.empty:
            continue
        t0 = time.time()
        direto = lgb.LGBMRegressor(**PARAMS).fit(tr[feats], tr["y"])
        # O residual aprende a CORRECAO da ingenua, e nao o nivel do preco. Sao
        # dois vieses indutivos diferentes sobre o mesmo insumo: um tem de
        # reconstruir o nivel do zero, o outro so precisa saber quando a
        # repeticao do dia anterior erra.
        residual = lgb.LGBMRegressor(**PARAMS).fit(
            tr[feats], tr["y"] - tr["naive_sazonal"])
        # Duas partes. A distribuicao do CMO tem massa concentrada no piso -- o
        # custo marginal e nulo quando sobra oferta -- e uma cauda longa. Um
        # regressor unico devolve a mediana condicional, que quase nunca cai
        # exatamente no piso. A regra de decisao abaixo e a que minimiza MAE sob
        # esse modelo: prever o piso quando ele e mais provavel que o resto.
        piso_tr = (tr["y"] <= LIMIAR_PISO)
        clf = lgb.LGBMClassifier(**{**PARAMS, "objective": "binary"}).fit(
            tr[feats], piso_tr.astype(int))
        reg = lgb.LGBMRegressor(**PARAMS).fit(
            tr.loc[~piso_tr, feats], tr.loc[~piso_tr, "y"])
        valor_piso = float(tr.loc[piso_tr, "y"].median())
        custo += time.time() - t0

        d = te[["t", "sub", "dia", "hh", "dow", "y", "cmo_l1", "cmo_l7",
                "naive_sazonal"]].copy()
        d["climatologia"] = tr.groupby(["sub", "hh"])["y"].mean().reindex(
            pd.MultiIndex.from_arrays([te["sub"], te["hh"]])).to_numpy()
        d["lgbm_direto"] = direto.predict(te[feats])
        d["lgbm_residual"] = te["naive_sazonal"].to_numpy() + residual.predict(te[feats])
        prob = clf.predict_proba(te[feats])[:, 1]
        d["lgbm_duas_partes"] = np.where(prob > 0.5, valor_piso,
                                         reg.predict(te[feats]))
        saida.append(d)
    return pd.concat(saida, ignore_index=True), custo


def oraculo_de_nivel(p):
    """Ingenua sazonal deslocada pela MEDIANA do residuo do dia. Nao e previsao.

    A mediana, e nao a media: a perda declarada e MAE, e a constante que
    minimiza MAE e a mediana. Deslocar pela media mediria a escolha de
    estatistica do analista em vez do ganho de acertar o nivel -- medido, o
    deslocamento pela media entrega +0,9% de habilidade e o pela mediana
    +17,7%, sobre o mesmo dado e o mesmo dia.
    """
    r = p["y"] - p["naive_sazonal"]
    return p["naive_sazonal"] + r.groupby([p["sub"], p["dia"]]).transform("median")


def boot_habilidade(p, preditor, adversario, b=B_BOOT, semente=SEMENTE):
    """IC da habilidade por reamostragem de DIA, nao de linha.

    O erro de meias-horas do mesmo dia e correlacionado: reamostrar linha daria
    IC estreito demais. O bloco e o dia inteiro, com os quatro subsistemas
    juntos, porque eles tambem andam juntos.
    """
    g = p.groupby("dia")
    em = g.apply(lambda d: np.abs(d["y"] - d[preditor]).sum(), include_groups=False)
    ea = g.apply(lambda d: np.abs(d["y"] - d[adversario]).sum(), include_groups=False)
    n = g.size()
    em, ea, n = em.to_numpy(), ea.to_numpy(), n.to_numpy()
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, len(n), size=(b, len(n)))
    hm = em[idx].sum(1) / n[idx].sum(1)
    ha = ea[idx].sum(1) / n[idx].sum(1)
    h = 100.0 * (1.0 - hm / ha)
    return float(np.percentile(h, 2.5)), float(np.percentile(h, 97.5))


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    pan = pd.read_parquet(PAINEL)
    pan["sub"] = pan["sub"].astype("category")
    feats = colunas_modelo(pan)

    dias = np.sort(pan["dia"].unique())
    corte = dias[int(len(dias) * FRACAO_TREINO_INICIAL)]
    dias_teste = dias[dias >= corte]

    t0 = time.time()
    p, custo_ajuste = ajustar_e_prever(pan, feats, dias_teste)
    p["oraculo_nivel"] = oraculo_de_nivel(p)
    p.to_parquet(PREVISOES, index=False)

    y = p["y"].to_numpy()
    erros = {k: dict(mae=mae(y, p[k].to_numpy()), rmse=rmse(y, p[k].to_numpy()))
             for k in PREDITORES}
    adv = erros[ADVERSARIO]["mae"]
    hab = {}
    for k in PREDITORES:
        if k == ADVERSARIO:
            continue
        lo, hi = boot_habilidade(p, k, ADVERSARIO)
        hab[k] = dict(habilidade_mae=100.0 * (1 - erros[k]["mae"] / adv),
                      ic95=[lo, hi],
                      habilidade_rmse=100.0 * (1 - erros[k]["rmse"] /
                                               erros[ADVERSARIO]["rmse"]))

    por_sub = {}
    for s in SUBSISTEMAS:
        q = p[p["sub"] == s]
        por_sub[s] = {k: mae(q["y"].to_numpy(), q[k].to_numpy())
                      for k in PREDITORES}
    por_mes = (p.assign(m=p["dia"].dt.to_period("M").astype(str))
               .groupby("m").apply(lambda d: pd.Series(
                   {k: mae(d["y"].to_numpy(), d[k].to_numpy())
                    for k in PREDITORES}), include_groups=False))

    res = dict(
        janela_teste=[str(p["t"].min()), str(p["t"].max())],
        n_linhas=int(len(p)), n_dias=int(p["dia"].nunique()),
        n_features=len(feats), recalibracoes=int(p["dia"].dt.to_period("M").nunique()),
        adversario=ADVERSARIO, erros=erros, habilidade=hab,
        mae_por_subsistema=por_sub,
        mae_por_mes=por_mes.round(2).to_dict(orient="index"),
        custo_s=dict(ajuste=round(custo_ajuste, 1), total=round(time.time() - t0, 1)),
    )
    RESULTADO.write_text(json.dumps(res, indent=2, ensure_ascii=False))

    print(f"teste: {res['n_linhas']} linhas, {res['n_dias']} dias, "
          f"{res['recalibracoes']} recalibracoes, {feats and len(feats)} features")
    print(f"{'preditor':16s} {'MAE':>8s} {'RMSE':>8s} {'hab.MAE':>9s} {'IC95':>20s}")
    for k in PREDITORES:
        h = hab.get(k)
        ic = f"[{h['ic95'][0]:+.2f}; {h['ic95'][1]:+.2f}]" if h else ""
        hv = f"{h['habilidade_mae']:+.2f}%" if h else "adversario"
        print(f"{k:16s} {erros[k]['mae']:8.2f} {erros[k]['rmse']:8.2f} "
              f"{hv:>9s} {ic:>20s}")
    print(f"custo de ajuste: {res['custo_s']['ajuste']:.0f} s")


if __name__ == "__main__":
    main()
