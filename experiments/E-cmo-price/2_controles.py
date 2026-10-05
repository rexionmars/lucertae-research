"""Passo 2 -- controles do painel. Bloqueia o passo 3 se algum reprovar.

Rodar da raiz do repositorio, depois do passo 1:
    .venv/bin/python experiments/E-preco-cmo/2_controles.py

Cada controle e falsificavel e independente do resultado pretendido: nenhum
deles fica verdadeiro por construcao do painel. O C3 e o mais caro e o unico
que testa o desenho, e nao o dado -- ele reconstroi as features a partir das
series mascaradas no instante de emissao e exige valor identico.

O QUE ESTES CONTROLES NAO TESTAM
--------------------------------
- Que o CMO publicado seja o CMO realizado. O ONS publica o valor do modelo de
  despacho; nao existe segunda fonte para conferir contra.
- O atraso de publicacao. Ele foi medido uma vez por fonte, por data de
  modificacao do arquivo, e esta declarado em `_comum`. Um so ponto por fonte.
- Feriado nacional e regional, que nao entram no painel: nao ha tabela de
  feriado no repositorio, e o efeito deles cai dentro do erro das duas partes.
"""
import json

import numpy as np
import pandas as pd

from _comum import (ATRASO_CARGA, ATRASO_CMO, ATRASO_HIDRO, CMO_PISO,
                    CMO_TETO, CONTROLES, PAINEL, SAIDA, SUBSISTEMAS)
from lucertae.sources.series import (
    cmo, ear, ear_sin, ena, hourly_load as carga,
    net_interchange as intercambio_liquido)
from _painel import colunas_feature, construir

# Fracao minima de linhas com valor para cada familia de feature. Abaixo disso
# a familia nao entra no modelo com cobertura suficiente para ser avaliada.
COBERTURA_MINIMA = 0.97
DIAS_SORTEADOS = 40
# Dias que NAO aparecem no painel, sobre a janela de 2024-01-01 a 2026-08-27.
# Sao 24, e nao os 8 dias sem CMO no arquivo do ONS: cada buraco na fonte custa
# TRES dias de painel -- o proprio, o dia seguinte, que perde o D-1 da ingenua,
# e o dia sete depois, que perde o D-7. Os 8 buracos estao afastados o bastante
# para que nenhum desses derivados colida com outro, e por isso 8 x 3 fecha;
# com buracos mais proximos o numero seria menor. E tripwire, nao tolerancia:
# se a fonte for rebaixada e o numero mudar, o controle reprova e obriga a
# olhar em vez de absorver a mudanca em silencio.
DIAS_AUSENTES_NO_PAINEL = 24


