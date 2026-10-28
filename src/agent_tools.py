"""Thin LangChain adapters retained until the Part 3 SDK/MCP migration."""

from langchain_core.tools import tool
from src.services.container import get_services
from src.services.errors import ServiceError


@tool
def query_telemetry_db(sql_query: str) -> str:
    """Execute a T-SQL SELECT against FDE_VIEWS.VW_ACTIVE_FLEET.

    Columns: Timestamp, Latitude, Longitude, Current_Temperature_C, Cargo_Condition_Code,
    Risk_Classification, Delay_Probability, Port_Congestion_Level, Route_Risk_Index.
    Fleet observations are historical, not live.
    """
    try:
        result = get_services().telemetry.query(sql_query)
        if not result.rows:
            return "No records matched the query criteria."
        return (
            "COLUMNS: "
            + ", ".join(result.columns)
            + "\n"
            + "\n".join(str(row) for row in result.rows)
        )
    except ServiceError as error:
        return str(error)


@tool
def fetch_corridor_conditions(latitude: float, longitude: float) -> str:
    """Fetch current weather at GPS coordinates and a wind-based demonstration disruption estimate.

    This is not measured traffic congestion and cannot establish causes of historical fleet events.
    """
    try:
        result = get_services().weather.fetch(latitude, longitude)
        return (
            f"GPS: {latitude}, {longitude} | Observed: {result.observed_at}\n"
            f"External Temp: {result.temperature_c}°C | Wind Speed: {result.wind_kmh} km/h\n"
            f"Corridor Risk: {result.status} (Disruption Index: {result.disruption_index}/10)\n{result.interpretation}"
        )
    except ServiceError as error:
        return str(error)


@tool
def search_compliance_sop(query: str) -> str:
    """Retrieve SOP passages for temperature thresholds, breach responses, and rerouting rules."""
    try:
        passages = get_services().sop.search(query)
        if not passages:
            return "No matching compliance clauses found."
        return "\n\n".join(
            f"[Source: {item.metadata.get('source_file', 'SOP')} | Format: {item.metadata.get('file_format', 'RAW')}]\n{item.text}"
            for item in passages
        )
    except ServiceError as error:
        return str(error)
