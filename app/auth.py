from fastapi import Header, HTTPException, status

from .config import get_settings


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")
    return token.strip()


def require_service_token(authorization: str | None = Header(default=None)) -> None:
    token = _bearer_token(authorization)
    settings = get_settings()
    if token != settings.ingest_service_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def authorize_dashboard_access(requested_user: str, authorization: str | None = Header(default=None)) -> None:
    token = _bearer_token(authorization)
    settings = get_settings()
    token_map = settings.dashboard_token_map
    allowed_user = token_map.get(token)
    if allowed_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if allowed_user != "*" and allowed_user != requested_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def require_admin_token(authorization: str | None = Header(default=None)) -> None:
    """Validate admin token for admin dashboard endpoints."""
    token = _bearer_token(authorization)
    settings = get_settings()
    if token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
