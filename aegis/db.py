from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from aegis.config import DATABASE_URL


@contextmanager
def connection(url=None):
    with psycopg.connect(url or DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def migrate():
    with connection() as conn:
        conn.execute(Path("infra/postgres/001_core.sql").read_text())


if __name__ == "__main__":
    migrate()
