"""DuckDB connection and SQL-file runner."""

from pathlib import Path

import duckdb

from carbon_forecast.config import SQL_DIR


def connect(path: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    # Naive TIMESTAMPs hold UTC; pin the session zone so nothing shifts them.
    con.execute("SET TimeZone = 'UTC'")
    return con


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text())


def run_sql_files(con: duckdb.DuckDBPyConnection, sql_dir: Path = SQL_DIR) -> list[Path]:
    """Run every `NN_*.sql` file in lexical order; returns the files run."""
    files = sorted(sql_dir.glob("[0-9][0-9]_*.sql"))
    for path in files:
        run_sql_file(con, path)
    return files


def init_raw_schema(con: duckdb.DuckDBPyConnection) -> None:
    run_sql_file(con, SQL_DIR / "00_raw_schema.sql")
