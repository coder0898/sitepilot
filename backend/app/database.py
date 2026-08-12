from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):
    """Render UUID columns as CHAR(32) under SQLite, which the test harness
    uses. Postgres is untouched - this rule is registered for the sqlite
    dialect only.

    Without it SQLAlchemy emits a column of declared type `UUID`, and SQLite
    assigns affinity by looking for substrings: INT, CHAR, CLOB, TEXT, BLOB,
    REAL, FLOA, DOUB. "UUID" contains none of them, so the column falls
    through to NUMERIC affinity - and NUMERIC quietly converts any value
    that looks like a number.

    A uuid4 hex is 32 characters of 0-9a-f, so every so often one is a valid
    numeric literal: all digits, or digits around a single `e`
    ("...811111e111111" parses as scientific notation). SQLite stored those
    as REAL, and reading one back raised

        AttributeError: 'float' object has no attribute 'replace'

    from inside uuid.UUID(). A few in a million per identifier, tens of
    thousands of identifiers per suite run - so the suite failed every few
    runs, in a different test each time, and passed on a rerun. CHAR(32)
    gives the column TEXT affinity and the value is stored verbatim.
    """
    return "CHAR(32)"


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
