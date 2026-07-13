"""Create dedicated daily DB and avoid legacy `runs` table collision."""

from __future__ import annotations

from sqlalchemy import create_engine, text

ADMIN = "postgresql+psycopg://connor:connor@localhost:5432/postgres"
DB_NAME = "connor_daily"


def main() -> None:
    engine = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": DB_NAME},
        ).scalar()
        if exists:
            print(f"{DB_NAME} already exists")
        else:
            conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
            print(f"created {DB_NAME}")


if __name__ == "__main__":
    main()
