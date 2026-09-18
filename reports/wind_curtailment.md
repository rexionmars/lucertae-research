# Wind generation curtailment

Data: ONS `restricao_coff_eolica_usi` (Apr 2024–Aug 2026), loaded into `br.wind_curtail` and
cleaned in `clean.wind_curtail`, with the same rules as for solar (curtailment only when there is a recorded reason and a
valid reference). 178 clusters, 6.59M intervals of 30 min.

**Curtailed share (%)** = curtailed energy / (generated energy + curtailed energy), that is, the fraction of possible
generation that was not generated. The same definition applies to the solar figures cited here.

## Magnitude

| year | generation | curtailed | curtailed share (%) |
|---|---|---|---|
| 2024 (Apr–Dec) | 86.3 TWh | 9.2 TWh | 9.6% |
| 2025 | 111.1 TWh | 26.2 TWh | **19.1%** |
| 2026 (Jan–Aug) | 66.8 TWh | 16.2 TWh | 19.5% |

**In volume, wind curtailment is larger than solar curtailment:** 51.6 TWh over the period, versus 22.2 TWh for solar.
As a percentage it is smaller (19% versus 26% in 2025); wind generation over the period is larger than solar generation.

## Reasons

| reason | origin | curtailed |
|---|---|---|
| ENE (energy balance) | systemic | 25.8 TWh |
| CNF (electrical reliability) | local | 11.1 TWh |
| CNF | systemic | 8.2 TWh |
| REL (external unavailability) | systemic | 5.5 TWh |
| REL | local | 0.9 TWh |

Curtailment of **local** origin is larger for wind (12.0 TWh) than for solar (2.0 TWh). This result is
consistent with the concentration of wind farms in the Northeast (164 of 178 clusters) and with the transmission
saturation in the region reported by Canal Solar (`reports/literature_curtailment.md`); the relationship was not
tested here.

## Where and when

- **Northeast: 164 clusters, 50.4 TWh curtailed, 17.1% curtailed share.** South: 5.9%. North: 8.1%.
- **Day of week:** 14–15% on weekdays, 17.7% on Saturday and **24.1% on Sunday**. Solar follows the same
  order, at a higher level: 17–18% on weekdays, 26.9% on Saturday and 43.9% on Sunday.
- **Hour of day: the wind curtailed share is highest between 10:00 and 12:00 (41–42%)**, versus 5–7% overnight.
  The solar one is highest between 9:00 and 11:00 (29–31%).

**Wind curtailment is concentrated in the same hours as solar curtailment**, when solar generation is highest. This
result is consistent with a common cause, low net load in the middle of the day, but the association
was not tested as causal. Two hypotheses follow from it and were not tested: that variables for one type of
curtailment improve the forecast of the other, and that flexibility measures (storage, load
shifting) reduce both.

## Models

Same configurations as for solar (`reports/experiments_curtailment.md`), with forecast wind in place
of irradiance in the cluster variables. Results in section 5 of that report.
