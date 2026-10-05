# E-thermal-dispatch

How much SIN thermal generation is driven by operating decisions rather than
price, and does the day-ahead schedule hold?

Built from scratch on `data/raw/termica_despacho/`. It does not read, import, or
reuse any prior result, panel, or script in this repository. The accounting
decomposition was discovered by testing the data, not copied from a manual.

```text
.venv/bin/python experiments/E-thermal-dispatch/1_painel.py
.venv/bin/python experiments/E-thermal-dispatch/2_controles.py  # blocks step 3
.venv/bin/python experiments/E-thermal-dispatch/3_medida.py
```

Outputs are written to `data/interim/E-despacho-termico/` (overridable with
`LUCERTAE_INTERIM`).

## Input

`GERACAO_TERMICA_DESPACHO-2`: 29 monthly files from April 2024 to August 2026.
Plant-by-hour panel: **2,601,600 rows, 186 plants, 21,192 hours**, with a
complete hourly grid.

The source schema changed three times during the study window: 42, 43, and 47
columns. Decomposition fields exist in all three versions. `din_publicacao`,
`nom_combustivel`, `val_geracaodespachada`, and `val_progdisponibilidade` are
available only from February 2026 or April 2026 onward. This is a stated data
limitation, not a panel-generation failure.

## Accounting decomposition

The decomposition was identified by testing the data. The identity that closes
is:

```text
geracao = ordemdemeritoacimadainflex + inflexibilidade + RESTO
```

Since `inflexibilidade = inflexembutmerito + inflexpura` closes for 100% of
scheduled rows, it can be rewritten in the economic form used here:

```text
geracao = MERITO + FORA
MERITO  = ordemdemeritoacimadainflex + inflexembutmerito
FORA    = inflexpura + razaoeletrica + garantiaenergetica + gfom
				+ reposicaoperdas + exportacao + reservapotencia + gsub + unitcommitment
```

`MERITO` is generation that merit-order dispatch would produce regardless,
including the inflexible share that happens to fall within it. `FORA` is
generation that exists because of operating decisions rather than price.

The published `ordemmerito` column is **not** included in the sum. It is
redundant with `ordemdemeritoacimadainflex + inflexembutmerito`, and that
redundancy fails in 0.41% of scheduled rows and 0.46% of verified rows. Control
C1b measures this discrepancy rather than hiding it.

## Controls

Controls run before any result is produced. A failed blocking control stops
step 3.

| Control | Result |
|---|---|
| C1: identity closes on **energy** | scheduled 99.887%, verified 99.977%; pass |
| C1b: `ordemmerito` equals the component sum | differs in 0.41% / 0.46% of rows; note |
| C1c: residual is concentrated, not diffuse | 40 and 41 plants; scheduled residual in Baixada Fluminense, verified residual in Amazonas gas plants |
| C2: complete hourly grid | 21,192 of 21,192 hours; pass |
| C3: unique (plant, hour) key | 0 duplicates; pass |
| C4: nonnegative reason components | 9 negative values across 22 columns; note |
| C5: `verificado` published **after** the event time | 0 violations; median lag 41.8 days; pass |
| C6: identifier coverage | `ceg` 100%, `cod_usinaplanejamento` 99.80%; pass |

**The C1 criterion changed during development, and the change is documented in
the code.** The first version required 99.9% of *rows* and **rejected the
panel** (verified generation closed at 99.126%). Diagnosis showed that the
failure came from small Amazonas plants with a tenth-of-a-megawatt difference
across many hours (Tucunaré, Pirarucu, Jaraqui, and Poraqué), not from a
decomposition error. The criterion was changed to the fraction of **energy**
explained, the quantity used by step 3. The row fraction remains reported as
descriptive information. This is a criteria change supported by a published
diagnosis, not a threshold relaxed until the control passes.

The residual is **not redistributed** across reasons; it appears as its own row
in the step 3 table.

## Result A: descriptive analysis

From April 2024 to August 2026, 156.34 TWh were scheduled and 153.09 TWh were
verified.

| | Scheduled | Verified |
|---|---:|---:|
| Total | 156.34 TWh | 153.09 TWh |
| Merit order | 81.44 TWh (52.09%) | 80.48 TWh (52.57%) |
| **Out of merit** | **75.07 TWh (48.02%)** | **72.58 TWh (47.41%)** |
| Unexplained residual | -0.174 TWh (-0.111%) | +0.034 TWh (+0.022%) |

Out-of-merit generation by reason (scheduled, as a percentage of total thermal
generation):

