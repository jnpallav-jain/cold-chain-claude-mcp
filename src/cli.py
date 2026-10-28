"""CLI using the same runner, prompt, and events as the Streamlit application."""

import argparse
import asyncio
import json
from src.orchestrator import AgentRunner, AgentSession


async def run_question(runner, session, question, *, json_events=False):
    answer = ""
    failed = False
    async for event in runner.stream_turn(session, question):
        if json_events:
            print(
                json.dumps({"kind": event.kind, "data": event.data}, default=str),
                flush=True,
            )
        elif event.kind == "tool_start":
            print(f"[tool] {event.data['name']}", flush=True)
        elif event.kind == "complete":
            answer = event.data["text"]
            print(answer, flush=True)
        elif event.kind in {"error", "audit_warning"}:
            print(event.data["message"], flush=True)
        if event.kind == "error":
            failed = True
    return not failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    parser.add_argument("--json-events", action="store_true")
    args = parser.parse_args()
    runner, session = AgentRunner(), AgentSession()
    if args.question:
        if not asyncio.run(
            run_question(runner, session, args.question, json_events=args.json_events)
        ):
            raise SystemExit(1)
        return
    print("Cold-Chain Claude MCP. /reset starts a fresh conversation; /quit exits.")
    while True:
        try:
            question = input("Dispatcher > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question == "/quit":
            break
        if question == "/reset":
            session.reset()
            print("New conversation started.")
            continue
        if question:
            asyncio.run(
                run_question(runner, session, question, json_events=args.json_events)
            )


if __name__ == "__main__":
    main()
