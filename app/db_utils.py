"""Database utility functions for cross-dialect compatibility."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session


def dialect_insert(db: Session, model):
    """Return dialect-appropriate insert statement for ON CONFLICT support.

    SQLAlchemy's insert().on_conflict_do_nothing() requires dialect-specific imports.
    This helper automatically selects the right dialect based on the database connection.

    Args:
        db: SQLAlchemy session
        model: The model class to insert into

    Returns:
        Insert statement object with on_conflict_do_nothing() support

    Example:
        stmt = dialect_insert(db, User).values(external_id="user-1").on_conflict_do_nothing(
            index_elements=['external_id']
        )
        db.execute(stmt)
    """
    dialect = inspect(db.bind).dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)
