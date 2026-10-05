"""Passo 1 -- monta o painel subsistema x meia-hora e conta todo descarte.

Le data/raw/{cmo,curva_carga,intercambio,ear_subsistema,ena_subsistema} e grava
data/interim/E-preco-cmo/painel.parquet, mais o inventario de descarte em
janelas.json. Nao mede nada sobre o alvo: quem decide se o painel presta e o
passo 2.

Rodar da raiz do repositorio:
    .venv/bin/python experiments/E-preco-cmo/1_painel.py
"""
import json

import numpy as np
import pandas as pd

from _comum import (CMO_PISO, CMO_TETO, LIMIAR_PISO, PAINEL, SAIDA,
                    SUBSISTEMAS, naive_sazonal)
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load as carga,
    net_interchange as intercambio_liquido)
from _painel import colunas_feature, construir


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)

    fcmo, fcarga = cmo(), carga()
    finterc, fear, fsin, fena = intercambio_liquido(), ear(), ear_sin(), ena()

    grade = len(fcmo) * len(SUBSISTEMAS)
    dias_ausentes = sorted({str(d.date()) for d in
                            fcmo.index[fcmo[SUBSISTEMAS[0]].isna()].normalize().unique()})

    pan = construir(fcmo, fcarga, finterc, fear, fsin, fena, horizonte=1)
    if len(pan) != grade:
        raise SystemExit(f"painel com {len(pan)} linhas, grade tem {grade}")

    # Descartes, contados na ordem em que se aplicam.
    n0 = len(pan)
    pan = pan[pan["y"].notna()]
    n_sem_alvo = n0 - len(pan)

    # Termos da comparacao: alvo, D-1 e D-7 da mesma meia-hora. Sem os tres na
    # mesma linha as linhas de base correriam sobre amostras diferentes, e a
    # razao entre elas nao significaria nada.
    l1, l7 = "cmo_l1", "cmo_l7"
    n1 = len(pan)
    pan = pan[pan[l1].notna() & pan[l7].notna()]
    n_sem_base = n1 - len(pan)

    pan["naive_sazonal"] = naive_sazonal(pan[l1].to_numpy(), pan[l7].to_numpy(),
                                         pan["dow"].to_numpy())

    feats = colunas_feature(pan)
    cobertura = {c: float(pan[c].notna().mean()) for c in feats}

    pan.to_parquet(PAINEL, index=False)

    inv = {
        "janela": [str(pan["t"].min()), str(pan["t"].max())],
        "grade_completa": int(grade),
        "linhas_gravadas": int(len(pan)),
        "descarte_sem_alvo": int(n_sem_alvo),
        "descarte_sem_base": int(n_sem_base),
        "dias_de_cmo_ausentes": dias_ausentes,
        "n_features": len(feats),
        "features": feats,
        "cobertura_minima": min(cobertura.values()),
        "feature_menos_coberta": min(cobertura, key=cobertura.get),
        "cmo_fracao_no_piso": float((pan["y"] <= LIMIAR_PISO).mean()),
        "cmo_min": float(pan["y"].min()),
        "cmo_max": float(pan["y"].max()),
        "cmo_fora_da_faixa": int(((pan["y"] < CMO_PISO) | (pan["y"] > CMO_TETO)).sum()),
    }
    (SAIDA / "janelas.json").write_text(json.dumps(inv, indent=2, ensure_ascii=False))

    print(f"painel: {len(pan)} linhas, {len(feats)} features, "
          f"{inv['janela'][0][:10]} a {inv['janela'][1][:10]}")
    ausentes_no_painel = pd.date_range(
        pan["dia"].min(), pan["dia"].max(), freq="D").difference(
        pd.DatetimeIndex(pan["dia"].unique()))
    inv["dias_ausentes_no_painel"] = [str(d.date()) for d in ausentes_no_painel]
    (SAIDA / "janelas.json").write_text(
        json.dumps(inv, indent=2, ensure_ascii=False))

    print(f"descarte: {n_sem_alvo} sem alvo ({len(dias_ausentes)} dias de CMO "
          f"ausentes), {n_sem_base} sem D-1 ou D-7")
    print(f"o painel perde {len(ausentes_no_painel)} dias: cada buraco na fonte "
          f"leva junto o dia seguinte (sem D-1) e o dia sete depois (sem D-7)")
    print(f"piso: {100 * inv['cmo_fracao_no_piso']:.1f}% das meias-horas "
          f"em CMO <= {LIMIAR_PISO} R$/MWh")


if __name__ == "__main__":
    main()
