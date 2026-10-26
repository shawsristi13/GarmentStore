from sqlalchemy import inspect, text

from database.db import Base, engine
from database import models


def initialize_database():
    print("Connecting to PostgreSQL...")

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        print("Database connection successful.")

        Base.metadata.create_all(bind=engine)

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        print("\nDatabase tables:")

        for table in tables:
            print(f"- {table}")

        print("\nDatabase initialization completed successfully.")

    except Exception as error:
        print(f"\nDatabase initialization failed: {error}")
        raise


if __name__ == "__main__":
    initialize_database()