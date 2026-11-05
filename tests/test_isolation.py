import libsql
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine


def _driver_isolation_level_writable():
    conn = libsql.connect(":memory:")
    try:
        conn.isolation_level = None
        return True
    except AttributeError:
        return False
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _driver_isolation_level_writable(),
    reason="installed libsql has a read-only Connection.isolation_level",
)


def test_autocommit_isolation_level(tmp_path):
    engine = create_engine(f"sqlite+libsql:///{tmp_path / 'iso.db'}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t(x)"))
        conn.commit()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert conn.connection.driver_connection.isolation_level is None
        conn.execute(text("INSERT INTO t VALUES (1)"))
        conn.rollback()  # no-op: the insert was autocommitted
    with engine.connect() as conn:
        # The pooled connection is reset to the default level on return.
        assert conn.connection.driver_connection.isolation_level is not None
        assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_async_autocommit_isolation_level(tmp_path):
    engine = create_async_engine(f"sqlite+aiolibsql:///{tmp_path / 'iso.db'}")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("CREATE TABLE t(x)"))
            await conn.commit()
        async with engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("INSERT INTO t VALUES (1)"))
            await conn.rollback()
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM t"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()
