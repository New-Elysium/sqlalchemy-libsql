from sqlalchemy.dialects import registry as _registry

from .aiolibsql import SQLiteDialect_aiolibsql
from .libsql import SQLiteDialect_libsql

__all__ = ["SQLiteDialect_aiolibsql", "SQLiteDialect_libsql"]

__version__ = "0.1.0-pre"

_registry.register("sqlite.libsql", "sqlalchemy_libsql.libsql", "SQLiteDialect_libsql")
_registry.register(
    "sqlite.aiolibsql", "sqlalchemy_libsql.aiolibsql", "SQLiteDialect_aiolibsql"
)
