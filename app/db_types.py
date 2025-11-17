from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, List, Sequence

from sqlalchemy import Boolean, Integer, Numeric
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import JSON, TypeDecorator


class BooleanArray(TypeDecorator[List[bool]]):
    """
    Use PostgreSQL ARRAY in production and JSON for lightweight sqlite testing.
    """

    impl = ARRAY(Boolean)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Boolean))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[bool] | None, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return list(value)

    def process_result_value(self, value: Any, dialect) -> List[bool] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            return list(json.loads(value))
        return list(value)


class IntegerArray(TypeDecorator[List[int]]):
    impl = ARRAY(Integer)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Integer))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[int] | None, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return list(value)

    def process_result_value(self, value: Any, dialect) -> List[int] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            return list(json.loads(value))
        return list(value)


class DecimalArray(TypeDecorator[List[Decimal | None]]):
    impl = ARRAY(Numeric(4, 2))
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Numeric(4, 2)))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[Decimal | None] | None, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        normalized: list[float | None] = []
        for item in value:
            if item is None:
                normalized.append(None)
            else:
                normalized.append(float(item))
        return normalized

    def process_result_value(self, value: Any, dialect) -> List[Decimal | None] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            value = json.loads(value)
        result: list[Decimal | None] = []
        for item in value:
            if item is None:
                result.append(None)
            else:
                result.append(Decimal(str(item)))
        return result
