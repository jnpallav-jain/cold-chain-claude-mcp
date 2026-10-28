"""UI-independent Claude Agent SDK orchestration and explicit session handling."""

import asyncio
from dataclasses import dataclass, field
import threading
from typing import AsyncIterator, Any
from uuid import uuid4
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    PermissionResultAllow,
    PermissionResultDeny,
)
from claude_agent_sdk.types import StreamEvent
from src.agent_tools import MCP_TOOL_NAMES, SERVER_NAME, create_business_mcp_server
from src.config import PROJECT_ROOT, Settings, get_settings
from pydantic import SecretStr
from src.services.container import Services, get_services
from src.services.observability import RequestTrace
from src.security.execution import RequestBudget
from src.security.redaction import Redactor, StreamingRedactor

PROMPT_PATH = PROJECT_ROOT / "src/prompts/system_prompt.txt"
RUNTIME_ROOT = PROJECT_ROOT / "data/cache/agent-runtime"


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    data: dict[str, Any]


@dataclass
class AgentSession:
    """Owned by one CLI/UI session. Never accept a client-provided SDK resume ID."""

    id: str = field(default_factory=lambda: str(uuid4()))
    sdk_session_id: str | None = None
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def reset(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A turn is still running.")
        try:
            self.id = str(uuid4())
            self.sdk_session_id = None
        finally:
            self._lock.release()


def load_system_prompt() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("System prompt must not be empty.")
    return prompt


async def business_tool_permission(name, arguments, context):
    if name in MCP_TOOL_NAMES:
        return PermissionResultAllow(updated_input=arguments)
    return PermissionResultDeny(
        message="Only the registered cold-chain MCP tools are permitted."
    )


def build_agent_options(
    settings: Settings, services: Services, session: AgentSession, *, trace=None
):
    settings.require("anthropic_api_key", "claude_model")
    # Private runtime directory prevents unrelated project config and transcripts from being loaded.
    directory = RUNTIME_ROOT / session.id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_dir = directory / "config"
    config_dir.mkdir(exist_ok=True, mode=0o700)
    return ClaudeAgentOptions(
        model=settings.claude_model,
        system_prompt=load_system_prompt(),
        tools=[],  # No built-in tools. allowed_tools alone would not remove them.
        allowed_tools=[],  # Every business call passes through the exact-name callback.
        disallowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Agent",
            "Task",
            "Skill",
        ],
        mcp_servers={
            SERVER_NAME: create_business_mcp_server(
                services,
                settings=settings,
                session_id=session.id,
                budget=RequestBudget(
                    settings.claude_request_timeout, settings.claude_max_tool_calls
                ),
            )
        },
        strict_mcp_config=True,
        setting_sources=[],
        skills=[],
        plugins=[],
        agents={},
        permission_mode="default",
        can_use_tool=business_tool_permission,
        hooks=trace.hooks() if trace else None,
        cwd=directory,
        env={
            **{
                field.validation_alias: ""
                for name, field in type(settings).model_fields.items()
                if name != "anthropic_api_key"
                and isinstance(getattr(settings, name), SecretStr)
                and isinstance(field.validation_alias, str)
            },
            "ANTHROPIC_API_KEY": settings.anthropic_api_key.get_secret_value(),
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_AUTH_TOKEN": "",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "CLAUDE_CODE_USE_BEDROCK": "0",
            "CLAUDE_CODE_USE_VERTEX": "0",
            "CLAUDE_CODE_USE_FOUNDRY": "0",
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "DISABLE_AUTOUPDATER": "1",
        },
        resume=session.sdk_session_id,
        continue_conversation=False,
        max_turns=settings.claude_max_turns,
        max_budget_usd=settings.claude_max_budget_usd,
        include_partial_messages=True,
        stderr=lambda line: None,  # Never surface raw CLI diagnostics or credential-bearing requests.
    )


