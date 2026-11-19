from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

from core.db_safety import guard_database_url

# Test runs must use a dedicated test database; refused before any engine exists (no-op outside tests)
guard_database_url(settings.SQLALCHEMY_DATABASE_URI, explicit=settings.DATABASE_URL is not None)

is_sqlite = settings.SQLALCHEMY_DATABASE_URI.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True, connect_args=connect_args)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


