from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from backend.config import settings

# Tells FastAPI to look for this header on every protected request
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI dependency — inject this into any route to protect it.

    Usage:
        @router.post("/some-endpoint")
        async def my_route(deps: str = Depends(require_api_key)):
            ...

    Returns the key on success, raises 401 on failure.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Use constant-time comparison to prevent timing attacks
    import hmac
    if not hmac.compare_digest(api_key, settings.app_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
