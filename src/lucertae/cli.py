"""lucertae command line. Run from the repository root.

    lucertae table    compare the models of every experiment
    lucertae gate     repeat the publication-lag measurement of the sources
    lucertae check    package controls; exits with code 1 if any fails

`table` transcribes no number: each row comes from an artifact opened on disk,
and the `method` column says whether the loss was recomputed from the
prediction or read from a summary. `partial` means the published number of the
experiment has NO readable source on disk, which is a result about the
repository.
"""
import argparse
import sys

import pandas as pd

from .gate import check_gate, lag_table
from .paths import ROOT, RepositoryRootError, check_root
from .registry import collect, to_table, write

TABLE_COLUMNS = ["experiment", "family", "loss", "predictor", "role", "value",
                 "skill", "ci_low", "ci_high", "verdict", "method"]
# Roles shown by default; `--all` adds baseline, null and oracle.
MAIN_ROLES = ("adversary", "model")


def _status(failed: bool) -> str:
    return "FAIL" if failed else "pass"


def _table(args: argparse.Namespace) -> int:
    results, missing = collect()
    table = to_table(results)
    if not args.all:
        table = table[table["role"].isin(MAIN_ROLES)]
    with pd.option_context("display.width", 220, "display.max_rows", 200):
        print(table[TABLE_COLUMNS].to_string(index=False, na_rep="—"))
    print("\nThe losses differ in nature. Skill is only comparable within "
          "the same estimand.")
    for result in results:
        if result.note:
            print(f"\n{result.experiment}: {result.note}")
    for name, reason in missing.items():
        print(f"\n[missing] {name}: {reason}")
    if args.write:
        json_path, csv_path = write(results, missing)
        print(f"\n{json_path}\n{csv_path}")
    return 0


def _gate(args: argparse.Namespace) -> int:
    print(lag_table().to_string(index=False, na_rep="—"))
    failures = check_gate()
    for failure in failures:
        print(f"[FAIL] {failure}")
    return 1 if failures else 0


def _check(args: argparse.Namespace) -> int:
    try:
        check_root()
    except RepositoryRootError as error:
        print(f"[FAIL] {error}")
        return 1
    print(f"[pass] repository root: {ROOT}")

    failures = check_gate()
    print(f"[{_status(failures)}] gate against the measured lag")

    results, missing = collect()
    print(f"[{_status(missing)}] registry: {len(results)} experiments "
          f"collected, {len(missing)} failed")
    failures += [f"{name}: {reason}" for name, reason in missing.items()]

    for failure in failures:
        print("   ", failure)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lucertae", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    table = commands.add_parser(
        "table", help="compare the models of the experiments")
    table.add_argument("--all", action="store_true",
                       help="include baseline, null and oracle rows")
    table.add_argument("--write", action="store_true",
                       help="write registry.json and table.csv")
    table.set_defaults(handler=_table)

    gate = commands.add_parser(
        "gate", help="measured publication lag of the sources")
    gate.set_defaults(handler=_gate)

    check = commands.add_parser("check", help="package controls")
    check.set_defaults(handler=_check)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
