"""Passo 4 -- onde o erro esta, sem ajustar modelo nenhum.

Rodar da raiz do repositorio, depois do passo 3:
    .venv/bin/python experiments/E-preco-cmo/4_decomposicao.py

Le previsoes.parquet e olha o erro por tres cortes: onde ele esta na propria
distribuicao, o que acontece nas meias-horas em que o CMO esta no piso, e a
separacao entre nivel do dia e forma dentro do dia.

O corte por quantil e o que decide a leitura do passo 3. MAE pesa toda linha
igual e RMSE pesa a cauda; se um preditor ganhar num quantil e perder no outro,
a divergencia entre as duas metricas nao e ruido, e a tabela de quantis mostra
onde ela nasce.

A separacao nivel/forma parte de duas partes que a serie de CMO tem
naturalmente:

    NIVEL  a media do dia, que a hidrologia e o balanco energetico movem
    FORMA  o desvio de cada meia-hora em relacao a essa media, que a carga e a
           geracao solar do proprio dia movem

Dentro de um subsistema o nivel responde pela maior parte da variancia do CMO;
no conjunto dos quatro, menos, porque a diferenca entre subsistemas na mesma
meia-hora entra no denominador. As duas frações saem lado a lado no JSON. As
duas partes tem preditor natural diferente, e a decomposicao diz em qual delas
cada preditor ganha ou perde.

MAE nao e aditiva sobre essa separacao: o erro de uma linha e a SOMA do erro de
nivel com o de forma, e |a+b| nao e |a|+|b|. Um preditor pode entao ganhar nas
duas partes medidas em separado e perder no total, e isso e resultado, nao
inconsistencia.

O corte por regime usa `cmopiso_d1` e `cmomed_d1` -- fracao de meias-horas no
piso e media do dia ANTERIOR. Condicionar ao dia anterior e legitimo porque ele
esta dentro do portao; condicionar ao dia alvo mediria o resultado com o
gabarito na mao.
"""
import json

import numpy as np
import pandas as pd

from _comum import DECOMPOSICAO, LIMIAR_PISO, PAINEL, PREVISOES, SAIDA
from _modelos_comum import ADVERSARIO, PREDITORES


def mae(y, p):
    return float(np.abs(np.asarray(y) - np.asarray(p)).mean())


