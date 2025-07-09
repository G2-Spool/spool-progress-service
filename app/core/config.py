"""Configuration management for Progress Service."""

from typing import List, Optional
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, PostgresDsn
import json


class Settings(BaseSettings):
    """Application settings with validation."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )
    
    # Application
    APP_NAME: str = "Spool Progress Service"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production)$")
    SERVICE_NAME: str = "progress-service"
    SERVICE_PORT: int = 8004
    
    # Database
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40
    
    # Redis Cache
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL: int = 3600  # 1 hour
    
    # Service URLs
    API_GATEWAY_URL: str = "http://localhost:8000"
    EXERCISE_SERVICE_URL: str = "http://localhost:8003"
    CONTENT_SERVICE_URL: str = "http://localhost:8002"
    
    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60
    
    # Gamification Points
    POINTS_CONCEPT_STARTED: int = 5
    POINTS_CONCEPT_COMPLETED: int = 10
    POINTS_CONCEPT_MASTERED: int = 25
    POINTS_PERFECT_SCORE_BONUS: int = 10
    POINTS_DAILY_STREAK: int = 5
    POINTS_WEEKLY_GOAL: int = 50
    STREAK_GRACE_HOURS: int = 36
    
    # Analytics
    ANALYTICS_RETENTION_DAYS: int = 365
    REPORT_GENERATION_TIMEOUT: int = 60
    ENABLE_AI_INSIGHTS: bool = True
    
    # Notifications
    EMAIL_ENABLED: bool = True
    SMS_ENABLED: bool = False
    PUSH_NOTIFICATIONS_ENABLED: bool = True
    NOTIFICATION_BATCH_SIZE: int = 100
    
    # AWS (for SES)
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    SES_FROM_EMAIL: str = "noreply@spool.edu"
    
    # Twilio (for SMS)
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    
    # Firebase (for push)
    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    
    # Dashboard
    LEADERBOARD_SIZE: int = 100
    LEADERBOARD_CACHE_TTL: int = 300  # 5 minutes
    DASHBOARD_CACHE_TTL: int = 60  # 1 minute
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    LOG_FORMAT: str = Field(default="json", pattern="^(json|plain)$")
    
    # CORS
    CORS_ORIGINS: List[str] = Field(default_factory=list)
    
    @field_validator("CORS_ORIGINS", mode="before")
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # Monitoring
    ENABLE_METRICS: bool = True
    
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT == "production"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()