# CLAUDE.md — sqlalchemy-libsql

SQLAlchemy 2.x dialect for [libSQL](https://turso.tech/libsql) / Turso, built on top of the `libsql` Python driver (repo: `libsql-python`; depends on the PyPI `libsql>=0.1.11` package, tests also pass against a local `maturin develop` build). Published to PyPI as **`sqlalchemy-libsql`**. Supports Linux and macOS only (per README).

## Layout

- `sqlalchemy_libsql/__init__.py` — registers dialects with SQLAlchemy's registry (`sqlite.libsql`, `sqlite.aiolibsql`). Contains a stale `__version__ = "0.1.0-pre"` (real version is in `pyproject.toml`, currently 0.2.0).
- `sqlalchemy_libsql/libsql.py` — `SQLiteDialect_libsql`, subclass of SQLAlchemy's `SQLiteDialect_pysqlite`, plus `_build_connection_url`.
- `sqlalchemy_libsql/aiolibsql.py` — `SQLiteDialect_aiolibsql` plus an asyncio adaptation layer (`_AsyncConnection`/`_AsyncCursor` facades, `AsyncAdapt_libsql_*` built on SQLAlchemy's `sqlalchemy.connectors.asyncio` classes, `AsyncAdapt_libsql_dbapi`).
- `tests/test_basic.py` (sync) and `tests/test_async.py` (async, `pytest-asyncio`) — fixtures parametrized over `memory`, `file`, `remote`, `embedded`.
- `pyproject.toml` — packaging (setuptools-style `[project]`, built with `uv build`), entry points `sqlite.libsql` / `sqlite.aiolibsql` under `sqlalchemy.dialects`. `uv.lock` (refresh with `uv lock --upgrade`; it forks per Python version), `flake.nix`, `.envrc` (direnv + nix) for dev env.
- `.github/workflows/test.yml` (pytest matrix; on Linux installs `sqld` to `~/.sqld` via `CARGO_DIST_FORCE_INSTALL_DIR`, since the installer defaults to `~/.cargo/bin`, and runs it on :8080), `publish.yml` (trusted publishing to PyPI on GitHub release). Keep action versions current (`checkout@v6`, `setup-python@v6`, `setup-uv@v6`).

## Commands

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
# (plain `uv sync` does not install the project — no [build-system] — so the dialect entry points would be missing)
pytest tests/                # memory + file cases always run
pytest --cov=sqlalchemy_libsql tests/   # what CI runs
```

Remote/embedded cases only use the real server when `TURSO_DATABASE_URL` is set (e.g. `localhost:8080` with `sqld` running, `TURSO_AUTH_TOKEN=""`); otherwise those fixture params silently fall back to an in-memory engine, so a green run without the env vars does NOT exercise remote/embedded paths. Tests create `test.db` / `test_embedded.db` in the cwd (gitignored).

Requires **Python ≥3.10** (project minimum; CI tests 3.10–3.14 on Linux and 3.12 on macOS/Windows; `.python-version` is 3.12). Don't use 3.12-only syntax (e.g. nested same-quote f-strings) in code, tests or README.

## How the dialect works

- URLs: `sqlite+libsql://` (in-memory), `sqlite+libsql:///file.db` (local, made absolute via `os.path.abspath`), `sqlite+libsql://host:port/?secure=true` (remote; `secure` → https, otherwise http), and an embedded replica via `connect_args={"sync_url": ..., "auth_token": ...}` on a local file URL. Async: `sqlite+aiolibsql://` with `create_async_engine(..., poolclass=AsyncAdaptedQueuePool)` (tests pass the pool class explicitly).
- `import_dbapi()` returns the `libsql` module. `on_connect()` wraps pysqlite's hook and **skips it for libsql `Connection`s** because libsql has no `create_function()`.
- `create_connect_args()` starts from pysqlite's logic: coerces known query args (`uri, timeout, isolation_level, detect_types, check_same_thread, cached_statements, secure`), forces `uri=True` when a host is present, builds the connect URL via `_build_connection_url`, and sets `check_same_thread` default to `not self._is_url_file_db(url)`. Remaining query params become URI options (sorted for deterministic unit tests). `secure` is a libsql-only extra.
- `supports_statement_cache` must be set explicitly on each dialect subclass (SQLAlchemy requirement) — both classes copy it from the parent.
- `aiolibsql`: the `libsql` driver is synchronous, so `import_dbapi()` returns `AsyncAdapt_libsql_dbapi`, whose `connect()` wraps the sync connection in awaitable facades and SQLAlchemy's `AsyncAdapt_dbapi_connection/cursor`. Calls run directly on the event loop (not offloaded to a thread) — they block it. `get_pool_class` returns `AsyncAdaptedQueuePool` for files/remote hosts and `StaticPool` for plain in-memory. Requires SQLAlchemy ≥ 2.0.44 (`_async_soft_close`).
- `create_connect_args()` renames `check_same_thread`/`uri` to `_check_same_thread`/`_uri` and drops `detect_types`/`cached_statements`, because `libsql.connect()` rejects the un-prefixed/unsupported sqlite3 kwargs.
- **Hrana/dead connections:** `is_disconnect` treats `OperationalError`/`ProgrammingError` messages such as `stream not found`/`stream expired`/`connection closed` as disconnects so the pool invalidates the connection (use with `pool_pre_ping=True` and `pool_recycle` on Turso). This needs a libsql driver with the DB-API exception hierarchy (post-0.1.11, i.e. libsql-python on this branch); with older drivers errors are bare `ValueError`s that SQLAlchemy never classifies, and the hook is inert (tests in `tests/test_disconnect.py` skip).
- Because the driver is `libsql` (not `sqlite3`), driver quirks leak through: with PyPI libsql ≤0.1.11, driver errors are bare `ValueError`s and `Connection.isolation_level` is read-only (so `execution_options(isolation_level="AUTOCOMMIT")` raises AttributeError; `tests/test_isolation.py` skips). Parameters are positional/qmark only, and unsupported pysqlite features (e.g. user-defined functions) are skipped.
- Tests: the async `remote` fixture mirrors the recommended Turso setup (`?secure=...`, `AsyncAdaptedQueuePool`, `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True`, `pool_recycle=300`). `TURSO_SECURE` defaults to `true`; CI sets it to `false` for plain-HTTP local sqld. `test_pool_pre_ping_replaces_dead_connection` simulates a dead pooled connection.

## Conventions / gotchas

- Lint: `ruff check .`, `ruff format --check .`, `ty check .` must be clean (CI `lint` job; tools are in the `dev` extra; config in `pyproject.toml`). `[tool.ty.analysis] replace-imports-with-any = ["libsql"]` exists only because PyPI libsql ≤0.1.11 has no stubs; remove it once the libsql floor ships `libsql.pyi`.
- Dialect behavior should stay a minimal layer over `SQLiteDialect_pysqlite`; prefer overriding only what libsql needs and comment why (existing comments document the reasons).
- Changes to driver semantics belong in `libsql-python`; if a fix there is required, coordinate both repos (both use branch `claude/vibrant-dijkstra-l2vbig` in this session).
- Keep entry points in `pyproject.toml` and registry calls in `__init__.py` in sync when adding dialects.
- When bumping the version, update `pyproject.toml` (and ideally the stale `__version__`).
- Repo URLs in `pyproject.toml`/README point to `tursodatabase/libsql-sqlalchemy` / `libsql-experimental-python`; the git remote here is `new-elysium/sqlalchemy-libsql`.
- Don't commit `*.db`, `.direnv`, `dist/`, `htmlcov/`, `.coverage`.
- Pre-commit: `.pre-commit-config.yaml` runs ruff and ty (`pip install pre-commit && pre-commit install`).
