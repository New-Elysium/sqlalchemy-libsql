import libsql
import pytest
from sqlalchemy_libsql.libsql import SQLiteDialect_libsql

needs_exception_hierarchy = pytest.mark.skipif(
    not hasattr(libsql, "OperationalError"),
    reason="installed libsql predates the DB-API exception hierarchy",
)


@needs_exception_hierarchy
@pytest.mark.parametrize(
    "message",
    [
        "Hrana: `stream error: 404 stream not found: abc123`",
        "Hrana: `stream expired`",
        "connection closed",
    ],
)
def test_hrana_stream_errors_are_disconnects(message):
    dialect = SQLiteDialect_libsql(dbapi=libsql)
    assert dialect.is_disconnect(libsql.OperationalError(message), None, None)


@needs_exception_hierarchy
def test_ordinary_errors_are_not_disconnects():
    dialect = SQLiteDialect_libsql(dbapi=libsql)
    assert not dialect.is_disconnect(
        libsql.OperationalError("no such table: users"), None, None
    )
    assert not dialect.is_disconnect(
        libsql.IntegrityError("UNIQUE constraint failed"), None, None
    )
