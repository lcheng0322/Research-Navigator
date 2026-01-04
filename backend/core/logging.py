import logging
import json
from typing import Any, Dict

from .config import settings


class JsonFormatter(logging.Formatter):
    """Simple JSON log formatter for structured logs."""
    def format(self, record: logging.LogRecord) -> str:
        data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include extra fields if present
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        if record.__dict__.get("extra"):
            data.update(record.__dict__["extra"])
        return json.dumps(data, ensure_ascii=False)


def setup_logging() -> None:
    """
    Configure root and common loggers to use JSON formatting and the configured log level.
    Optionally initialize Sentry if DSN is provided.
    """
    level = getattr(logging, (settings.__dict__.get("LOG_LEVEL") or "INFO").upper(), logging.INFO)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.handlers = [handler]

    # Uvicorn loggers
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # Avoid duplicate handlers
        logger.handlers = [handler]

    # Optional: Sentry integration
    dsn = settings.__dict__.get("SENTRY_DSN")
    if dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)  # tracing off by default
            logging.getLogger(__name__).info("Sentry initialized", extra={"component": "logging", "sentry": True})
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to initialize Sentry", extra={"error": str(e)})