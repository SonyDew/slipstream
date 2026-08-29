"""Structured logging with a strict secret-redaction filter."""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any, ClassVar

from app.core.config import settings

# Keys whose values must never reach a log sink.
_SENSITIVE_KEYS = {
    "password",
    "current_password",
    "new_password",
    "confirm_password",
    "password_hash",
    "token",
    "session_token",
    "csrf_token",
    "secret",
    "secret_key",
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
}

_REDACTED = "[REDACTED]"

# Catches `password=hunter2`, `"token": "abc"`, `Authorization: Bearer x`.
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(k) for k in sorted(_SENSITIVE_KEYS, key=len, reverse=True))
    + r")(\"?\s*[:=]\s*\"?)([^\s,;&\"})\]]+)"
)


def redact_text(text: str) -> str:
    return _INLINE_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", text)


def redact_mapping(data: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys in structures destined for logs."""
    if _depth > 6:
        return "[TRUNCATED]"
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                out[str(key)] = _REDACTED
            else:
                out[str(key)] = redact_mapping(value, _depth + 1)
        return out
    if isinstance(data, (list, tuple)):
        return [redact_mapping(v, _depth + 1) for v in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


class RedactionFilter(logging.Filter):
    """Last line of defence: scrub the rendered message and any extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_mapping(record.args)
            else:
                record.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in record.args
                )
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            record.extra_fields = redact_mapping(extra)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for attr in ("request_id", "user_id", "job_id", "event"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    _COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)-26s %(message)s", "%H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        rid = getattr(record, "request_id", None)
        if rid:
            base = f"{base}  [req={rid}]"
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict) and extra:
            base = f"{base}  {json.dumps(extra, ensure_ascii=False, default=str)}"
        if self.use_color and record.levelname in self._COLORS:
            return f"{self._COLORS[record.levelname]}{base}{self._RESET}"
        return base


class StructuredAdapter(logging.LoggerAdapter):
    """Lets callers pass arbitrary kwargs that land in ``extra_fields``."""

    _RESERVED: ClassVar[set[str]] = {"exc_info", "stack_info", "stacklevel", "extra"}

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        fields = {k: v for k, v in kwargs.items() if k not in self._RESERVED}
        for key in fields:
            kwargs.pop(key)
        promoted = {}
        for key in ("request_id", "user_id", "job_id", "event"):
            if key in fields:
                promoted[key] = fields.pop(key)
        extra = kwargs.setdefault("extra", {})
        extra.update(promoted)
        if fields:
            extra["extra_fields"] = fields
        return msg, kwargs


_configured = False


def setup_logging() -> None:
    """Idempotently configure root logging (console + rotating file)."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    redaction = RedactionFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        JsonFormatter() if settings.LOG_JSON else ConsoleFormatter(use_color=sys.stdout.isatty())
    )
    console.addFilter(redaction)
    root.addHandler(console)

    try:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        # 5 x 10 MiB keeps disk use bounded on a small VPS.
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "slipstream.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Could not open log file; continuing with console logging only")

    # Our request middleware already emits one line per request.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # yt-dlp is chatty and can echo URLs containing query parameters.
    logging.getLogger("yt_dlp").setLevel(logging.ERROR)
    _configured = True


def get_logger(name: str) -> StructuredAdapter:
    return StructuredAdapter(logging.getLogger(name), {})


def log_security_event(event: str, **fields: Any) -> None:
    """Dedicated channel for auth/security events (never carries credentials)."""
    get_logger("slipstream.security").warning("security event: %s", event, event=event, **fields)
