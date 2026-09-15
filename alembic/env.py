"""Read credentials only from environment; no SQL/secret logging."""

import os

from sqlalchemy import create_engine, pool

from alembic import context
from neftecode_hackathon.persistence.models import Base

url = os.environ["DATABASE_URL"]
if not url.startswith("postgresql+psycopg://"):
    raise ValueError("DATABASE_URL must use PostgreSQL with psycopg")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
