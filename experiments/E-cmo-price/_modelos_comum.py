"""Shared predictor names and hyperparameters for steps 3, 4, and 5.

Keeping predictor names in one place ensures that changes are reflected in the
step 3 results, step 4 decomposition, and step 5 ablation together.
"""
RANDOM_SEED = 1

PARAMS = dict(objective="mae", n_estimators=600, learning_rate=0.05,
              num_leaves=63, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, verbose=-1,
              n_jobs=-1, random_state=RANDOM_SEED)

PREDICTORS = ["cmo_l1", "cmo_l7", "naive_sazonal", "climatologia",
              "lgbm_direto", "lgbm_residual", "lgbm_duas_partes",
              "oraculo_nivel"]
BASELINE = "naive_sazonal"

INITIAL_TRAIN_FRACTION = 0.55
N_BOOTSTRAP = 2000
