import os
from functools import lru_cache
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class Settings(BaseModel):
    database_url: str = Field(..., alias="DATABASE_URL")
    ingest_service_token: str = Field(..., alias="INGEST_SERVICE_TOKEN")
    admin_token: str = Field(..., alias="ADMIN_TOKEN")
    dashboard_token_map: Dict[str, str] = Field(default_factory=dict, alias="DASHBOARD_TOKEN_MAP")
    dashboard_origin: str = Field(..., alias="DASHBOARD_ORIGIN")
    dashboard_allowed_origins: List[str] = Field(default_factory=list, alias="DASHBOARD_ALLOWED_ORIGINS")
    environment: Literal["development", "production", "test"] = Field(default="development", alias="APP_ENV")
    rollup_window_days: int = Field(default=7, alias="ROLLUP_WINDOW_DAYS")

    @field_validator("dashboard_token_map", mode="before")
    @classmethod
    def parse_token_map(cls, value: object) -> Dict[str, str]:
        if value in (None, "", {}):
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            parsed: Dict[str, str] = {}
            pairs = [item.strip() for item in value.split(",") if item.strip()]
            for pair in pairs:
                if ":" not in pair:
                    raise ValueError("Expected DASHBOARD_TOKEN_MAP entries in 'token:user' format")
                token, user = [part.strip() for part in pair.split(":", 1)]
                if not token or not user:
                    raise ValueError("Token and user mapping must be non-empty")
                parsed[token] = user
            return parsed
        raise ValueError("Unsupported DASHBOARD_TOKEN_MAP type")

    @model_validator(mode="after")
    def validate_rollup_days(self) -> "Settings":
        if self.rollup_window_days != 7:
            raise ValueError("ROLLUP_WINDOW_DAYS is locked to 7 for this release")
        return self

    @staticmethod
    def _normalize_database_url(url: str) -> str:
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+psycopg" not in url:
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgresql+psycopg2://"):
            return "postgresql+psycopg://" + url[len("postgresql+psycopg2://") :]
        return url

    @staticmethod
    def _parse_dashboard_origins(raw_value: Optional[str]) -> List[str]:
        if raw_value in (None, ""):
            raise ValueError("DASHBOARD_ORIGIN must include at least one origin")
        if isinstance(raw_value, str):
            origins = [item.strip() for item in raw_value.split(",") if item.strip()]
            if not origins:
                raise ValueError("DASHBOARD_ORIGIN must include at least one origin")
            return origins
        if isinstance(raw_value, list):
            origins = [str(item).strip() for item in raw_value if str(item).strip()]
            if not origins:
                raise ValueError("DASHBOARD_ORIGIN must include at least one origin")
            return origins
        raise ValueError("Unsupported DASHBOARD_ORIGIN type")

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            raw_dashboard_map = os.getenv("DASHBOARD_TOKEN_MAP", "")
            raw_rollup = os.getenv("ROLLUP_WINDOW_DAYS")
            rollup_days = int(raw_rollup) if raw_rollup not in (None, "") else 7
            raw_dashboard_origins = os.getenv("DASHBOARD_ALLOWED_ORIGINS")
            dashboard_origins = cls._parse_dashboard_origins(
                raw_dashboard_origins if raw_dashboard_origins not in (None, "") else os.environ["DASHBOARD_ORIGIN"]
            )
            database_url = cls._normalize_database_url(os.environ["DATABASE_URL"])
            return cls(
                DATABASE_URL=database_url,
                INGEST_SERVICE_TOKEN=os.environ["INGEST_SERVICE_TOKEN"],
                ADMIN_TOKEN=os.environ["ADMIN_TOKEN"],
                DASHBOARD_TOKEN_MAP=raw_dashboard_map,
                DASHBOARD_ORIGIN=dashboard_origins[0],
                DASHBOARD_ALLOWED_ORIGINS=dashboard_origins,
                ROLLUP_WINDOW_DAYS=rollup_days,
                APP_ENV=os.getenv("APP_ENV", "development").lower(),
            )
        except ValueError as err:
            raise RuntimeError(f"Configuration error: Invalid ROLLUP_WINDOW_DAYS: {err}") from err
        except ValidationError as err:
            raise RuntimeError(f"Configuration error: {err}") from err
        except KeyError as missing:
            raise RuntimeError(f"Missing required environment variable: {missing}") from missing


@lru_cache()
def get_settings() -> Settings:
    """
    Cached settings accessor so the app parses environment variables exactly once.
    """
    return Settings.from_env()