def _igual(a, b):
    """Igualdade elemento a elemento tratando ausente como igual a ausente."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    return np.all((np.isclose(a, b, rtol=1e-9, atol=1e-9)) |
                  (np.isnan(a) & np.isnan(b)))


def c1_grade(pan):
    """Chave unica, 48 meias-horas por dia e nenhum dia inventado.

    A terceira parte importa: os dias sem CMO precisam continuar AUSENTES do
    painel. Se algum passo os preenchesse por interpolacao, o calendario
    fecharia e o alvo seria numero que o operador nunca publicou.
    """
    dup = int(pan.duplicated(["sub", "t"]).sum())
    por_dia = pan.groupby(["sub", "dia"]).size()
    # O primeiro e o ultimo dia da janela podem sair truncados pelo descarte de
    # D-7; os do meio, nao.
    meio = por_dia[(por_dia.index.get_level_values("dia") > pan["dia"].min()) &
                   (por_dia.index.get_level_values("dia") < pan["dia"].max())]
    incompletos = int((meio != 48).sum())
    calendario = pd.date_range(pan["dia"].min(), pan["dia"].max(), freq="D")
    ausentes = calendario.difference(pd.DatetimeIndex(pan["dia"].unique()))
    return dict(nome="C1 grade e chave", duplicatas=dup,
                dias_incompletos=incompletos,
                dias_ausentes=[str(d.date()) for d in ausentes],
                dias_no_calendario=len(calendario), bloqueante=True,
                passa=(dup == 0 and incompletos == 0 and len(ausentes) == DIAS_AUSENTES_NO_PAINEL))


def c2_faixa(pan):
    """CMO dentro da faixa fisica, e o alvo sem ausente depois do descarte."""
    fora = int(((pan["y"] < CMO_PISO) | (pan["y"] > CMO_TETO)).sum())
    nulos = int(pan["y"].isna().sum())
    return dict(nome="C2 faixa fisica do alvo", fora_da_faixa=fora,
                alvo_ausente=nulos, minimo=float(pan["y"].min()),
                maximo=float(pan["y"].max()), bloqueante=True,
                passa=(fora == 0 and nulos == 0))


def c3_portao(pan, fontes, rng):
    """Vazamento: refazer as features com as fontes mascaradas na emissao.

    Para o dia alvo D a previsao sai as 12:00 de D-1. Mascarar significa apagar
    o CMO de D em diante, a carga e o intercambio de D-1 em diante e a
    hidrologia depois de D-3. Se alguma feature olhasse para o futuro, o valor
    mascarado mudaria. Este controle falha por diferenca em UMA celula.
    """
    cmo, carga, interc, ear, ear_sin, ena = fontes
    feats = colunas_feature(pan)
    dias = pd.Series(sorted(pan["dia"].unique()))
    alvo = dias[(dias > dias.min() + pd.Timedelta(days=14)) &
                (dias < dias.max() - pd.Timedelta(days=1))]
    sorteio = alvo.sample(n=min(DIAS_SORTEADOS, len(alvo)), random_state=rng)

    divergentes, celulas = [], 0
    for d in sorteio:
        c = cmo.copy(); c[c.index >= d] = np.nan
        g = carga.copy(); g[g.index >= d - pd.Timedelta(days=ATRASO_CARGA - 1)] = np.nan
        i = interc.copy(); i[i.index >= d - pd.Timedelta(days=ATRASO_CARGA - 1)] = np.nan
        e = ear.copy(); e[e.index > d - pd.Timedelta(days=ATRASO_HIDRO)] = np.nan
        es = ear_sin.copy(); es[es.index > d - pd.Timedelta(days=ATRASO_HIDRO)] = np.nan
        n = ena.copy(); n[n.index > d - pd.Timedelta(days=ATRASO_HIDRO)] = np.nan

        ref = pan[pan["dia"] == d].sort_values(["sub", "t"])
        novo = construir(c, g, i, e, es, n, horizonte=1)
        novo = novo[novo["dia"] == d].sort_values(["sub", "t"])
        if len(novo) != len(ref):
            divergentes.append((str(d.date()), "linhas"))
            continue
        for f in feats:
            celulas += len(ref)
            if not _igual(ref[f].to_numpy(), novo[f].to_numpy()):
                divergentes.append((str(d.date()), f))

    nomes = sorted({f for _, f in divergentes})
    return dict(nome="C3 portao de informacao", dias_testados=len(sorteio),
                celulas_conferidas=int(celulas), features_divergentes=nomes,
                bloqueante=True, passa=(len(divergentes) == 0))


def c4_cobertura(pan):
    """Toda feature cobre pelo menos COBERTURA_MINIMA das linhas.

    Falsificavel e nao redundante: e este controle que pega `id_subsistema` com
    espaco a direita nos arquivos de EAR e ENA. Sem o `strip`, a coluna do
    subsistema afetado fica vazia e a cobertura despenca.
    """
    cob = {c: float(pan[c].notna().mean()) for c in colunas_feature(pan)}
    ruins = {c: round(v, 4) for c, v in cob.items() if v < COBERTURA_MINIMA}
    return dict(nome="C4 cobertura de feature", limiar=COBERTURA_MINIMA,
                abaixo_do_limiar=ruins, pior=min(cob.values()),
                bloqueante=True, passa=(len(ruins) == 0))


def c5_bases(pan):
    """Ordem esperada entre as linhas de base ingenuas.

    Se a persistencia de D-1 nao batesse a climatologia por meia-hora, o alvo
    nao teria memoria de curto prazo e o experimento inteiro nao teria objeto.
    A comparacao corre sobre a mesma amostra, que e o painel gravado.
    """
    mae = lambda a: float(np.abs(pan["y"] - a).mean())
    clim = pan.groupby(["sub", "hh"])["y"].transform("mean")
    m = dict(d1=mae(pan["cmo_l1"]), d7=mae(pan["cmo_l7"]),
             sazonal=mae(pan["naive_sazonal"]), climatologia=mae(clim))
    return dict(nome="C5 ordem das linhas de base", mae=m, bloqueante=True,
                passa=(m["d1"] < m["climatologia"] and
                       m["sazonal"] <= m["d7"]))


def c6_subsistemas(pan):
    """As quatro colunas cruzadas sao series distintas, nao copia da mesma.

    Pega o defeito de pivot em que um rotulo sujo colapsa dois subsistemas.
    """
    largo = pan.pivot_table(index="t", columns="sub", values="y")
    cor = largo.corr()
    fora = [(a, b) for a in SUBSISTEMAS for b in SUBSISTEMAS
            if a < b and cor.loc[a, b] > 0.999]
    return dict(nome="C6 subsistemas distintos",
                correlacao_maxima=float(cor.where(
                    ~np.eye(len(cor), dtype=bool)).max().max()),
                pares_colapsados=fora, bloqueante=True, passa=(len(fora) == 0))


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    pan = pd.read_parquet(PAINEL)
    fontes = (cmo(), carga(), intercambio_liquido(), ear(), ear_sin(), ena())

    saida = [c1_grade(pan), c2_faixa(pan), c3_portao(pan, fontes, 7),
             c4_cobertura(pan), c5_bases(pan), c6_subsistemas(pan)]

    for c in saida:
        print(f"[{'passa' if c['passa'] else 'REPROVA'}] {c['nome']}")
        for k, v in c.items():
            if k not in ("nome", "passa", "bloqueante"):
                print(f"    {k}: {v}")

    CONTROLES.write_text(json.dumps(saida, indent=2, ensure_ascii=False))
    ruins = [c["nome"] for c in saida if c["bloqueante"] and not c["passa"]]
    if ruins:
        raise SystemExit("controle bloqueante reprovado: " + "; ".join(ruins))
    print("\ntodos os controles bloqueantes passaram")


if __name__ == "__main__":
    main()
