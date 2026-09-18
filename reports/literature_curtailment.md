# Literature: forecasting renewable curtailment

Review carried out to guide improvements to the model in `reports/baseline_curtailment.md`.
Experiment results in `reports/experiments_curtailment.md`.

## Brazil

- **Vieira, Silva, Lourenço, Monaro, Salles and Almeida (2026), *Characterizing wind and solar
  curtailment in Brazil: an evidence-based analysis of operational drivers*, Electric Power Systems
  Research 254, 112672, doi:[10.1016/j.epsr.2025.112672](https://doi.org/10.1016/j.epsr.2025.112672)** —
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378779625012593) ·
  [USP repository](https://repositorio.usp.br/directbitstream/e8bd1984-563f-43f4-a7fa-1128694361e8/Characterizing_wind_2026.pdf).
  According to the abstract, the authors identify two regimes. In **energy balance** curtailment,
  **distributed micro- and mini-generation (MMGD) is the strongest predictor** (odds ratio ≈ 9.8 for solar
  and 6.2 for wind), and system load is associated with a lower probability of curtailment. In
  **reliability** curtailment, the main predictor is **high renewable generation in the Northeast** (odds ratio
  ≈ 5.9), which the authors relate to conservative ONS dispatch. The August 2023 blackout marks a
  structural break. *Only the abstract was read; the full text could not be downloaded. The values above
  should be checked against the full text before being cited in another document.*
- **Volt Robotics (2026), via [pv magazine](https://www.pv-magazine.com/2026/02/02/brazil-curtails-20-of-solar-and-wind-output-in-2025-with-losses-at-1-2-billion/)** —
  20% of solar and wind generation curtailed in 2025 (R$ 6.5 billion). Peak between August and October. **Sunday mornings**
  are the critical point, with strong wind combined with the solar peak. 16 days close to the lower security limit
  (1 in 2024).
- **[Canal Solar](https://canalsolar.com.br/en/renewable-cut-panorama-curtailment/)** — almost daily
  curtailment in BA, PI and MG; transmission saturation in the NE; 50 GW of distributed solar versus 23 GW centralized.

## Forecasting curtailment and congestion

- **Titz, Pütz and Witthaut (2024), *Identifying drivers and mitigators for congestion and redispatch in
  the German electric power system with explainable AI*, Applied Energy 356, 122351,
  doi:[10.1016/j.apenergy.2023.122351](https://doi.org/10.1016/j.apenergy.2023.122351)** —
  [arXiv:2307.12636](https://arxiv.org/abs/2307.12636). Gradient boosting + SHAP to forecast the
  hourly redispatch volume **with day-ahead variables only**. Wind is the variable with the largest contribution (SHAP),
  but **hydro and cross-border interchange** also weigh in. Calendar variables did not help
  once the system variables were included. Training and test separated by 24h gaps.
- **Acun et al. (2023), *Unlocking the Potential of Renewable Energy Through Curtailment Prediction*,
  Climate Change AI workshop, NeurIPS 2023 (arXiv, May 2024)** — [arXiv:2405.18526](https://arxiv.org/abs/2405.18526). Proposes the problem and a
  dataset; recommends granularity below 1h, local (nodal) forecasting and a 24h horizon.
- **[*Classification Models for Forecasting and Real-Time Identification of Solar Curtailment in the
  California Grid*](https://dl.acm.org/doi/fullHtml/10.1145/3632775.3661951) (ACM e-Energy 2024)** —
  classification of curtailment occurrence in CAISO using the **day-ahead net demand forecast**
  published by the operator.
- **[*Predicting Renewable Curtailment in Distribution Grids Using Neural Networks*](https://elib.dlr.de/194148/1/Predicting%20Renewable%20Curtailment%20in%20Distribution%20Grids%20Using%20Neural%20Networks.pdf)
  (DLR)** — neural networks for wind, transformer flow and congestion, in the context of Redispatch 2.0.
- **[*Probabilistic day-ahead forecasting of system-level renewable energy and electricity demand*](https://www.nature.com/articles/s41467-026-69015-w)
  (Terrén-Serrano, Deshmukh and Martínez-Ramón, Nature Communications, 2026)** — probabilistic day-ahead
  forecasting for CAISO; +25% *skill* over the operational references (value not checked against the
  full text).

## Methods for zero-inflated targets and uncertainty

- **Two-stage (*hurdle*) models**: occurrence classifier × regressor of the conditional
  magnitude; in gradient boosting, with a Tweedie objective or regression on positives only —
  [Nathan et al., Scientific Reports 2026](https://www.nature.com/articles/s41598-026-35197-y)
  (intermittent demand forecasting; the use of two-stage models was not checked in the text),
  [Altinişik et al., Scientific Reports 2026](https://www.nature.com/articles/s41598-026-58719-0)
  (photovoltaic data with an excess of structural zeros).
- **Conformal prediction and quantile regression** for intervals in markets with a high renewable share —
  [arXiv:2502.04935](https://arxiv.org/abs/2502.04935).

## Tested hypotheses

The hypotheses are predictive: each one states that a group of variables reduces the forecast error, not
that it causes curtailment.

| # | hypothesis | origin | implementation |
|---|---|---|---|
| H1 | the MMGD share of forecast load improves the forecast of energy-balance curtailment | Vieira et al. | `lit_sin_mmgd_share` |
| H2 | forecast renewables and NE net load improve the forecast of reliability and export curtailment | Vieira et al.; Volt | `lit_ne_vre_forecast`, `lit_ne_net_load_forecast`, `lit_se_net_load_forecast` |
| H3 | interchange between regions and hydrology improve the forecast | Titz et al. | `lag1d_flow_*`, `lag1d_*_ena_pct_mlt`, `lag1d_*_ear_pct` |
| H4 | daily net load shape (trough, ramp) and the whole-day plan improve the forecast | CAISO; Volt | `lit_sin_net_load_daymin`, `_above_daymin`, `_ramp_1h`, `plan_day_*` |
| H5 | zero-inflated target → two-stage model | hurdle | config `hurdle` |
| H6 | regime changes over time → recency weighting / monthly retraining reduce the error | structural break (Vieira et al.) | configs `recency`, `walk` |
| H7 | archived weather forecast reduces the error, especially without the ONS plan | Acun et al. (GFS); CAISO | configs `*_wx`, `d2_*` |
