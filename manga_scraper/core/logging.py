import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from manga_scraper.config import settings


def setup_logging() -> None:
    """Configure structured logging."""
    
    # Determine log level
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Shared processors for all loggers
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]

    # Development: pretty console output
    # Production: JSON output
    if settings.is_production:
        shared_processors.extend([
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ])
    else:
        shared_processors.extend([
            structlog.dev.ConsoleRenderer(colors=True),
        ])

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )


def get_logger(name: str | None = None, **kwargs: Any) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    logger = structlog.get_logger(name)
    if kwargs:
        logger = logger.bind(**kwargs)
    return logger
