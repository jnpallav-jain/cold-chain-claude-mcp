"""Case-level deterministic checks with explicit fixture/native boundary."""

from claude_agent_sdk import ResultMessage
from pydantic import SecretStr
from src.agent_tools import build_mcp_tools
from src.orchestrator import AgentRunner, AgentSession
from src.security.execution import BoundedWorkers, RequestBudget, ToolTimedOut
from src.security.sql_policy import SqlPolicyError
from src.services.errors import ServiceError
from src.services.sql_executor import QueryCancellation


async def run_control(case, env, settings, password):
    category = case["category"]
    if category == "sql_result":
        result = env.services.telemetry.query(case["sql"])
        actual = [list(row) for row in result.rows]
        assert actual == case["expected"]["rows"], (
            f"Expected rows {case['expected']['rows']}, got {actual}"
        )
        return {"actual_rows": actual, "sql": case["sql"]}
    if category == "sql_denial":
        try:
            env.services.telemetry.query(case["sql"])
        except SqlPolicyError:
            return {"blocked": True, "sql": case["sql"]}
        raise AssertionError("Forbidden SQL accepted")
    if category == "schema":
        tools = {
            tool.name: tool
            for tool in build_mcp_tools(
                env.services, settings=settings, session_id="evaluation"
            )
        }
        for name, args in [
            ("fetch_corridor_conditions", {"latitude": 999, "longitude": 0}),
            (
                "propose_incident_escalation",
                {
                    "summary": "Synthetic fixture summary",
                    "evidence": "Synthetic evidence only",
                    "sop_reference": "sample.md",
                    "approved": True,
                },
            ),
        ]:
            assert (await tools[name].handler(args))["is_error"]
        good_weather = await tools["fetch_corridor_conditions"].handler(
            {"latitude": 34.05, "longitude": -118.24}
        )
        import json

        weather = json.loads(good_weather["content"][0]["text"])["data"]
        assert weather["temperature_c"] == 25.0 and weather["wind_kmh"] == 12.0
        assert (
            weather["observed_at"] == "2026-01-01 12:00 UTC"
            and "fixture" in weather["interpretation"]
        )
        return {
            "invalid_coordinates_and_approval_field_blocked": True,
            "fixed_weather_values_and_timestamp_verified": True,
        }
    if category == "cancellation":
        import threading

        token, stopped = QueryCancellation(), threading.Event()
        token.attach(stopped.set)

        def operation():
            stopped.wait(1)

        try:
            await BoundedWorkers(1).run(operation, seconds=0.01, cancel=token.cancel)
        except ToolTimedOut:
            assert token.cancel_attempted and stopped.wait(0.2)
            return {
                "caller_timeout_and_cancel_handle": True,
                "scope": "Controlled cancellation handle, not native SQL Server; use --live-sql for native verification.",
            }
        raise AssertionError("Deadline not enforced")
    if category == "budget":
        tools = {
            tool.name: tool
            for tool in build_mcp_tools(
                env.services, settings=settings, budget=RequestBudget(10, 1)
            )
        }
        args = {"query": "temperature"}
        assert not (await tools["search_compliance_sop"].handler(args))["is_error"]
        assert (await tools["search_compliance_sop"].handler(args))["is_error"]
        return {"second_call_blocked": True}
    payload = {
        "summary": "Synthetic fixture incident proposal",
        "evidence": "Historical synthetic observation: 7 C.",
        "sop_reference": "sample.md / Temperature",
    }
    service = env.approvals
    if category in {"approval_auth", "approval_rejection", "session"}:
        proposal = service.propose("first-session", **payload)

        def decide(session="first-session", choice="approve", secret=password):
            return service.decide(
                session,
                proposal["proposal_id"],
                proposal["digest"],
                choice,
                operator="evaluation-operator",
                password=secret,
            )

        def denied(operation):
            try:
                operation()
            except ServiceError:
                return
            raise AssertionError("Unauthorized or disallowed decision accepted")

        if category == "approval_auth":
            denied(lambda: decide(secret="chat approval is not authentication"))
            denied(lambda: decide(session="other-session"))
            first, repeat = decide(), decide()
            assert (
                first["incident_id"] == repeat["incident_id"]
                and repeat["duplicate_prevented"]
            )
        elif category == "approval_rejection":
            assert decide(choice="reject")["status"] == "rejected"
            denied(decide)
            second = service.propose("second-session", **payload)
            service.clock = lambda: second["expires_at_unix"] + 1
            denied(
                lambda: service.decide(
                    "second-session",
                    second["proposal_id"],
                    second["digest"],
                    "approve",
                    operator="evaluation-operator",
                    password=password,
                )
            )
        else:
            session = AgentSession()
            prior = session.id
            session.sdk_session_id = "previous-sdk-id"
            session.reset()
            assert session.id != prior and session.sdk_session_id is None
            assert service.list_for_session(session.id) == []
            denied(lambda: decide(session=session.id))
        return {
            "verified": category,
            "events": [row["event"] for row in service.trail("first-session")],
        }
    if category == "turn_limit":

        class LimitClient:
            def __init__(self, **kwargs):
                assert kwargs["options"].max_turns == settings.claude_max_turns

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def query(self, prompt):
                pass

            async def receive_response(self):
                yield ResultMessage(
                    subtype="error_max_turns",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=settings.claude_max_turns,
                    session_id="fixture-session",
                )

        session = AgentSession(sdk_session_id="prior")
        runner = AgentRunner(
            settings.model_copy(
                update={"anthropic_api_key": SecretStr("offline-evaluation-dummy-key")}
            ),
            env.services,
            client_factory=LimitClient,
        )
        events = [
            event
            async for event in runner.stream_turn(
                session, "Controlled max-turn response"
            )
        ]
        assert any(
            event.kind == "error" and event.data["category"] == "error_max_turns"
            for event in events
        )
        assert session.sdk_session_id is None
        return {
            "sdk_error_handling": "verified with injected terminal error",
            "max_turns": settings.claude_max_turns,
            "scope": "SDK option and error handling, not a live forced loop.",
        }
    raise ValueError("Unknown evaluation control category")
