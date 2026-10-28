"""Claude SDK MCP adapters over the framework-independent business services."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from functools import partial
import json
from typing import Any
import asyncio
import time
from claude_agent_sdk import tool, create_sdk_mcp_server
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from src.services.container import Services
from src.services.errors import ServiceError, TransientServiceError
from src.services.sql_executor import QueryCancellation
from src.config import get_settings
from src.security.execution import RequestBudget, get_workers
from src.security.redaction import Redactor

SERVER_NAME = "coldchain"
TOOL_NAMES = (
    "query_telemetry_db",
    "fetch_corridor_conditions",
    "search_compliance_sop",
)
MCP_TOOL_NAMES = tuple(f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TelemetryArguments(Arguments):
    sql_query: str = Field(min_length=1, max_length=10000)


class WeatherArguments(Arguments):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SopArguments(Arguments):
    query: str = Field(min_length=1, max_length=4000)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("Unsupported result type")


def tool_result(
    payload: dict[str, Any], *, error=False, redactor=None, max_bytes=16384
):
    if redactor:
        payload = redactor.data(payload)
    encoded = json.dumps(payload, default=_json_default, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > max_bytes:
        encoded = json.dumps(
            {
                "ok": False,
                "error": "Tool output exceeded the configured size limit. Narrow the query.",
            }
        )
        error = True
    return {"content": [{"type": "text", "text": encoded}], "is_error": error}


def build_mcp_tools(services: Services, *, settings=None, budget=None):
    settings = settings if settings is not None else get_settings()
    budget = (
        budget
        if budget is not None
        else RequestBudget(
            settings.claude_request_timeout, settings.claude_max_tool_calls
        )
    )
    workers = get_workers(settings.tool_worker_limit)
    redactor = Redactor(settings)

    def response(payload, *, error=False):
        return tool_result(
            payload,
            error=error,
            redactor=redactor,
            max_bytes=settings.tool_max_output_bytes,
        )

    async def invoke(schema, args, operation, *, cancellation=None):
        try:
            values = schema.model_validate(args).model_dump()
            deadline = time.monotonic() + min(settings.tool_timeout, budget.reserve())
            for attempt in range(settings.tool_max_attempts):
                try:
                    result = await workers.run(
                        partial(operation, **values),
                        seconds=max(0.001, deadline - time.monotonic()),
                        cancel=cancellation.cancel if cancellation else None,
                    )
                    return response({"ok": True, "data": result, "evidence_only": True})
                except TransientServiceError:
                    if (
                        attempt + 1 == settings.tool_max_attempts
                        or deadline - time.monotonic() <= 0.1
                    ):
                        raise
                    await asyncio.sleep(0.1)
            raise ServiceError("Tool attempt budget exhausted.")
        except ValidationError:
            return response(
                {"ok": False, "error": "Invalid tool arguments."}, error=True
            )
        except ServiceError as error:
            return response({"ok": False, "error": str(error)}, error=True)
        except Exception:
            return response(
                {"ok": False, "error": "Tool execution failed."}, error=True
            )

    @tool(
        "query_telemetry_db",
        "Query historical synthetic fleet observations using T-SQL SELECT against FDE_VIEWS.VW_ACTIVE_FLEET. Columns: Timestamp, Latitude, Longitude, Current_Temperature_C, Cargo_Condition_Code, Risk_Classification, Delay_Probability, Port_Congestion_Level, Route_Risk_Index. Return at most the configured row limit. These records are not live shipments.",
        TelemetryArguments.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def telemetry(args):
        cancellation = QueryCancellation()

        def operation(sql_query):
            result = services.telemetry.query(sql_query, cancellation=cancellation)
            return {
                **asdict(result),
                "observation_type": "historical_synthetic",
                "returned_rows": len(result.rows),
            }

        return await invoke(
            TelemetryArguments, args, operation, cancellation=cancellation
        )

    @tool(
        "fetch_corridor_conditions",
        "Fetch timestamped current weather for GPS coordinates. The wind-based disruption score is a demonstration heuristic, not measured traffic congestion. Current weather cannot establish the cause of historical fleet readings.",
        WeatherArguments.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def weather(args):
        return await invoke(
            WeatherArguments,
            args,
            lambda **values: asdict(services.weather.fetch(**values)),
        )

    @tool(
        "search_compliance_sop",
        "Retrieve up to two relevant SOP passages with source filename and section metadata. Use for temperature thresholds, cold-chain breach responses, rerouting, and escalation rules. Cite returned sources; do not invent missing clauses.",
        SopArguments.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def sop(args):
        return await invoke(
            SopArguments,
            args,
            lambda query: {
                "passages": [asdict(item) for item in services.sop.search(query)]
            },
        )

    return [telemetry, weather, sop]


def create_business_mcp_server(services: Services, *, settings=None, budget=None):
    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="0.4.0",
        tools=build_mcp_tools(services, settings=settings, budget=budget),
    )