def por_faixa(p, coluna, cortes, rotulos):
    faixa = pd.cut(p[coluna], bins=cortes, labels=rotulos, include_lowest=True)
    out = {}
    for r in rotulos:
        q = p[faixa == r]
        if len(q) == 0:
            continue
        out[r] = dict(n=int(len(q)),
                      **{k: round(mae(q["y"], q[k]), 2) for k in PREDITORES})
    return out


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    p = pd.read_parquet(PREVISOES)
    pan = pd.read_parquet(PAINEL)[["t", "sub", "cmopiso_d1", "cmomed_d1"]]
    p = p.merge(pan, on=["t", "sub"], how="left", validate="one_to_one")

    chave = ["sub", "dia"]
    nivel = p.groupby(chave)[["y"] + PREDITORES].mean()
    forma = p.copy()
    for c in ["y"] + PREDITORES:
        forma[c] = p[c] - p.groupby(chave)[c].transform("mean")

    err = {k: np.abs(p["y"] - p[k]) for k in PREDITORES}
    piso = (p["y"] <= LIMIAR_PISO).to_numpy()
    alto = (p["y"] > p["y"].quantile(0.95)).to_numpy()

    dec = dict(
        n_linhas=int(len(p)), n_dias_sub=int(len(nivel)),
        nivel={k: round(mae(nivel["y"], nivel[k]), 2) for k in PREDITORES},
        forma={k: round(mae(forma["y"], forma[k]), 2) for k in PREDITORES},
        completo={k: round(mae(p["y"], p[k]), 2) for k in PREDITORES},
        fracao_variancia_do_nivel=float(
            p.groupby(chave)["y"].transform("mean").var() / p["y"].var()),
        fracao_variancia_do_nivel_por_sub={
            s: float(q.groupby("dia")["y"].transform("mean").var() / q["y"].var())
            for s, q in p.groupby("sub", observed=True)},
        por_piso_da_vespera=por_faixa(
            p, "cmopiso_d1", [-0.001, 0.05, 0.35, 0.65, 1.0],
            ["ate 5%", "5 a 35%", "35 a 65%", "acima de 65%"]),
        por_nivel_da_vespera=por_faixa(
            p, "cmomed_d1", [-100, 20, 80, 200, 10000],
            ["ate 20", "20 a 80", "80 a 200", "acima de 200"]),
        por_meia_hora={int(h): {k: round(mae(q["y"], q[k]), 2)
                                for k in PREDITORES}
                       for h, q in p.groupby("hh")},
        fracao_alvo_no_piso=float(piso.mean()),
        quantis_do_erro={
            str(q): {k: round(float(err[k].quantile(q)), 2) for k in PREDITORES}
            for q in (0.25, 0.5, 0.75, 0.9, 0.95, 0.99)},
        fracao_de_linhas_melhor_que_adversario={
            k: float((err[k] < err[ADVERSARIO]).mean())
            for k in PREDITORES if k != ADVERSARIO},
        no_piso={k: dict(
            preve_no_piso=float((p[k].to_numpy()[piso] <= LIMIAR_PISO).mean()),
            erro_mediano=round(float(np.median(err[k].to_numpy()[piso])), 2),
            erro_mediano_fora=round(float(np.median(err[k].to_numpy()[~piso])), 2))
            for k in PREDITORES},
        cauda_alta={k: round(float(err[k].to_numpy()[alto].mean()), 2)
                    for k in PREDITORES},
        limiar_cauda_alta=round(float(p["y"].quantile(0.95)), 2),
    )
    DECOMPOSICAO.write_text(json.dumps(dec, indent=2, ensure_ascii=False))

    porsub = dec["fracao_variancia_do_nivel_por_sub"]
    print(f"variancia do CMO que e nivel do dia: "
          f"{100 * dec['fracao_variancia_do_nivel']:.1f}% no conjunto, "
          f"{100 * min(porsub.values()):.1f}% a {100 * max(porsub.values()):.1f}% "
          f"dentro de subsistema")
    print(f"\n{'preditor':16s} {'completo':>10s} {'nivel':>10s} {'forma':>10s}")
    for k in PREDITORES:
        print(f"{k:16s} {dec['completo'][k]:10.2f} {dec['nivel'][k]:10.2f} "
              f"{dec['forma'][k]:10.2f}")
    print(f"\n{'preditor':16s} " +
          " ".join(f"{'q' + str(q):>8s}" for q in (0.25, 0.5, 0.9, 0.95)))
    for k in PREDITORES:
        print(f"{k:16s} " + " ".join(
            f"{dec['quantis_do_erro'][str(q)][k]:8.2f}" for q in
            (0.25, 0.5, 0.9, 0.95)))

    print(f"\nalvo no piso em {100 * dec['fracao_alvo_no_piso']:.1f}% das linhas")
    for k in PREDITORES:
        v = dec["no_piso"][k]
        print(f"  {k:16s} preve no piso em {100 * v['preve_no_piso']:5.1f}% delas, "
              f"erro mediano {v['erro_mediano']:7.2f} (fora: {v['erro_mediano_fora']:6.2f})")

    print("\nMAE por fracao de piso da vespera")
    for r, v in dec["por_piso_da_vespera"].items():
        print(f"  {r:14s} n={v['n']:6d} " +
              " ".join(f"{k}={v[k]}" for k in
                       ("naive_sazonal", "lgbm_direto", "lgbm_residual",
                        "lgbm_duas_partes")))


if __name__ == "__main__":
    main()
