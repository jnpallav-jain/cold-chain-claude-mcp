"""Live Part 5 check: Claude proposal, real SQL audit, temporary operator, local simulation only."""

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import secrets
import sqlite3
from pydantic import SecretStr
from tempfile import TemporaryDirectory
from sqlalchemy import text
from src.config import get_settings
from src.services.container import get_services
from src.services.approvals import ApprovalService, password_hash
from src.services.database import create_sql_engine
from src.services.errors import ServiceError
from src.orchestrator import AgentRunner, AgentSession


async def verify(output):
    original_settings = get_settings()
    password = secrets.token_urlsafe(24)
    settings = original_settings.model_copy(
        update={
            "approval_password_hash": SecretStr(password_hash(password)),
            "approval_operator": "verification-operator",
        }
    )
    with TemporaryDirectory(prefix="cold-chain-part5-") as directory:
        approvals = ApprovalService(settings, path=Path(directory) / "approval.sqlite3")
        services = replace(get_services(), approvals=approvals)
        runner, session = AgentRunner(settings, services), AgentSession()
        events = []
        async for event in runner.stream_turn(
            session,
            "Use telemetry to assess the synthetic historical temperature breaches above 4 C and retrieve the applicable SOP. "
            "Then propose one SIMULATED internal incident escalation for human review, with supporting telemetry and an SOP filename/section citation. "
            "Do not approve or execute it. Explicitly explain that the proposal is pending human approval and no external notification was sent.",
        ):
            if event.kind in {
                "tool_start",
                "tool_result",
                "complete",
                "error",
                "audit_warning",
            }:
                events.append(event)
                print(event.kind, flush=True)
        if any(event.kind in {"error", "audit_warning"} for event in events):
            raise RuntimeError("Live request or audit failed.")
        complete = next(event.data for event in events if event.kind == "complete")
        called = {event.data["name"] for event in events if event.kind == "tool_start"}
        required = {
            "mcp__coldchain__query_telemetry_db",
            "mcp__coldchain__search_compliance_sop",
            "mcp__coldchain__propose_incident_escalation",
        }
        assert required.issubset(called)
        assert not any(
            event.data.get("is_error")
            for event in events
            if event.kind == "tool_result"
        )
        proposals = approvals.list_for_session(session.id)
        assert len(proposals) == 1 and proposals[0]["status"] == "pending"
        proposal = proposals[0]
        with sqlite3.connect(approvals.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0
        args = (session.id, proposal["proposal_id"], proposal["digest"], "approve")
        for sid, candidate_password in [
            (session.id, "wrong-verification-password"),
            ("wrong-session", password),
        ]:
            try:
                approvals.decide(
                    sid,
                    *args[1:],
                    operator="verification-operator",
                    password=candidate_password,
                )
            except ServiceError:
                pass
            else:
                raise AssertionError("Invalid approval was accepted")
        outcome = approvals.decide(
            *args, operator="verification-operator", password=password
        )
        duplicate = approvals.decide(
            *args, operator="verification-operator", password=password
        )
        assert (
            outcome["incident_id"] == duplicate["incident_id"]
            and duplicate["duplicate_prevented"]
        )
        trail = approvals.trail(session.id)
        with sqlite3.connect(approvals.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
        engine = create_sql_engine(original_settings, admin=True)
        try:
            with engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT NodeExecuted, Content FROM FDE_VIEWS.AgentAuditLog WHERE SessionID=:session ORDER BY LogID"
                        ),
                        {"session": session.id},
                    )
                    .mappings()
                    .all()
                )
        finally:
            engine.dispose()
        records = [
            {"kind": row["NodeExecuted"], **json.loads(row["Content"])} for row in rows
        ]
        starts = [row for row in records if row["kind"] == "sdk_PreToolUse"]
        ends = [
            row
            for row in records
            if row["kind"] in {"sdk_PostToolUse", "sdk_PostToolUseFailure"}
        ]
        assert len(starts) >= 3 and len(ends) == len(starts)
        assert {row["tool_call_id"] for row in starts} == {
            row["tool_call_id"] for row in ends
        }
        assert all(
            row["latency_ms"] is not None and row["status"] == "success" for row in ends
        )
        assert all("output" in row for row in ends)
        request_end = next(row for row in records if row["kind"] == "request_end")
        assert (
            request_end["status"] == "success"
            and request_end["audit_failures_before_end"] == 0
        )
        report = {
            "status": "passed",
            "scope": "One live synthetic proposal scenario; not an evaluation score.",
            "model_setting": settings.claude_model,
            "actual_models": list(complete["model_usage"]),
            "tools_called": sorted(called),
            "sql_audit_events": len(records),
            "correlated_hook_calls": len(ends),
            "tool_timings_ms": [
                {
                    "name": row["name"],
                    "latency_ms": row["latency_ms"],
                    "status": row["status"],
                }
                for row in ends
            ],
            "request_duration_ms": request_end["duration_ms"],
            "sdk_reported_cost_usd": complete["cost_usd"],
            "usage": complete["usage"],
            "no_incident_before_human_approval": True,
            "invalid_credentials_blocked": True,
            "wrong_session_blocked": True,
            "authenticated_approval_created_one_simulated_incident": True,
            "duplicate_execution_prevented": True,
            "decision_events": [row["event"] for row in trail],
            "external_notification": False,
            "operator_credentials": "Random temporary test identity; never sent to Claude, not installed into .env; temporary ledger removed after verification.",
            "cost_note": "SDK-reported total retained without computing cumulative-session deltas.",
        }
        if output:
            output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "--live required; sends approved synthetic fleet/SOP test evidence to Claude and incurs usage"
        )
    asyncio.run(verify(args.output))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "Part 5 verification failed; raw SDK diagnostics are not displayed.",
                }
            )
        )
        raise SystemExit(1)
