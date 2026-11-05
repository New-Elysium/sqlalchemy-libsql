import os
import urllib.parse

from sqlalchemy import util
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from libsql import Connection


def _build_connection_url(url, query, secure):
    # sorting of keys is for unit test support
    query_str = urllib.parse.urlencode(sorted(query.items()))

    if not url.host:
        if query_str:
            return f"{url.database}?{query_str}"
        return url.database
    elif secure:  # yes, pop to remove
        scheme = "https"
    else:
        scheme = "http"

    if url.username and url.password:
        netloc = f"{url.username}:{url.password}@{url.host}"
    elif url.username:
        netloc = f"{url.username}@{url.host}"
    else:
        netloc = url.host

    if url.port:
        netloc += f":{url.port}"

    return urllib.parse.urlunsplit(
        (
            scheme,
            netloc,
            url.database or "",
            query_str,
            "",  # fragment
        )
    )


class SQLiteDialect_libsql(SQLiteDialect_pysqlite):
    driver = "libsql"
    # need to be set explicitly
    supports_statement_cache = SQLiteDialect_pysqlite.supports_statement_cache

    @classmethod
    def import_dbapi(cls):
        import libsql

        return libsql

    # Messages that mean the connection (or the Hrana stream behind it) is gone.
    # Turso multiplexes Hrana "streams" over one socket; when the server drops
    # it (idle timeout, network blip) every stream dies with e.g.
    # `404 stream not found`, and the pooled connection must be discarded.
    _DISCONNECT_MESSAGES = (
        "stream not found",
        "stream expired",
        "stream closed",
        "connection closed",
        "connection reset",
        "connection refused",
        "broken pipe",
        "error sending request",
        "connection already closed",
        "websocket",
    )

    def is_disconnect(self, e, connection, cursor):
        # libsql versions before the DB-API exception hierarchy (<= 0.1.11)
        # raise plain ValueErrors, which SQLAlchemy never routes here.
        names = ("OperationalError", "ProgrammingError")
        types = tuple(t for t in (getattr(self.dbapi, n, None) for n in names) if t)
        if types and isinstance(e, types):
            message = str(e).lower()
            if any(m in message for m in self._DISCONNECT_MESSAGES):
                return True
        return super().is_disconnect(e, connection, cursor)

    def on_connect(self):
        import libsql

        sqlite3_connect = super().on_connect()

        def connect(conn):
            # LibSQL: there is no support for create_function()
            if isinstance(conn, Connection):
                return
            return sqlite3_connect(conn)

        return connect

    def create_connect_args(self, url):
        pysqlite_args = (
            ("uri", bool),
            ("timeout", float),
            ("isolation_level", str),
            ("detect_types", int),
            ("check_same_thread", bool),
            ("cached_statements", int),
            ("secure", bool),  # LibSQL extra, selects between ws and wss
        )
        opts = url.query
        libsql_opts = {}
        for key, type_ in pysqlite_args:
            util.coerce_kw_type(opts, key, type_, dest=libsql_opts)

        if url.host:
            libsql_opts["uri"] = True

        if libsql_opts.get("uri", False):
            uri_opts = dict(opts)
            # here, we are actually separating the parameters that go to
            # sqlite3/pysqlite vs. those that go the SQLite URI.  What if
            # two names conflict?  again, this seems to be not the case right
            # now, and in the case that new names are added to
            # either side which overlap, again the sqlite3/pysqlite parameters
            # can be passed through connect_args instead of in the URL.
            # If SQLite native URIs add a parameter like "timeout" that
            # we already have listed here for the python driver, then we need
            # to adjust for that here.
            for key, type_ in pysqlite_args:
                uri_opts.pop(key, None)

            secure = libsql_opts.pop("secure", False)
            connect_url = _build_connection_url(url, uri_opts, secure)
        else:
            connect_url = url.database or ":memory:"
            if connect_url != ":memory:":
                connect_url = os.path.abspath(connect_url)

        libsql_opts.setdefault("check_same_thread", not self._is_url_file_db(url))

        # libsql.connect() only accepts a subset of the sqlite3 keywords, and
        # spells the ones it merely tolerates with a leading underscore.
        for key in ("check_same_thread", "uri"):
            if key in libsql_opts:
                libsql_opts[f"_{key}"] = libsql_opts.pop(key)
        for key in ("detect_types", "cached_statements"):
            libsql_opts.pop(key, None)

        return ([connect_url], libsql_opts)


dialect = SQLiteDialect_libsql
