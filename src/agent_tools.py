"""Claude SDK MCP adapters over the framework-independent business services."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from functools import partial
import json
from typing import Any
import anyio
from claude_agent_sdk import tool, create_sdk_mcp_server
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from src.services.container import Services
from src.services.errors import ServiceError

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


def tool_result(payload: dict[str, Any], *, error=False):
    # SDK custom tools use the snake-case is_error field. It becomes MCP isError.
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, default=_json_default, ensure_ascii=False),
            }
        ],
        "is_error": error,
    }


def build_mcp_tools(services: Services):
    async def invoke(schema, args, operation):
        try:
            values = schema.model_validate(args).model_dump()
            result = await anyio.to_thread.run_sync(partial(operation, **values))
            return tool_result({"ok": True, "data": result})
        except ValidationError:
            return tool_result(
                {"ok": False, "error": "Invalid tool arguments."}, error=True
            )
        except ServiceError as error:
            return tool_result({"ok": False, "error": str(error)}, error=True)
        except Exception:
            return tool_result(
                {"ok": False, "error": "Tool execution failed."}, error=True
            )

    @tool(
        "query_telemetry_db",
        "Query historical synthetic fleet observations using T-SQL SELECT against FDE_VIEWS.VW_ACTIVE_FLEET. Columns: Timestamp, Latitude, Longitude, Current_Temperature_C, Cargo_Condition_Code, Risk_Classification, Delay_Probability, Port_Congestion_Level, Route_Risk_Index. Return at most the configured row limit. These records are not live shipments.",
        TelemetryArguments.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def telemetry(args):
        def operation(sql_query):
            result = services.telemetry.query(sql_query)
            return {
                **asdict(result),
                "observation_type": "historical_synthetic",
                "returned_rows": len(result.rows),
            }

        return await invoke(TelemetryArguments, args, operation)

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


def create_business_mcp_server(services: Services):
    return create_sdk_mcp_server(
        name=SERVER_NAME, version="0.3.0", tools=build_mcp_tools(services)
    )
