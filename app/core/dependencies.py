"""Shared dependencies for Progress Service."""

from typing import Optional
import httpx
from aiocache import Cache
import structlog
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

logger = structlog.get_logger()

# Global instances
_redis_cache: Optional[Cache] = None
_http_client: Optional[httpx.AsyncClient] = None

# Security
security = HTTPBearer()


async def get_redis_cache():
    """Get Redis cache instance."""
    global _redis_cache
    
    if _redis_cache is None:
        try:
            _redis_cache = Cache.from_url(settings.REDIS_URL)
            await _redis_cache.exists("test")  # Test connection
            logger.info("Redis cache connection established")
        except Exception as e:
            logger.warning(f"Redis cache not available: {e}")
            # Fallback to in-memory cache
            _redis_cache = Cache(Cache.MEMORY)
    
    return _redis_cache


async def get_http_client() -> httpx.AsyncClient:
    """Get HTTP client for service communication."""
    global _http_client
    
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"{settings.SERVICE_NAME}/{settings.APP_VERSION}"
            }
        )
    
    return _http_client


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token."""
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"user_id": user_id, "role": payload.get("role", "student")}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )