import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)


@pytest_asyncio.fixture(params=["memory", "file", "remote", "embedded"])
async def engine(request):
    import os

    match request.param:
        case "file":
            if os.path.exists("test.db"):
                os.remove("test.db")
            engine = create_async_engine(
                "sqlite+aiolibsql:///test.db",
                poolclass=AsyncAdaptedQueuePool,
            )
        case "remote" if os.getenv("TURSO_DATABASE_URL"):
            # Mirrors the recommended Turso setup: a real pool with pre-ping
            # and recycling, so dead Hrana streams ("404 stream not found")
            # are detected and replaced. TURSO_SECURE=false is only for a
            # plain-HTTP local sqld (as in CI); Turso itself needs https.
            secure = os.getenv("TURSO_SECURE", "true")
            engine = create_async_engine(
                f"sqlite+aiolibsql://{os.getenv('TURSO_DATABASE_URL').strip()}?secure={secure}",
                connect_args={"auth_token": os.getenv("TURSO_AUTH_TOKEN")},
                poolclass=AsyncAdaptedQueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        case "embedded" if os.getenv("TURSO_DATABASE_URL"):
            if os.path.exists("test_embedded.db"):
                os.remove("test_embedded.db")
            engine = create_async_engine(
                "sqlite+aiolibsql:///test_embedded.db",
                poolclass=AsyncAdaptedQueuePool,
                connect_args={
                    "auth_token": os.getenv("TURSO_AUTH_TOKEN"),
                    "sync_url": f"http://{os.getenv('TURSO_DATABASE_URL')}",
                },
            )
        case "memory" | _:
            engine = create_async_engine(
                "sqlite+aiolibsql://",
                poolclass=AsyncAdaptedQueuePool,
            )
    yield engine
    await engine.dispose()

@pytest_asyncio.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_connection(session: AsyncSession):
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_create_table(session):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    )
    assert result.scalar() == "users"


@pytest.mark.asyncio
async def test_insert_and_query(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    await session.commit()

    stmt = select(User)
    result = await session.execute(stmt)
    queried_user = result.scalars().first()
    assert queried_user.name == "Test User"
    assert queried_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_update(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    await session.commit()

    user.name = "Updated User"
    await session.commit()

    stmt = select(User)
    result = await session.execute(stmt)
    updated_user = result.scalars().first()
    assert updated_user.name == "Updated User"


@pytest.mark.asyncio
async def test_delete(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    await session.commit()

    await session.delete(user)
    await session.commit()

    stmt = select(User)
    result = await session.execute(stmt)
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_concurrent_sessions(engine, session):
    # Several sessions at once check out separate pooled connections (or
    # share the StaticPool one for :memory:) without interfering.
    async_session = async_sessionmaker(engine, class_=AsyncSession)

    async def count(i):
        async with async_session() as s:
            result = await s.execute(text("SELECT :i"), {"i": i})
            return result.scalar()

    assert await asyncio.gather(*(count(i) for i in range(8))) == list(range(8))


@pytest.mark.asyncio
async def test_pool_pre_ping_replaces_dead_connection(tmp_path):
    # A connection that died while idle in the pool (what happens to a Hrana
    # stream the server expired) must be detected by pre-ping and replaced,
    # not handed to the application.
    import libsql

    if not hasattr(libsql, "ProgrammingError"):
        pytest.skip("libsql driver predates the DB-API exception hierarchy")

    engine = create_async_engine(
        f"sqlite+aiolibsql:///{tmp_path / 'ping.db'}",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            first = raw.driver_connection
            first.close()  # kill it behind the pool's back

        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar() == 1
            raw = await conn.get_raw_connection()
            assert raw.driver_connection is not first
    finally:
        await engine.dispose()
