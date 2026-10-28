"""CLI using the same runner, prompt, and events as the Streamlit application."""

import argparse
import asyncio
import json
from getpass import getpass
from src.services.errors import ServiceError
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


def review_proposals(runner, session):
    service = runner.services.approvals
    if service is None or not service.configured:
        print("Configure an operator first: python -m scripts.configure_operator")
        return
    try:
        proposals = service.list_for_session(session.id)
        print(json.dumps(proposals, indent=2))
        pending = [item for item in proposals if item["status"] == "pending"]
        if not pending:
            print("No pending proposals in this conversation.")
            return
        proposal_id = input("Proposal ID (blank cancels) > ").strip()
        proposal = next(
            (item for item in pending if item["proposal_id"] == proposal_id), None
        )
        if proposal is None:
            return
        choice = input("Type approve or reject for this exact proposal > ").strip()
        operator = input("Operator > ").strip()
        password = getpass("Operator password (never put this in chat): ")
        outcome = service.decide(
            session.id,
            proposal_id,
            proposal["digest"],
            choice,
            operator=operator,
            password=password,
        )
        print(json.dumps(outcome, indent=2))
    except ServiceError as error:
        print(str(error))


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
    print(
        "Cold-Chain Claude MCP. /reset starts a fresh conversation; /approvals reviews simulated proposals; /quit exits."
    )
    while True:
        try:
            question = input("Dispatcher > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question == "/quit":
            break
        if question == "/approvals":
            review_proposals(runner, session)
            continue
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
