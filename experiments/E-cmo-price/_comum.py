"""Definicoes compartilhadas do E-preco-cmo. Nao contem analise: so caminho,
esquema, o portao de informacao e a leitura das fontes.

Rodar sempre da raiz do repositorio.

PORTAO DE INFORMACAO
--------------------
O experimento preve as 48 meias-horas do dia D com previsao emitida as 12:00 do
dia D-1. O que esta disponivel nesse instante foi MEDIDO, fonte a fonte, pela
diferenca entre o ultimo registro do arquivo em disco e a data de modificacao
dele -- uma observacao por fonte, o que e limite declarado e nao regra:

    CMO semi-horario   baixado 2026-08-27 10:08, ultimo registro 2026-08-27
                       23:30. O dia inteiro ja estava no arquivo as 10:08:
                       o CMO e publicado COM ANTECEDENCIA, nao ex-post.
    Curva de carga     baixado 2026-09-02 04:25, ultimo 2026-08-31 23:00.
                       Atraso ~1,2 dia.
    Intercambio        baixado 2026-09-02 04:44, ultimo 2026-08-31 23:00.
                       Atraso ~1,2 dia.
    EAR diario         baixado 2026-09-02 04:25, ultimo 2026-08-31. ~2,2 dias.
    ENA diario         baixado 2026-09-06 11:22, ultimo 2026-09-04. ~2,3 dias.

Dai o portao, que vale IGUALMENTE para o modelo e para as linhas de base:

    CMO ................ ate o fim do dia D-1
    carga, intercambio . ate o fim do dia D-2
    EAR, ENA ........... ate o dia D-3
    calendario de D .... deterministico, liberado

O CMO ser publicado antes do dia nao esvazia a tarefa: na emissao das 12:00 de
D-1 o numero do operador para o dia D ainda nao saiu.

DE ONDE VEM A LEITURA
---------------------
Os leitores do ONS estao em `lucertae.sources.series`, e os atrasos de
publicacao em `lucertae.gate`. Estavam aqui ate 07/09/2026, quando o mesmo codigo apareceu
pela segunda vez em `experiments/E-osciloscopio/_comum.py`: duas copias da mesma
serie sao duas series que podem divergir sem ninguem notar.

PROPRIEDADES DO DADO QUE OBRIGAM DECISAO
----------------------------------------
1. Faltam 8 dias inteiros de CMO na janela (48 meias-horas x 4 subsistemas cada).
   Eles entram na grade como ausentes e sao descartados com contagem, nunca
   preenchidos por interpolacao -- interpolar criaria alvo que o operador nunca
   publicou. Cada buraco custa TRES dias de painel: o proprio, o dia seguinte
   que perde o D-1 e o dia sete depois que perde o D-7.
2. O CMO e limitado por piso e teto regulatorios e encosta nos dois: 17% a 28%
   das meias-horas ficam em <= 1 R$/MWh, e o maximo observado e 4.870,95.
   A distribuicao e inflada no piso e de cauda pesada a direita.
3. A carga e o intercambio sao HORARIOS; o CMO e semi-horario. A juncao e pela
   hora cheia, e as duas meias-horas de uma hora recebem o mesmo valor.
"""
import numpy as np

from lucertae.paths import ROOT as RAIZ, output_dir as saida
from lucertae.sources.series import (
    SUBSYSTEMS as SUBSISTEMAS, cmo, ear, ear_sin, ena, hourly_load as carga,
    net_interchange as intercambio_liquido)

SAIDA = saida("E-cmo-price")

PAINEL = SAIDA / "painel.parquet"
CONTROLES = SAIDA / "controles.json"
PREVISOES = SAIDA / "previsoes.parquet"
RESULTADO = SAIDA / "resultado.json"
DECOMPOSICAO = SAIDA / "decomposicao.json"

# Portao, em dias, contado do dia alvo D. Numero maior e informacao mais velha.
# O atraso que justifica cada um esta MEDIDO em `lucertae.gate`, com
# `lucertae gate` refazendo a medida sobre os arquivos em disco.
from lucertae.gate import GATE_DAYS as ATRASO_DIAS

ATRASO_CMO = ATRASO_DIAS["cmo"]
ATRASO_CARGA = ATRASO_DIAS["load"]
ATRASO_HIDRO = ATRASO_DIAS["ear"]

# Faixa fisica do CMO em R$/MWh. Piso e teto regulatorios do PLD, com folga:
# o teto observado na janela e 4.870,95 e o minimo e -39,24.
CMO_PISO = -100.0
CMO_TETO = 6000.0

# Limiar de "piso" para a fracao de meias-horas em custo marginal nulo.
LIMIAR_PISO = 1.0


def naive_sazonal(cmo_l1, cmo_l7, dow):
    """Linha de base ingenua canonica da literatura de previsao de preco.

    Terca a sexta repetem D-1; sabado, domingo e segunda repetem D-7, porque o
    dia anterior a eles tem perfil de outro tipo de dia. `dow` segue o pandas:
    0 e segunda.
    """
    return np.where(np.isin(dow, [1, 2, 3, 4]), cmo_l1, cmo_l7)