class AgentRunner:
    def __init__(
        self,
        settings: Settings | None = None,
        services: Services | None = None,
        *,
        client_factory=ClaudeSDKClient,
    ):
        self.settings = settings if settings is not None else get_settings()
        self.services = services if services is not None else get_services()
        self.client_factory = client_factory
        self.redactor = Redactor(self.settings)

    async def stream_turn(
        self, session: AgentSession, prompt: str
    ) -> AsyncIterator[AgentEvent]:
        if not prompt.strip():
            yield AgentEvent("error", {"message": "Enter a question."})
            return
        if len(prompt) > self.settings.claude_max_prompt_chars:
            yield AgentEvent(
                "error", {"message": "Question exceeds the configured size limit."}
            )
            return
        if not session._lock.acquire(blocking=False):
            yield AgentEvent(
                "error", {"message": "This conversation already has a running request."}
            )
            return
        final_seen = False
        trace = RequestTrace(self.settings, self.services.audit, session.id)
        status = "interrupted"
        metrics = {}
        warned = 0
        captured_sdk_id = session.sdk_session_id
        try:
            if not await trace.write(
                "request_start",
                {
                    "status": "started",
                    "prompt": prompt,
                    "model_setting": self.settings.claude_model,
                },
            ):
                yield AgentEvent(
                    "audit_warning",
                    {
                        "message": "Request audit storage is unavailable; read-only answers may continue. Approval decisions require their own durable ledger."
                    },
                )
                warned = trace.warnings
            options = build_agent_options(
                self.settings, self.services, session, trace=trace
            )
            tool_names = {}
            assistant_text = []
            stream_redactor = StreamingRedactor(self.redactor)
            async with asyncio.timeout(self.settings.claude_request_timeout):
                async with self.client_factory(options=options) as client:
                    await client.query(self.redactor.text(prompt))
                    async for message in client.receive_response():
                        events = []
                        if (
                            isinstance(message, SystemMessage)
                            and message.subtype == "init"
                        ):
                            captured_sdk_id = message.data.get(
                                "session_id", captured_sdk_id
                            )
                            yield AgentEvent(
                                "session",
                                {
                                    "session_id": session.id,
                                    "available_tools": message.data.get("tools", []),
                                },
                            )
                        elif isinstance(message, StreamEvent):
                            event = message.event
                            if (
                                event.get("type") == "content_block_delta"
                                and event.get("delta", {}).get("type") == "text_delta"
                            ):
                                events.append(
                                    AgentEvent(
                                        "text_delta",
                                        {
                                            "text": stream_redactor.feed(
                                                event["delta"].get("text", "")
                                            )
                                        },
                                    )
                                )
                        elif isinstance(message, AssistantMessage):
                            if message.error:
                                events.append(
                                    AgentEvent(
                                        "error",
                                        {
                                            "message": "Claude could not process this request.",
                                            "category": message.error,
                                        },
                                    )
                                )
                            for block in message.content:
                                if isinstance(block, ToolUseBlock):
                                    tool_names[block.id] = block.name
                                    assistant_text.clear()
                                    events.append(
                                        AgentEvent(
                                            "tool_start",
                                            {
                                                "tool_call_id": block.id,
                                                "name": block.name,
                                                "arguments": block.input,
                                            },
                                        )
                                    )
                                elif isinstance(block, TextBlock):
                                    assistant_text.append(block.text)
                                    events.append(
                                        AgentEvent("text", {"text": block.text})
                                    )
                        elif isinstance(message, UserMessage) and isinstance(
                            message.content, list
                        ):
                            for block in message.content:
                                if isinstance(block, ToolResultBlock):
                                    events.append(
                                        AgentEvent(
                                            "tool_result",
                                            {
                                                "tool_call_id": block.tool_use_id,
                                                "name": tool_names.get(
                                                    block.tool_use_id, "tool"
                                                ),
                                                "content": block.content,
                                                "is_error": bool(block.is_error),
                                            },
                                        )
                                    )
                        elif isinstance(message, ResultMessage):
                            final_seen = True
                            status = "error" if message.is_error else "success"
                            metrics = {
                                "sdk_duration_ms": message.duration_ms,
                                "sdk_api_duration_ms": message.duration_api_ms,
                                "sdk_reported_cost_usd": message.total_cost_usd,
                                "usage": message.usage or {},
                                "model_usage": message.model_usage or {},
                                "turns": message.num_turns,
                                "cost_scope": "SDK-reported total; may be cumulative for resumed sessions; do not sum across turns.",
                            }
                            if message.is_error:
                                # Avoid accidentally resuming an incomplete/ambiguous turn after an SDK failure.
                                session.sdk_session_id = None
                                events.append(
                                    AgentEvent(
                                        "error",
                                        {
                                            "message": "Claude did not complete the request.",
                                            "category": message.subtype,
                                        },
                                    )
                                )
                            else:
                                session.sdk_session_id = (
                                    message.session_id or captured_sdk_id
                                )
                                events.append(
                                    AgentEvent(
                                        "complete",
                                        {
                                            "text": message.result
                                            or "\n".join(assistant_text),
                                            "cost_usd": message.total_cost_usd,
                                            "usage": message.usage or {},
                                            "model_usage": message.model_usage or {},
                                            "turns": message.num_turns,
                                            "session_id": session.id,
                                            **metrics,
                                        },
                                    )
                                )
                        if isinstance(message, ResultMessage):
                            tail = stream_redactor.flush()
                            if tail:
                                yield AgentEvent("text_delta", {"text": tail})
                        for event in events:
                            event = AgentEvent(event.kind, trace.enrich(event.data))
                            if event.kind in {
                                "tool_start",
                                "tool_result",
                                "complete",
                                "error",
                            }:
                                await trace.write(event.kind, event.data)
                            if trace.warnings > warned:
                                warned = trace.warnings
                                yield AgentEvent(
                                    "audit_warning",
                                    {
                                        "message": "An execution event was not saved to the audit log."
                                    },
                                )
                            yield event
            if not final_seen:
                session.sdk_session_id = None
                status = "error"
                event = AgentEvent(
                    "error",
                    trace.enrich(
                        {
                            "message": "Claude disconnected before completing the request."
                        }
                    ),
                )
                await trace.write("error", event.data)
                yield event
        except TimeoutError:
            session.sdk_session_id = None
            event = AgentEvent(
                "error", {"message": "Request exceeded the configured time limit."}
            )
            status = "timeout"
            if not await trace.write("error", event.data):
                yield AgentEvent(
                    "audit_warning",
                    {"message": "Error event could not be saved to the audit log."},
                )
                warned = trace.warnings
            yield AgentEvent(event.kind, trace.enrich(event.data))
        except Exception as error:
            session.sdk_session_id = None
            message = "Claude request failed. Check credentials, model access, and service availability."
            from src.config import ConfigurationError

            if isinstance(error, ConfigurationError):
                message = str(error)
            event = AgentEvent(
                "error", {"message": message, "category": type(error).__name__}
            )
            status = "error"
            if not await trace.write("error", event.data):
                yield AgentEvent(
                    "audit_warning",
                    {"message": "Error event could not be saved to the audit log."},
                )
                warned = trace.warnings
            yield AgentEvent(event.kind, trace.enrich(event.data))
        finally:
            try:
                await trace.close(status, metrics)
            finally:
                if not final_seen:
                    session.sdk_session_id = None
                session._lock.release()
        if trace.warnings > warned:
            yield AgentEvent(
                "audit_warning",
                {
                    "message": "One or more execution events were not saved to the audit log."
                },
            )
