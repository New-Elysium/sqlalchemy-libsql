# CLAUDE.md — sqlalchemy-libsql

SQLAlchemy 2.x dialect for [libSQL](https://turso.tech/libsql) / Turso, built on top of the `libsql` Python driver (repo: `libsql-python`). Published to PyPI as **`sqlalchemy-libsql`**. Supports Linux and macOS only (per README).

## Layout

- `sqlalchemy_libsql/__init__.py` — registers dialects with SQLAlchemy's registry (`sqlite.libsql`, `sqlite.aiolibsql`). Contains a stale `__version__ = "0.1.0-pre"` (real version is in `pyproject.toml`, currently 0.2.0).
- `sqlalchemy_libsql/libsql.py` — `SQLiteDialect_libsql`, subclass of SQLAlchemy's `SQLiteDialect_pysqlite`, plus `_build_connection_url`.
- `sqlalchemy_libsql/aiolibsql.py` — `SQLiteDialect_aiolibsql`, a thin subclass that sets `is_async = True`.
- `tests/test_basic.py` (sync) and `tests/test_async.py` (async, `pytest-asyncio`) — fixtures parametrized over `memory`, `file`, `remote`, `embedded`.
- `pyproject.toml` — packaging (setuptools-style `[project]`, built with `uv build`), entry points `sqlite.libsql` / `sqlite.aiolibsql` under `sqlalchemy.dialects`. `uv.lock`, `flake.nix`, `.envrc` (direnv + nix) for dev env.
- `.github/workflows/test.yml` (pytest on PRs/pushes to `main`, installs `sqld` and runs it on :8080), `publish.yml` (publishes to PyPI on GitHub release).

## Commands

```bash
uv sync --extra dev          # or: python -m venv .venv && pip install -e '.[dev]'
pytest tests/                # memory + file cases always run
pytest --cov=sqlalchemy_libsql tests/   # what CI runs
```

Remote/embedded cases only use the real server when `TURSO_DATABASE_URL` is set (e.g. `localhost:8080` with `sqld` running, `TURSO_AUTH_TOKEN=""`); otherwise those fixture params silently fall back to an in-memory engine, so a green run without the env vars does NOT exercise remote/embedded paths. Tests create `test.db` / `test_embedded.db` in the cwd (gitignored).

Requires Python ≥3.8 per metadata but the tests use `match` statements and nested same-quote f-strings (`f"...{os.getenv("X")}"`, README too), so effectively **Python 3.12+** (CI and `.python-version` use 3.12).

## How the dialect works

- URLs: `sqlite+libsql://` (in-memory), `sqlite+libsql:///file.db` (local, made absolute via `os.path.abspath`), `sqlite+libsql://host:port/?secure=true` (remote; `secure` → https, otherwise http), and an embedded replica via `connect_args={"sync_url": ..., "auth_token": ...}` on a local file URL. Async: `sqlite+aiolibsql://` with `create_async_engine(..., poolclass=AsyncAdaptedQueuePool)` (tests pass the pool class explicitly).
- `import_dbapi()` returns the `libsql` module. `on_connect()` wraps pysqlite's hook and **skips it for libsql `Connection`s** because libsql has no `create_function()`.
- `create_connect_args()` copies pysqlite's logic: coerces known query args (`uri, timeout, isolation_level, detect_types, check_same_thread, cached_statements, secure`), forces `uri=True` when a host is present, builds the connect URL via `_build_connection_url`, and sets `check_same_thread` default to `not self._is_url_file_db(url)`. Remaining query params become URI options (sorted for deterministic unit tests). `secure` is a libsql-only extra.
- `supports_statement_cache` must be set explicitly on each dialect subclass (SQLAlchemy requirement) — both classes copy it from the parent.
- `aiolibsql` is only a flag-flipping subclass (`driver = "libsql"`, `is_async = True`); the `libsql` driver is synchronous, so async behavior is presumably provided by SQLAlchemy's greenlet-based adaptation (note the `greenlet` dependency; unverified). Don't expect true non-blocking IO.
- Because the driver is `libsql` (not `sqlite3`), driver quirks leak through: errors from the driver are `ValueError`, parameters are positional/qmark only, and unsupported pysqlite features (e.g. user-defined functions) are skipped.

## Conventions / gotchas

- Dialect behavior should stay a minimal layer over `SQLiteDialect_pysqlite`; prefer overriding only what libsql needs and comment why (existing comments document the reasons).
- Changes to driver semantics belong in `libsql-python`; if a fix there is required, coordinate both repos (both use branch `claude/vibrant-dijkstra-l2vbig` in this session).
- Keep entry points in `pyproject.toml` and registry calls in `__init__.py` in sync when adding dialects.
- When bumping the version, update `pyproject.toml` (and ideally the stale `__version__`).
- Repo URLs in `pyproject.toml`/README point to `tursodatabase/libsql-sqlalchemy` / `libsql-experimental-python`; the git remote here is `new-elysium/sqlalchemy-libsql`.
- Don't commit `*.db`, `.direnv`, `dist/`, `htmlcov/`, `.coverage`.
