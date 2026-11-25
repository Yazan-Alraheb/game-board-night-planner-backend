
import app.models

from sqlalchemy import inspect
from app.core.database import Base, engine


def init_db():
    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            "Database initialization requires PostgreSQL. "
            "Check your DATABASE_URL in .env."
        )

    print("Connecting to PostgreSQL...")
    print(f"Database: {engine.url.database}")

    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())

        print("Checking database tables...")

        # Creates only missing tables
        Base.metadata.create_all(bind=connection)

        # Verify which tables were created
        inspector = inspect(connection)
        current_tables = set(inspector.get_table_names())

    created_tables = current_tables - existing_tables

    if created_tables:
        print("\nCreated tables:")
        for table in sorted(created_tables):
            print(f"  + {table}")
    else:
        print("\nNo new tables needed.")

    print("\nCurrent database tables:")
    for table in sorted(current_tables):
        print(f"  - {table}")

    print("\nDatabase initialization complete!")


if __name__ == "__main__":
    init_db()
