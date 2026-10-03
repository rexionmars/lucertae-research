"""Repository paths, defined once for every experiment.

The root is anchored on this package and checked against a marker that only
exists at the repository root. Deriving it per script with `parents[N]` fails
silently when N is wrong: the path points above the repository, `glob` returns
an empty list, and no exception is raised.

Run from the repository root. Large intermediates go to `data/interim/`,
which the `LUCERTAE_INTERIM` environment variable overrides.
"""
import os
from pathlib import Path

PROJECT_NAME = "lucertae-research"

# src/lucertae/paths.py -> src/lucertae -> src -> repository root
ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORT_DIR = ROOT / "report"
SQL_DIR = ROOT / "sql"


class RepositoryRootError(RuntimeError):
    """The root derived from the package location is not the repository root."""


def interim_dir() -> Path:
    """Directory for intermediates; `LUCERTAE_INTERIM` takes precedence."""
    return Path(os.environ.get("LUCERTAE_INTERIM", ROOT / "data" / "interim"))


def output_dir(name: str) -> Path:
    """Output directory of one experiment, created if it does not exist."""
    directory = interim_dir() / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def check_root() -> None:
    """Raise `RepositoryRootError` if `ROOT` is not the repository root.

    The `pyproject.toml` carrying the project name only exists at the root.
    Without this check, a package installed outside the tree would point to a
    `data/raw` that does not exist, and the failure would surface later and
    elsewhere as "no files found".
    """
    pyproject = ROOT / "pyproject.toml"
    marker = f'name = "{PROJECT_NAME}"'
    if not pyproject.exists() or marker not in pyproject.read_text():
        raise RepositoryRootError(
            f"repository root mismatch: {ROOT} does not hold the "
            f"{PROJECT_NAME} pyproject.toml")
