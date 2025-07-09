"""Main FastAPI application for Progress Service."""

import os
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import init_db, get_db
from app.core.dependencies import get_redis_cache
from app.routers import progress, gamification, analytics, notifications, dashboard

# Setup structured logging
setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    # Startup
    logger.info("Starting Spool Progress Service", version=settings.APP_VERSION)
    
    # Initialize database
    await init_db()
    
    # Initialize services
    redis_cache = await get_redis_cache()
    
    # Store in app state
    app.state.redis_cache = redis_cache
    
    # Setup Prometheus metrics
    if settings.ENABLE_METRICS:
        instrumentator = Instrumentator()
        instrumentator.instrument(app).expose(app, endpoint="/metrics")
    
    logger.info("Progress service initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Spool Progress Service")


# Create FastAPI app
app = FastAPI(
    title="Spool Progress Service",
    description="Progress tracking, gamification, and analytics for the Spool platform",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(progress.router, prefix="/api/progress", tags=["progress"])
app.include_router(gamification.router, prefix="/api/gamification", tags=["gamification"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])


@app.get("/", tags=["root"])
async def root():
    """Root endpoint."""
    return {
        "service": "Spool Progress Service",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "operational"
    }


@app.get("/health", tags=["health"])
async def health_check(request: Request):
    """Health check endpoint."""
    health_status = {
        "status": "healthy",
        "service": "progress-service",
        "version": settings.APP_VERSION,
        "checks": {}
    }
    
    # Check database
    try:
        async for db in get_db():
            await db.execute("SELECT 1")
            health_status["checks"]["database"] = "healthy"
    except Exception as e:
        health_status["checks"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        if hasattr(request.app.state, "redis_cache"):
            await request.app.state.redis_cache.exists("health_check")
            health_status["checks"]["redis"] = "healthy"
    except Exception as e:
        health_status["checks"]["redis"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/config", tags=["debug"])
async def get_config():
    """Get current configuration (development only)."""
    if settings.ENVIRONMENT == "production":
        return JSONResponse(
            content={"error": "Not available in production"},
            status_code=403
        )
    
    return {
        "environment": settings.ENVIRONMENT,
        "gamification": {
            "points": {
                "concept_started": settings.POINTS_CONCEPT_STARTED,
                "concept_completed": settings.POINTS_CONCEPT_COMPLETED,
                "concept_mastered": settings.POINTS_CONCEPT_MASTERED,
                "daily_streak": settings.POINTS_DAILY_STREAK
            },
            "streak_grace_hours": settings.STREAK_GRACE_HOURS
        },
        "analytics": {
            "retention_days": settings.ANALYTICS_RETENTION_DAYS,
            "ai_insights": settings.ENABLE_AI_INSIGHTS
        },
        "notifications": {
            "email": settings.EMAIL_ENABLED,
            "sms": settings.SMS_ENABLED,
            "push": settings.PUSH_NOTIFICATIONS_ENABLED
        },
        "leaderboard_size": settings.LEADERBOARD_SIZE
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVICE_PORT,
        reload=settings.ENVIRONMENT == "development",
        log_config=None  # Use structlog instead
    )