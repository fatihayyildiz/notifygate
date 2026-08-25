"""notifygate — Hermes → NotifyGate sender plugin.

Every hook event (tool call, session end, subagent stop) is POSTed to the
NotifyGate server as an HMAC-signed, fire-and-forget request. The server
applies the rules (dedupe, stale sweep, quiet hours, digests) and delivers
only what matters to Telegram/Slack — this plugin never blocks the agent.

Env vars (put in ~/.hermes/.env):
    NOTIFYGATE_URL      default http://localhost:8457/v1/adapters/hermes
    NOTIFYGATE_SECRET   optional — if set, requests are signed with
                        X-Hermes-Signature-256 (server must share the secret)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MAX_PAYLOAD = 100_000  # server clips details anyway; don't ship megabytes


def _clip(value: Any, limit: int = _MAX_PAYLOAD) -> Any:
    """Sınırlı kopya — sonuç devasa olabilir (terminal çıktısı)."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "\n…[truncated by notifygate plugin]"
    return value


def _send(payload: Dict[str, Any]) -> None:
    url = os.environ.get(
        "NOTIFYGATE_URL", "http://localhost:8457/v1/adapters/hermes"
    ).strip()
    secret = os.environ.get("NOTIFYGATE_SECRET", "").strip()
    body = json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        req.add_header("X-Hermes-Signature-256", f"sha256={sig}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as exc:  # fire-and-forget: never block or crash the turn
        logger.debug("notifygate iletim hatası: %s", exc)


def _fire(payload: Dict[str, Any]) -> None:
    threading.Thread(target=_send, args=(payload,), daemon=True).start()


def _base(hook_event_name: str, session_id: str, task_id: str) -> Dict[str, Any]:
    return {
        "hook_event_name": hook_event_name,
        "session_id": session_id or "",
        "task_id": task_id or "",
        "delivery_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "extra": {},
    }


def _on_post_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    duration_ms: Optional[float] = None,
    **_,
) -> None:
    payload = _base("post_tool_call", session_id, task_id)
    payload["tool_name"] = tool_name or ""
    payload["tool_input"] = args if isinstance(args, dict) else {"value": args}
    payload["extra"].update(
        {
            "tool_call_id": tool_call_id or "",
            "duration_ms": duration_ms,
            "result": _clip(result),
        }
    )
    _fire(payload)


def _on_session_end(
    session_id: str = "",
    task_id: str = "",
    completed: bool = False,
    failed: bool = False,
    interrupted: bool = False,
    turn_exit_reason: str = "",
    model: str = "",
    platform: str = "",
    **_: Any,
) -> None:
    payload = _base("on_session_end", session_id, task_id)
    payload["extra"].update(
        {
            "completed": completed,
            "failed": failed,
            "interrupted": interrupted,
            "turn_exit_reason": turn_exit_reason or "",
            "model": model or "",
            "platform": platform or "",
        }
    )
    _fire(payload)


def _on_subagent_stop(
    session_id: str = "",
    task_id: str = "",
    subagent_id: str = "",
    completed: bool = False,
    failed: bool = False,
    interrupted: bool = False,
    **_: Any,
) -> None:
    payload = _base("subagent_stop", session_id, task_id)
    payload["extra"].update(
        {
            "subagent_id": subagent_id or "",
            "completed": completed,
            "failed": failed,
            "interrupted": interrupted,
        }
    )
    _fire(payload)


def register(ctx) -> None:
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("subagent_stop", _on_subagent_stop)
