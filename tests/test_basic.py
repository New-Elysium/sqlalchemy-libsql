import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None]
    email: Mapped[str | None]


@pytest.fixture(params=["memory", "file", "remote", "embedded"])
def engine(request, tmp_path):
    import os

    database_url = os.getenv("TURSO_DATABASE_URL")
    # Embedded replicas sync via /export, which Turso Cloud serves but the
    # open-source sqld does not, so they need an explicit TURSO_SYNC_URL.
    sync_url = os.getenv("TURSO_SYNC_URL")
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "")
    match request.param:
        case "file":
            engine = create_engine(f"sqlite+libsql:///{tmp_path / 'test.db'}")
        case "remote" if database_url:
            secure = os.getenv("TURSO_SECURE", "true")
            engine = create_engine(
                f"sqlite+libsql://{database_url.strip()}?secure={secure}",
                connect_args={"auth_token": auth_token},
            )
        case "remote":
            pytest.skip("TURSO_DATABASE_URL not set")
        case "embedded" if sync_url:
            engine = create_engine(
                f"sqlite+libsql:///{tmp_path / 'test_embedded.db'}",
                connect_args={"auth_token": auth_token, "sync_url": sync_url},
            )
        case "embedded":
            pytest.skip("TURSO_SYNC_URL not set")
        case _:
            engine = create_engine("sqlite+libsql://")
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_connection(engine):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_create_table(session):
    with session.connection() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        )
        assert result.scalar() == "users"


def test_insert_and_query(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    session.commit()

    queried_user = session.query(User).first()
    assert queried_user.name == "Test User"
    assert queried_user.email == "test@example.com"


def test_update(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    session.commit()

    user.name = "Updated User"
    session.commit()

    updated_user = session.query(User).first()
    assert updated_user.name == "Updated User"


def test_delete(session):
    user = User(name="Test User", email="test@example.com")
    session.add(user)
    session.commit()

    session.delete(user)
    session.commit()

    assert session.query(User).count() == 0