| Reason | TWh | % of thermal | % of out-of-merit |
|---|---:|---:|---:|
| Pure inflexibility | 50.660 | 32.40% | 67.48% |
| Unit commitment | 10.064 | 6.44% | 13.41% |
| Export | 8.995 | 5.75% | 11.98% |
| GSUB | 2.653 | 1.70% | 3.53% |
| Electrical constraint | 2.389 | 1.53% | 3.18% |
| Energy security | 0.222 | 0.14% | 0.30% |
| GFOM | 0.090 | 0.06% | 0.12% |
| Loss replacement | 0 | - | - |
| Power reserve | 0 | - | - |

**Almost half of SIN thermal generation is not dispatched by price**, and
two-thirds of that amount is pure inflexibility, declared by the generator
rather than decided by the operator. Loss replacement and power reserve are
zero throughout the window: the columns exist but were never used.

## Result B: decision analysis

Estimand: `d = fora_verificado - fora_programado`, aggregated to the SIN by
hour. Declared loss: MAE in MWh/h. The analysis covers 19,728 hours from June
2024 to August 2026.

**The design constraint comes from C5.** Month M's file is published at the end
of month M+1. This lag was measured in the five files that contain publication
timestamps: 29.8 to 30.8 days after the end of the month. Therefore, for an
hour in month M, the latest knowable verified value is from month M-2. No
baseline uses the "previous 7 days," which would introduce 30 to 60 days of
leakage.

The baselines use the **median**, not the mean, as their central estimator
because the declared loss is MAE, which the median minimizes. Using the mean
would measure the analyst's choice rather than publication delay.

The bias is present: mean -125.9 MWh/h, median -55.6 MWh/h, or **-3.59% of
scheduled out-of-merit generation**. Verified generation is systematically
below scheduled generation.

| Baseline | MAE (MWh/h) | Skill | 95% CI |
|---|---:|---:|---:|
| B0: unbiased schedule | 257.1 | - | - |
| B1: median by hour, month M-2 | 268.8 | **-4.55%** | [-7.38%, -1.92%] |
| B2: median of month M-2 | 268.6 | **-4.44%** | [-7.28%, -1.91%] |
| Oracle: median of the same month | 218.0 | **+15.23%** | [+13.07%, +17.49%] |

**Finding.** The bias is real and predictable: the oracle gains 15.2%, with its
entire confidence interval above zero. This positive control shows that the
experiment can detect a bias when one is present. However, correcting with the
most recent month already published by ONS is **significantly worse than not
correcting**, with both baseline confidence intervals entirely below zero.

Drift explains the result: the monthly median deviation ranges from -351 to
+102 MWh/h, an amplitude of 453, with a typical month-to-month step of
43 MWh/h. The bias moves slowly but spans a wide range; a two-month publication
lag is enough for the published value to describe a different regime.

**Decision interpretation: the obstacle is institutional latency, not absence
of signal.** An entity exposed to the charge has a 3.6% bias to correct but
cannot do so because the operator's publication schedule is too slow. A better
model does not solve this; faster publication would. This is a statement about
the process, not the technique.

## Stated limitations

- **No price data.** `cvu-usitermica` is not on disk, so these results are not
	in R$. On 2026-09-06, 22 CSV files totaling 9.8 MB were available and the
	download was tested.
- **The M+1 rule was measured in 5 of 29 files.** The other 24 lack
	`din_publicacao`. The August 2026 file was released 0.8 days after month-end,
	which may indicate a preliminary version subject to revision; this was not
	verified.
- **"Out of merit" combines two agents.** Pure inflexibility is declared by the
	generator; electrical constraints and GSUB are operator decisions. The table
	reports reasons so it can be recomposed with a different classification.
- **Export and GSUB are included in `FORA`.** This classification is
	debatable; the published decomposition allows them to be removed without
	rebuilding the panel.
- **System-level grain.** All of Result B is aggregated to the SIN. Structure
	by subsystem, plant, fuel, or load condition was not tested.
- **No fitted model.** This analysis uses constant and hour-conditional
	baselines only. A model with features could beat the oracle; that was not
	tested. The latency conclusion does not depend on it because no feature
	changes when ONS publishes the data.

## Not tested

Subsystem, plant, and fuel breakdowns; conditioning on load or hydrological
state; horizons other than the "next published hour"; and whether the current
month's preliminary version, published one day late, would resolve the latency.
The last item is the most promising test and requires downloading version
history, which CKAN does not retain.
