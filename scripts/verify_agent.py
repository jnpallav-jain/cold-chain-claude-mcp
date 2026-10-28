"""Bounded live Claude SDK smoke check. Sends synthetic fleet/weather/SOP evidence to Anthropic."""

import argparse
import asyncio
import json
from pathlib import Path
from src.orchestrator import AgentRunner, AgentSession
from src.agent_tools import MCP_TOOL_NAMES


async def verify(output):
    runner, session = AgentRunner(), AgentSession()
    events = []
    prompt = (
        "Assess the synthetic historical fleet records with cargo temperatures above 4 C. "
        "Use the telemetry tool first, check current weather at one returned location, and retrieve the relevant SOP. "
        "Recommend conditional actions supported by the SOP, cite its filename, and distinguish current weather from historical fleet data."
    )
    async for event in runner.stream_turn(session, prompt):
        if event.kind in {
            "session",
            "tool_start",
            "tool_result",
            "complete",
            "error",
            "audit_warning",
        }:
            events.append(event)
            # Print event kinds only; no raw SDK diagnostics or secret values.
            print(event.kind, flush=True)
    errors = [event.data for event in events if event.kind == "error"]
    completed = [event.data for event in events if event.kind == "complete"]
    called = {event.data["name"] for event in events if event.kind == "tool_start"}
    if errors or not completed:
        raise RuntimeError(
            "Live agent did not complete. Check credentials, model access, and runtime availability."
        )
    if not set(MCP_TOOL_NAMES[:3]).issubset(called):
        raise RuntimeError("Live smoke question did not exercise all three MCP tools.")
    if any(
        event.data.get("is_error") for event in events if event.kind == "tool_result"
    ):
        raise RuntimeError("A live MCP tool returned an error.")
    answer = completed[-1]["text"]
    if "Cold_Chain_Incident_SOP_v2.md" not in answer:
        raise RuntimeError("Live answer omitted the SOP source filename.")
    initial_tools = [
        event.data.get("available_tools", [])
        for event in events
        if event.kind == "session"
    ]
    if initial_tools and any(
        name in {"Bash", "Read", "Write", "Edit", "Agent", "Task"}
        for name in initial_tools[0]
    ):
        raise RuntimeError("Unexpected built-in tools are exposed by the runtime.")
    first_resume = session.sdk_session_id
    follow = []
    async for event in runner.stream_turn(
        session,
        "Which SOP source did you cite in the previous answer? Answer briefly using the conversation history.",
    ):
        if event.kind in {"complete", "error"}:
            follow.append(event)
    assert follow and follow[-1].kind == "complete", "Follow-up request failed"
    assert session.sdk_session_id == first_resume, (
        "Follow-up did not retain the SDK session"
    )
    assert "Cold_Chain_Incident_SOP_v2.md" in follow[-1].data["text"], (
        "Follow-up did not retain source context"
    )
    report = {
        "sdk": "claude-agent-sdk",
        "model_setting": runner.settings.claude_model,
        "tools_called": sorted(called),
        "runtime_tools": initial_tools[0] if initial_tools else [],
        "tool_error_count": 0,
        "source_cited": True,
        "session_resume_verified": True,
        "first_request_turns": completed[-1]["turns"],
        "first_request_cost_usd": completed[-1]["cost_usd"],
        "followup_cost_usd": follow[-1].data["cost_usd"],
        "usage": completed[-1]["usage"],
        "actual_models": list(completed[-1]["model_usage"]),
        "note": "One live smoke scenario and one follow-up; not an answer-quality evaluation score.",
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
            "--live is required; this sends test evidence to Anthropic and incurs API usage"
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
                    "message": "Agent verification failed; no raw SDK diagnostics are displayed.",
                }
            )
        )
        raise SystemExit(1)
