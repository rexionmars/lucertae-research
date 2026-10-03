"""Connection to the local PostGIS (terra_br database).

External dependency: a PostgreSQL server with PostGIS, reached through DATABASE_URL or the
PG* environment variables.
"""

import os
from functools import cache

import pandas as pd
from sqlalchemy import Engine, create_engine, text


@cache
def engine() -> Engine:
    """SQLAlchemy engine. Uses DATABASE_URL, or the PG* variables with local defaults."""
    url = os.environ.get("DATABASE_URL")
    if url is None:
        host = os.environ.get("PGHOST", "localhost")
        port = os.environ.get("PGPORT", "5432")
        user = os.environ.get("PGUSER", os.environ.get("USER", "postgres"))
        database = os.environ.get("PGDATABASE", "terra_br")
        url = f"postgresql+psycopg://{user}@{host}:{port}/{database}"
    return create_engine(url)


def query(sql: str, **params) -> pd.DataFrame:
    """Run `sql` with the named parameters bound and return the rows as a DataFrame."""
    with engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
