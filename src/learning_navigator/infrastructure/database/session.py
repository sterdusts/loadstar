"""Engine and session lifecycle management."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from learning_navigator.infrastructure.database.base import Base


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    engine = create_engine(database_url, **options)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_schema(engine: Engine) -> None:
    """Create tables for local/demo startup; production deployments should run Alembic."""

    Base.metadata.create_all(engine)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
