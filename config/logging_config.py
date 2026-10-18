"""Structured logging configuration.

Logs are emitted as single-line key=value records. A redaction filter strips
anything that looks like an API key or bearer token so secrets never reach the
log stream.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Optional

_CONFIGURED = False

# Patterns that should never appear in logs.
_REDACT_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9]{32,}"),  # long opaque strings (likely keys)
]


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pat in _REDACT_PATTERNS:
            redacted = pat.sub("[REDACTED]", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s level=%(levelname)s logger=%(name)s %(message)s")
    )
    handler.addFilter(_RedactionFilter())
    root = logging.getLogger("meridian")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    configure_logging()
    return logging.getLogger("meridian" if not name else f"meridian.{name}")
