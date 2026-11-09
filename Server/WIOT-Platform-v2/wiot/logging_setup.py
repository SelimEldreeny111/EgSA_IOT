"""Structured logging with secret redaction and a rotating file sink."""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import time
from contextvars import ContextVar
from pathlib import Path

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_RE = re.compile(r"(?i)((?:password|aes_key|key_hex|token|secret)\s*[=:]\s*)\S+")


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1[REDACTED]", str(text))


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, log_dir: Path, as_json: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    text_fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter() if as_json else text_fmt)
    console.addFilter(_ContextFilter())
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "wiot-server.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(_ContextFilter())
    root.addHandler(file_handler)

    for noisy in ("uvicorn.access", "watchfiles", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
