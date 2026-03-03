"""Central logging for the app: one logger, console output, step-level messages."""
import logging
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module (e.g. app.api.upload). Use 'app.*' so logs go to app handler."""
    if not name.startswith("app"):
        name = f"app.{name}"
    return logging.getLogger(name)


def setup_logging(level: str | None = None) -> None:
    """Configure root app logger and console handler. Call once at startup."""
    level = (level or LOG_LEVEL).upper()
    numeric = getattr(logging, level, logging.INFO)

    root = logging.getLogger("app")
    root.setLevel(numeric)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FMT))
        root.addHandler(handler)

    # Avoid duplicate logs from uvicorn's propagation
    for n in ("uvicorn", "uvicorn.error"):
        logging.getLogger(n).setLevel(logging.WARNING)
