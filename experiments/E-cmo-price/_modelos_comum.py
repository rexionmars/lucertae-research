"""Nomes de preditor e hiperparametro, compartilhados pelos passos 3, 4 e 5.

Fica separado para o nome do preditor ter UMA fonte: mudar a lista aqui muda a
tabela do passo 3, a decomposicao do passo 4 e a ablacao do passo 5 juntas.
"""
SEMENTE = 1

PARAMS = dict(objective="mae", n_estimators=600, learning_rate=0.05,
              num_leaves=63, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, verbose=-1,
              n_jobs=-1, random_state=SEMENTE)

PREDITORES = ["cmo_l1", "cmo_l7", "naive_sazonal", "climatologia",
              "lgbm_direto", "lgbm_residual", "lgbm_duas_partes",
              "oraculo_nivel"]
ADVERSARIO = "naive_sazonal"

FRACAO_TREINO_INICIAL = 0.55
B_BOOT = 2000
