
import os

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load local .env settings (for local development)
load_dotenv()


def get_setting(name):
    """Read a setting from Streamlit Cloud secrets or local environment."""
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        # Streamlit secrets may not exist during local development.
        pass

    return os.getenv(name)


# Required database configuration
required_settings = [
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
]

settings = {name: get_setting(name) for name in required_settings}

missing_settings = [
    name for name, value in settings.items() if not value
]

if missing_settings:
    raise RuntimeError(
        f"Missing database settings: {', '.join(missing_settings)}"
    )

# Build the PostgreSQL connection URL
database_url = URL.create(
    drivername="postgresql+psycopg2",
    username=settings["DB_USER"],
    password=settings["DB_PASSWORD"],
    host=settings["DB_HOST"],
    port=int(settings["DB_PORT"]),
    database=settings["DB_NAME"],
)

# Create the SQLAlchemy engine
engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

