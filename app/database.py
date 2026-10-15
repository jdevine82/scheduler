from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


# No migration framework — create_all() only adds missing tables, never
# columns, so new nullable columns on existing tables are listed here and
# added in place on startup.
ADDED_COLUMNS = [
    ("workers", "servicem8_queue_uuid", "VARCHAR(64)"),
    ("jobs", "servicem8_queue_pushed", "VARCHAR(255)"),
]


def add_missing_columns() -> None:
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if existing and column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
