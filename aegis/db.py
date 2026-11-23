import atexit
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from aegis.config import DATABASE_URL

_pools = {}
_lock = Lock()


def close_pools():
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


atexit.register(close_pools)


@contextmanager
def connection(url=None):
    target = url or DATABASE_URL
    with _lock:
        pool = _pools.get(target)
        if pool is None:
            pool = ConnectionPool(
                target,
                kwargs={"row_factory": dict_row, "connect_timeout": 5},
                min_size=1,
                max_size=16,
                timeout=5,
                name="aegis-db",
                open=True,
            )
            _pools[target] = pool
    with pool.connection() as conn:
        yield conn


def migrate():
    with connection() as conn:
        conn.execute(Path("infra/postgres/001_core.sql").read_text())


if __name__ == "__main__":
    migrate()
