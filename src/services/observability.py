"""Per-request SDK hooks and a UI-independent, redacted audit writer."""

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from uuid import uuid4
from claude_agent_sdk import HookMatcher
from src.security.execution import get_workers
from src.security.redaction import Redactor
from src.services.audit import AuditEvent

logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tool_failed(output):
    """Recognize MCP envelopes and SDK-unwrapped JSON results without relying on prose."""
    if isinstance(output, str):
        try:
            return tool_failed(json.loads(output))
        except (ValueError, TypeError):
            return False
    if isinstance(output, list):
        return any(tool_failed(item) for item in output)
    if isinstance(output, dict):
        return bool(
            output.get("is_error")
            or output.get("isError")
            or output.get("ok") is False
            or tool_failed(output.get("content"))
            or tool_failed(output.get("text"))
        )
    return False


class RequestTrace:
    def __init__(self, settings, audit, session_id):
        self.settings, self.audit, self.session_id = settings, audit, session_id
        self.request_id = str(uuid4())
        self.started = time.monotonic()
        self.redactor = Redactor(settings)
        self.calls = {}
        self.warnings = 0
        self._write_lock = asyncio.Lock()

    def enrich(self, data):
        return self.redactor.data(
            {
                **data,
                "session_id": self.session_id,
                "request_id": self.request_id,
                "timestamp_utc": utc_now(),
                "request_elapsed_ms": round(
                    (time.monotonic() - self.started) * 1000, 3
                ),
            }
        )

    async def write(self, kind, data):
        data = self.enrich(data)
        try:
            record = AuditEvent(
                self.session_id,
                kind[:50],
                str(data.get("name", "claude"))[:100],
                json.dumps(data, ensure_ascii=False, default=str),
            )
            async with asyncio.timeout(min(5, self.settings.tool_timeout)):
                async with self._write_lock:
                    await get_workers(1, "audit").run(
                        lambda: self.audit.write(record),
                        seconds=min(5, self.settings.tool_timeout),
                    )
            return True
        except Exception:
            self.warnings += 1
            # Only identifiers, never raw exceptions or payloads. Visible even when the SQL sink is down.
            logger.error(
                "Audit persistence failed request=%s event=%s", self.request_id, kind
            )
            return False

    async def hook(self, data, tool_use_id, context):
        kind = data["hook_event_name"]
        call_id = data.get("tool_use_id") or tool_use_id
        name = data.get("tool_name", "tool")
        record = {
            "tool_call_id": call_id,
            "name": name,
            "arguments": data.get("tool_input", {}),
            "sdk_session_id": data.get("session_id"),
        }
        if kind == "PreToolUse":
            self.calls[call_id] = {
                "start": time.monotonic(),
                "name": name,
                "arguments": record["arguments"],
                "finished": False,
            }
            record["status"] = "started"
        else:
            prior = self.calls.get(call_id)
            record["latency_ms"] = data.get("duration_ms")
            if record["latency_ms"] is None and prior:
                record["latency_ms"] = round(
                    (time.monotonic() - prior["start"]) * 1000, 3
                )
            output = data.get("tool_response")
            failed = kind == "PostToolUseFailure"
            failed = failed or tool_failed(output)
            record.update(
                status="error" if failed else "success",
                output=output,
                error=data.get("error") if failed else None,
            )
            if prior:
                prior["finished"] = True
            if failed and record["error"] is None:
                record["error"] = "Tool returned an error result."
        await self.write("sdk_" + kind, record)
        return {}

    def hooks(self):
        return {
            name: [HookMatcher(hooks=[self.hook], timeout=10)]
            for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure")
        }

    async def close(self, status, metrics):
        for call_id, item in self.calls.items():
            if not item["finished"]:
                await self.write(
                    "tool_interrupted",
                    {
                        "tool_call_id": call_id,
                        "name": item["name"],
                        "arguments": item["arguments"],
                        "status": "interrupted",
                        "error": "Request ended without a terminal tool hook.",
                        "latency_ms": round(
                            (time.monotonic() - item["start"]) * 1000, 3
                        ),
                    },
                )
        return await self.write(
            "request_end",
            {
                "status": status,
                "duration_ms": round((time.monotonic() - self.started) * 1000, 3),
                **metrics,
                "audit_failures_before_end": self.warnings,
            },
        )
