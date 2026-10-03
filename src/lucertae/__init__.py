"""lucertae: what the experiments in this repository share.

    sources      ONS readers, one source per series; database loaders
    gate         measured publication lag, and the gate derived from it
    evaluation   loss, skill and block-bootstrap confidence interval
    registry     result schema and adapters that read each artifact
    paths        root, data/raw, data/interim with LUCERTAE_INTERIM
    viz          figure style for the notebooks

Command line in `lucertae.cli`. Run from the repository root.
"""
# `cli`, `viz` and the database modules stay OUT of this import. Importing
# `cli` here and then running `python -m lucertae.cli` would execute the
# module twice; the entry point targets `lucertae.cli:main` directly. `viz`
# loads matplotlib, and `sources.db` needs the database driver.
from . import evaluation, gate, paths, registry, sources

__all__ = ["evaluation", "gate", "paths", "registry", "sources"]
