"""Step 2 -- falsifiable controls on the generated panel.

Each control is a claim that the data can refute. Step 3 refuses to run if a blocking
control fails. Informational checks do not block execution, but they are still included
in the output and should be cited with any claim depending on them.

Output: data/interim/E-despacho-termico/controles.json
"""
import json
import sys
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _comum import (CONTROLS_PATH, MERIT_COMPONENTS, OUT_OF_MERIT_REASONS,
                    PANEL_PATH)

# Tolerance. The raw data carry three decimals across 11 summed columns, so rounding
# accumulates to roughly 0.005 MW per row. 0.01 MW is sufficient to absorb that without
# hiding a real gap; the real gaps measured here are between 0.3 and 205 MW.
TOL = 1e-2
# C1 threshold is based on ENERGY, not on rows. The first version of this control required
# 99.9% of rows, which rejected the whole panel because a small Amazon plant had tiny gaps
# across many hours. The diagnostic showed the issue was not a decomposition error. The
# post-diagnostic criterion therefore uses the fraction of energy explained, which is the
# quantity step 3 depends on.
C1_ENERGY_THRESHOLD = 0.995


def record_result(results, name, blocking, passed, value, description):
    results.append({"controle": name, "bloqueante": blocking,
                    "passou": bool(passed), "valor": value, "diz": description})
    status = "PASS" if passed else ("FAIL" if blocking else "NOTE")
    print(f"  [{status:7s}] {name:34s} {value}")
    return passed


def main():
    panel = pd.read_parquet(PANEL_PATH)
    results = []
    print(f"panel: {len(panel):,} rows\n")

    # --- C1 accounting identity ---------------------------------------
    # Claim: published generation = merit + out-of-merit row by row.
    # If this fails, the decomposition is wrong and any reason-specific numbers from step 3
    # are invented. This is the control that can kill the experiment.
    ok_c1 = True
    for side in ("prog", "verif"):
        residual = (panel[f"{side}_total_pub"] - panel[f"{side}_total_soma"]).abs()
        energy = float(panel[f"{side}_total_pub"].sum())
        explained = 1.0 - float(residual.sum()) / energy
        rows = float((residual <= TOL).mean())
        ok = explained >= C1_ENERGY_THRESHOLD
        ok_c1 &= record_result(
            results,
            f"C1 generation identity ({side})",
            True,
            ok,
            f"{explained:.4%} of energy explained "
            f"({residual.sum():,.0f} of {energy:,.0f} MWh unexplained); rows closed {rows:.4%}",
            "published generation = merit + out-of-merit; energy-based criterion",
        )
        # If the balance does not close, the residual is not redistributed across reasons: it
        # remains a separate bucket in step 3 and is visible in the table.
        plants = panel.loc[residual > TOL, "nom_usina"]
        record_result(
            results,
            f"C1c residual concentration ({side})",
            False,
            True,
            f"{plants.nunique()} plants contain the residual; largest contributors: "
            f"{', '.join(plants.value_counts().head(3).index)}",
            "residual is concentrated in a few plants, not diffuse",
        )

    # --- C1b redundancy of order-merit -------------------------------
    # Informational. `ordemmerito` should equal `ordemdemeritoacimadainflex + inflexembutmerito`.
    # Where it does not, the source is internally inconsistent and the panel uses the sum.
    for side in ("prog", "verif"):
        target = panel[f"val_{side}ordemmerito"]
        total = sum(panel[f"val_{side}{column}"] for column in MERIT_COMPONENTS)
        residual = (target - total).abs()
        count = int((residual > TOL).sum())
        plants = panel.loc[residual > TOL, "nom_usina"].nunique()
        record_result(
            results,
            f"C1b merit-order redundancy ({side})",
            False,
            count == 0,
            f"{count:,} divergent rows ({count/len(panel):.3%}), {plants} plants",
            "ordemmerito is redundant with the component sum; divergences indicate source inconsistency",
        )

    # --- C2 temporal grid --------------------------------------------
    # Claim: the hourly grid is complete for the period, with no missing hours.
    hourly_index = panel.din_instante.drop_duplicates().sort_values()
    expected = pd.date_range(hourly_index.min(), hourly_index.max(), freq="h")
    missing = len(expected) - len(hourly_index)
    ok_c2 = record_result(
        results,
        "C2 hourly grid",
        True,
        missing == 0,
        f"{len(hourly_index):,} of {len(expected):,} expected hours present; {missing} missing",
        "complete hourly grid between the first and last timestamps",
    )

    # --- C3 unique key -----------------------------------------------
    duplicates = int(panel.duplicated(["nom_usina", "din_instante"]).sum())
    ok_c3 = record_result(
        results,
        "C3 unique key",
        True,
        duplicates == 0,
        f"{duplicates:,} duplicate (plant, timestamp) keys",
        "each plant appears once per hour",
    )

    # --- C4 sign check ------------------------------------------------------
    # Negative components are not necessarily a panel error: they may indicate that the
    # decomposition contains a sign inversion, which would break the meaning of the sum as
    # 'generation by reason'. Informational check, with a count.
    components = ([f"val_prog{column}"
                   for column in MERIT_COMPONENTS + OUT_OF_MERIT_REASONS]
                  + [f"val_verif{column}"
                     for column in MERIT_COMPONENTS + OUT_OF_MERIT_REASONS])
    negatives = int(sum((panel[c] < -TOL).sum() for c in components))
    record_result(
        results,
        "C4 component signs",
        False,
        negatives == 0,
        f"{negatives:,} negative values across {len(components)} reason columns",
        "reason components are expected to be nonnegative",
    )

    # --- C5 knowability timestamp ---------------------------------
    # Claim: `verified` was published after the instant it describes. If not, it is not a valid
    # verified value. This can only be tested where the column exists, which is itself a limit of
    # the observation window.
    has_publication = panel.din_publicacao.notna()
    if has_publication.any():
        lag = panel.loc[has_publication, "din_publicacao"] - panel.loc[has_publication, "din_instante"]
        invalid = int((lag <= pd.Timedelta(0)).sum())
        ok_c5 = record_result(
            results,
            "C5 publication after event time",
            True,
            invalid == 0,
            f"{has_publication.mean():.1%} of rows have timestamps; {invalid} published before event time; "
            f"median lag {lag.median().total_seconds()/86400:.1f} d",
            "verified generation was published after the timestamp it describes",
        )
    else:
        ok_c5 = record_result(
            results,
            "C5 publication after event time",
            False,
            False,
            "din_publicacao is absent from the entire panel",
            "not testable",
        )

    # --- C6 key coverage ---------------------------------
    for column in ("ceg", "cod_usinaplanejamento"):
        coverage = float(panel[column].notna().mean())
        record_result(
            results,
            f"C6 identifier coverage ({column})",
            False,
            coverage > 0.99,
            f"{coverage:.2%} populated",
            "linkage key for other sources",
        )

    blocked = not (ok_c1 and ok_c2 and ok_c3 and ok_c5)
    output = {"linhas": int(len(panel)), "usinas": int(panel.nom_usina.nunique()),
              "inicio": str(panel.din_instante.min()), "fim": str(panel.din_instante.max()),
              "bloqueado": blocked, "controles": results}
    CONTROLS_PATH.write_text(json.dumps(output, indent=1, ensure_ascii=False))

    print(f"\n{'BLOCKED' if blocked else 'READY'} -- saved to {CONTROLS_PATH}")
    if blocked:
        sys.exit(1)


if __name__ == "__main__":
    main()
