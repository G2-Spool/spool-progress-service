"""Structured logging configuration."""

import sys
import structlog
from structlog.processors import JSONRenderer, TimeStamper, add_log_level
from structlog.stdlib import add_logger_name

from app.core.config import settings


def setup_logging():
    """Configure structured logging."""
    
    # Determine renderer based on environment
    if settings.LOG_FORMAT == "json":
        renderer = JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.contextvars.merge_contextvars,
            add_log_level,
            add_logger_name,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Set log level
    import logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL),
    )