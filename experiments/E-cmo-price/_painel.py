"""Construcao do painel subsistema x meia-hora com as features do dia seguinte.

Fica separado do runner porque o controle de vazamento (C4) precisa chamar a
MESMA funcao sobre series truncadas no instante de emissao. Se alguma feature
olhasse para o futuro, truncar mudaria o valor dela, e o controle falharia.

Toda feature nomeia no sufixo o dia de onde vem, contado do dia alvo D:
`_d1` e o dia D-1 inteiro, `_l1` e a mesma meia-hora do dia D-1.
"""
import numpy as np
import pandas as pd

from _comum import (ATRASO_CARGA, ATRASO_CMO, ATRASO_HIDRO, LIMIAR_PISO,
                    SUBSISTEMAS)


def _agrega_dia(serie_mh):
    """Media, minimo, maximo e fracao no piso, por dia, de uma serie de 30 min."""
    dia = serie_mh.index.normalize()
    g = serie_mh.groupby(dia)
    return pd.DataFrame({
        "med": g.mean(), "min": g.min(), "max": g.max(),
        "piso": (serie_mh <= LIMIAR_PISO).groupby(dia).mean(),
    })


def construir(cmo, carga, interc, ear, ear_sin, ena, horizonte=1):
    """Painel longo, uma linha por (subsistema, meia-hora do dia alvo).

    `horizonte` em dias desloca o alvo sem mexer no instante de emissao: com 2,
    a previsao emitida na vespera de D vale para D+1, e todo atraso do portao
    cresce de 1. Serve ao controle C9, que exige erro crescente com o horizonte.

    O alvo `y` e o CMO do proprio instante. As features vem do portao declarado
    em `_comum`, e nenhuma delas toca o dia D.
    """
    desl = horizonte - 1
    dcmo = ATRASO_CMO + desl
    dcarga = ATRASO_CARGA + desl
    dhidro = ATRASO_HIDRO + desl

    agr = {s: _agrega_dia(cmo[s]) for s in SUBSISTEMAS}
    passos = 48  # meias-horas por dia

    blocos = []
    for s in SUBSISTEMAS:
        d = pd.DataFrame({"t": cmo.index, "y": cmo[s].to_numpy()})
        d["sub"] = s
        d["dia"] = d["t"].dt.normalize()
        d["hh"] = d["t"].dt.hour * 2 + d["t"].dt.minute // 30
        d["dow"] = d["t"].dt.dayofweek
        d["mes"] = d["t"].dt.month

        # CMO proprio, mesma meia-hora de dias anteriores
        for k in (0, 1, 2, 6):
            d[f"cmo_l{dcmo + k}"] = cmo[s].shift(passos * (dcmo + k)).to_numpy()

        # CMO proprio, agregados de dia inteiro
        for k in (0, 1, 6):
            idx = d["dia"] - pd.Timedelta(days=dcmo + k)
            a = agr[s].reindex(idx)
            for c in ("med", "min", "max", "piso"):
                d[f"cmo{c}_d{dcmo + k}"] = a[c].to_numpy()

        # CMO dos quatro subsistemas na mesma meia-hora de D-1: o acoplamento
        # entre eles e por limite de intercambio, e o preco de um informa o do
        # outro. A coluna do proprio subsistema repete `cmo_l{dcmo}` de
        # proposito, para o conjunto de colunas ser identico nos quatro blocos.
        for o in SUBSISTEMAS:
            d[f"cmo_{o}_l{dcmo}"] = cmo[o].shift(passos * (dcmo + 0)).to_numpy()
        idx1 = d["dia"] - pd.Timedelta(days=dcmo)
        for o in SUBSISTEMAS:
            d[f"cmomed_{o}_d{dcmo}"] = agr[o]["med"].reindex(idx1).to_numpy()

        # Carga e intercambio sao horarios: junta pela hora cheia
        hora = d["t"].dt.floor("h")
        for k in (0, 1, 7):
            d[f"carga_l{dcarga + k}"] = carga[s].reindex(
                hora - pd.Timedelta(days=dcarga + k)).to_numpy()
        cd = carga[s].groupby(carga.index.normalize()).mean()
        cx = carga[s].groupby(carga.index.normalize()).max()
        idxc = d["dia"] - pd.Timedelta(days=dcarga)
        d[f"cargamed_d{dcarga}"] = cd.reindex(idxc).to_numpy()
        d[f"cargamax_d{dcarga}"] = cx.reindex(idxc).to_numpy()
        d[f"cargasin_d{dcarga}"] = carga.sum(axis=1).groupby(
            carga.index.normalize()).mean().reindex(idxc).to_numpy()
        d[f"interc_l{dcarga}"] = interc[s].reindex(
            hora - pd.Timedelta(days=dcarga)).to_numpy()
        d[f"intercmed_d{dcarga}"] = interc[s].groupby(
            interc.index.normalize()).mean().reindex(idxc).to_numpy()

        # Hidrologia diaria
        idxh = d["dia"] - pd.Timedelta(days=dhidro)
        d[f"ear_d{dhidro}"] = ear[s].reindex(idxh).to_numpy()
        d["ear_delta7"] = d[f"ear_d{dhidro}"] - ear[s].reindex(
            idxh - pd.Timedelta(days=7)).to_numpy()
        d[f"earsin_d{dhidro}"] = ear_sin.reindex(idxh).to_numpy()
        d[f"ena_d{dhidro}"] = ena[s].reindex(idxh).to_numpy()
        d[f"enam7_d{dhidro}"] = ena[s].rolling(7).mean().reindex(idxh).to_numpy()

        blocos.append(d)

    pan = pd.concat(blocos, ignore_index=True)
    return pan.sort_values(["t", "sub"]).reset_index(drop=True)


# O subsistema entra no modelo como categoria. Sem ele o modelo nao sabe de
# qual subsistema e a linha: as quatro colunas `cmo_<sub>_l1` aparecem sempre na
# mesma ordem, e a que repete o proprio passado nao e identificavel dentro
# delas. Fica fora de `colunas_feature` porque nao e numerica -- o controle de
# vazamento compara valor a valor -- e volta em `colunas_modelo`.
FEATURE_CATEGORICA = "sub"


def colunas_feature(pan):
    """Features numericas. Fora ficam alvo, chave e a linha de base ingenua."""
    fora = {"t", "y", "dia", "sub", "naive_sazonal"}
    return [c for c in pan.columns if c not in fora]


def colunas_modelo(pan):
    """O que o modelo recebe: as numericas mais o subsistema como categoria."""
    return colunas_feature(pan) + [FEATURE_CATEGORICA]
