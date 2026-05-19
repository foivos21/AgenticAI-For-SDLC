from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.config import Settings


logger = logging.getLogger("app.almas")

ANSI_RESET = "\033[0m"
ANSI_COLORS = {
    "analyzer": "\033[36m",
    "planner": "\033[33m",
    "developer": "\033[32m",
    "fixer": "\033[35m",
    "github": "\033[34m",
    "apply": "\033[34m",
}
SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|password|authorization|api[_-]?key)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(value: Any, *, redact: bool) -> Any:
    if isinstance(value, BaseModel):
        return _sanitize(value.model_dump(mode="json"), redact=redact)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if redact and SENSITIVE_KEY_PATTERN.search(str(key)):
                sanitized[str(key)] = "***REDACTED***"
            else:
                sanitized[str(key)] = _sanitize(item, redact=redact)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item, redact=redact) for item in value]
    return value


def _serialize_payload(value: Any, *, settings: Settings) -> str:
    sanitized = _sanitize(value, redact=settings.almas_redact_sensitive_logs)
    text = json.dumps(sanitized, indent=2, ensure_ascii=True, default=str)
    limit = max(256, int(settings.almas_log_payload_max_chars or 6000))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...<truncated {len(text) - limit} chars>"


def log_stage_payload(
    settings: Settings,
    *,
    run_id: str,
    issue_key: str,
    agent: str,
    stage: str,
    model: str,
    payload: Any,
) -> None:
    record = {
        "timestamp": _now(),
        "run_id": run_id,
        "issue_key": issue_key,
        "agent": agent,
        "stage": stage,
        "model": model,
        "payload": payload,
    }
    serialized = _serialize_payload(record, settings=settings)
    prefix = f"[ALMAS][{agent.upper()}][{stage.upper()}]"
    color = ANSI_COLORS.get(agent.lower(), "")
    if settings.almas_enable_color_logs and color:
        logger.info("%s%s%s\n%s", color, prefix, ANSI_RESET, serialized)
    else:
        logger.info("%s\n%s", prefix, serialized)
