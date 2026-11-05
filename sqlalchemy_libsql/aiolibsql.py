"""Asyncio flavour of the libSQL dialect.

The ``libsql`` driver is synchronous, so SQLAlchemy's asyncio extension needs
an adaptation layer in between.  The classes below expose the sync driver
through an awaitable (DBAPI-over-asyncio style) interface and then reuse
SQLAlchemy's own ``AsyncAdapt_dbapi_*`` classes for the greenlet bridge.

Note that the underlying calls are *not* offloaded to a thread: they run
directly on the event loop, so a slow remote query blocks the loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import pool
from sqlalchemy.connectors.asyncio import (
    AsyncAdapt_dbapi_connection,
    AsyncAdapt_dbapi_cursor,
    AsyncAdapt_dbapi_module,
)

from sqlalchemy_libsql.libsql import SQLiteDialect_libsql

if TYPE_CHECKING:
    from sqlalchemy.connectors.asyncio import AsyncIODBAPIConnection
    from typing_extensions import Self


class _AsyncCursor:
    """Awaitable facade over a ``libsql.Cursor``."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._cursor.close()

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def arraysize(self) -> int:
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._cursor.arraysize = value

    async def close(self) -> None:
        self._cursor.close()

    async def execute(self, operation: Any, parameters: Any = ()) -> _AsyncCursor:
        self._cursor.execute(operation, parameters)
        return self

    async def executemany(self, operation: Any, seq_of_parameters: Any) -> _AsyncCursor:
        self._cursor.executemany(operation, list(seq_of_parameters))
        return self

    async def fetchone(self) -> Any:
        return self._cursor.fetchone()

    async def fetchmany(self, size: int | None = None) -> Any:
        return self._cursor.fetchmany(size) or []

    async def fetchall(self) -> Any:
        return self._cursor.fetchall() or []

    async def nextset(self) -> None:
        return None

    async def setinputsizes(self, sizes: Any) -> None:
        return None


class _AsyncConnection:
    """Awaitable facade over a ``libsql.Connection``."""

    def __init__(self, connection: Any):
        self._connection = connection

    @property
    def isolation_level(self) -> str | None:
        return self._connection.isolation_level

    @isolation_level.setter
    def isolation_level(self, value: str | None) -> None:
        self._connection.isolation_level = value

    def __getattr__(self, key: str) -> Any:
        # Pass through anything else (in_transaction, autocommit, ...); also
        # required by SQLAlchemy's AsyncIODBAPIConnection protocol.
        return getattr(self._connection, key)

    def cursor(self) -> _AsyncCursor:
        return _AsyncCursor(self._connection.cursor())

    async def commit(self) -> None:
        self._connection.commit()

    async def rollback(self) -> None:
        self._connection.rollback()

    async def close(self) -> None:
        self._connection.close()


class AsyncAdapt_libsql_cursor(AsyncAdapt_dbapi_cursor):
    __slots__ = ()


class AsyncAdapt_libsql_connection(AsyncAdapt_dbapi_connection):
    __slots__ = ()

    _cursor_cls = AsyncAdapt_libsql_cursor

    @property
    def isolation_level(self) -> str | None:
        return self._connection.isolation_level

    # SQLAlchemy's pysqlite set_isolation_level() assigns this attribute
    # (None for AUTOCOMMIT); needs a libsql driver where it is writable.
    @isolation_level.setter
    def isolation_level(self, value: str | None) -> None:
        self._connection.isolation_level = value


class AsyncAdapt_libsql_dbapi(AsyncAdapt_dbapi_module):
    """DBAPI module facade whose ``connect()`` returns an adapted connection."""

    def __init__(self, libsql: Any):
        # SQLAlchemy 2.1's base __init__ sets `driver`; 2.0.x's base is only a
        # typing marker without one, so set the attributes directly.
        self.driver = libsql
        self.dbapi_module = None
        self.libsql = libsql
        self.paramstyle = "qmark"

    @property
    def exceptions_module(self) -> Any:
        return self.libsql

    def __getattr__(self, key: str) -> Any:
        # Everything else (Error, sqlite_version_info, ...) comes from libsql.
        return getattr(self.libsql, key)

    def connect(self, *args: Any, **kwargs: Any) -> AsyncAdapt_libsql_connection:
        connection = _AsyncConnection(self.libsql.connect(*args, **kwargs))
        # The protocol declares a keyword-capable __setattr__, which plain
        # classes (positional-only object.__setattr__) can't satisfy.
        return AsyncAdapt_libsql_connection(
            self, cast("AsyncIODBAPIConnection", connection)
        )


class SQLiteDialect_aiolibsql(SQLiteDialect_libsql):
    driver = "aiolibsql"
    supports_statement_cache = SQLiteDialect_libsql.supports_statement_cache
    is_async = True

    @classmethod
    def import_dbapi(cls) -> Any:
        import libsql

        return AsyncAdapt_libsql_dbapi(libsql)

    def on_connect(self):
        # libsql has no create_function(), so there is nothing to set up.
        return None

    @classmethod
    def get_pool_class(cls, url):
        # Local files and remote/embedded databases can have one connection per
        # pool slot; a plain in-memory database must share a single connection.
        if url.host or cls._is_url_file_db(url):
            return pool.AsyncAdaptedQueuePool
        return pool.StaticPool

    def get_driver_connection(self, connection: Any) -> Any:
        return connection._connection._connection


dialect = SQLiteDialect_aiolibsql
