"""Repeatable versioned evaluations. Default is offline; live flags are explicit and bounded."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import secrets
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from pydantic import SecretStr
from src.config import PROJECT_ROOT, get_settings
from src.evaluation.fixtures import DATASET, SOP_PATH, FixtureEnvironment
from src.evaluation.controls import run_control
from src.evaluation.scoring import score_agent, score_retrieval
from src.orchestrator import AgentRunner, AgentSession
from src.security.redaction import Redactor
from src.services.approvals import password_hash
from src.services.sop import SopService


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(dataset):
    paths = [
        DATASET / "cases.json",
        DATASET / "telemetry.csv",
        DATASET / "weather.json",
        SOP_PATH,
        PROJECT_ROOT / "src/prompts/system_prompt.txt",
        PROJECT_ROOT / "requirements.lock.txt",
    ]
    paths += list((PROJECT_ROOT / "src/evaluation").glob("*.py")) + [
        PROJECT_ROOT / "scripts/evaluate.py"
    ]
    paths += [
        path for path in (PROJECT_ROOT / "src").rglob("*.py") if path not in paths
    ]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()
    )
    return {
        "dataset_version": dataset["version"],
        "scorer_version": dataset["scorer_version"],
        "git_commit": commit,
        "working_tree_dirty_at_run": dirty,
        "python": platform.python_version(),
        "file_sha256": {
            str(path.relative_to(PROJECT_ROOT)): sha(path) for path in paths
        },
        "dependencies": {
            dist.metadata["Name"]: dist.version
            for dist in importlib.metadata.distributions()
        },
    }


def load_cases(path=DATASET / "cases.json"):
    dataset = json.loads(path.read_text())
    cases = dataset["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    for case in cases:
        if (
            case["mode"] not in {"control", "agent", "retrieval"}
            or not case["expected"]
            or not case["question"]
        ):
            raise ValueError("Invalid evaluation case")
    return dataset


def aggregate(results):
    metrics = {}
    for mode in ["control", "agent", "retrieval"]:
        selected = [row for row in results if row["mode"] == mode]
        ran = [row for row in selected if row["status"] != "skipped"]
        passed = sum(row["status"] == "passed" for row in ran)
        metrics[mode] = {
            "planned": len(selected),
            "executed": len(ran),
            "passed": passed,
            "failed": len(ran) - passed,
            "skipped": len(selected) - len(ran),
            "case_pass_rate": passed / len(ran) if ran else None,
        }
    named = {}
    for row in results:
        for check in row.get("checks", []):
            key = (
                "grounded_reference_checks"
                if check["name"].startswith("reference:")
                else check["name"]
            )
            values = named.setdefault(key, {"passed": 0, "total": 0})
            values["passed"] += bool(check["passed"])
            values["total"] += 1
    for values in named.values():
        values["rate"] = values["passed"] / values["total"]
    metrics["checks"] = named
    agents = [
        row for row in results if row["mode"] == "agent" and row["status"] != "skipped"
    ]
    latencies = sorted(row["latency_ms"] for row in agents)
    costs = [row["cost_usd"] for row in agents if row.get("cost_usd") is not None]
    metrics["agent_latency_ms"] = {
        "p50_nearest_rank": latencies[math.ceil(0.5 * len(latencies)) - 1]
        if latencies
        else None,
        "p95_nearest_rank": latencies[math.ceil(0.95 * len(latencies)) - 1]
        if latencies
        else None,
    }
    metrics["agent_cost_usd"] = {
        "known_total": sum(costs) if costs else None,
        "known_cases": len(costs),
        "unknown_cases": len(agents) - len(costs),
        "scope": "SDK-reported totals; each case starts a fresh SDK session. Incomplete cases may incur unreported usage.",
    }
    return metrics


def gate(report):
    path = DATASET / "release_criteria.json"
    if not path.exists():
        return {
            "automated_status": "baseline_only",
            "publication_status": "human_review_required",
            "reason": "Baseline first; release criteria not yet established.",
        }
    criteria = json.loads(path.read_text())
    issues = []
    metrics = report["metrics"]
    for mode in ["control", "agent", "retrieval"]:
        if metrics[mode]["executed"] != criteria["required_cases"][mode]:
            issues.append(f"Incomplete {mode} coverage")
        rate = metrics[mode]["case_pass_rate"]
        if rate is None or rate < criteria["minimum_case_pass_rate"][mode]:
            issues.append(f"{mode} case pass rate below criterion")
    for name, minimum in criteria["minimum_check_rates"].items():
        value = metrics["checks"].get(name, {}).get("rate")
        if value is None or value < minimum:
            issues.append(f"{name} below criterion or unavailable")
    if (
        criteria.get("require_native_sql_supplement")
        and report.get("native_sql_supplement", {}).get("status") != "passed"
    ):
        issues.append("Native SQL supplement missing or failed")
    return {
        "criteria_version": criteria["version"],
        "criteria_sha256": sha(path),
        "automated_status": "passed" if not issues else "failed",
        "issues": issues,
        "publication_status": "human_review_required",
        "reason": "Deterministic checks are narrow. Complete the review template before publishing answer-quality claims or deploying.",
    }


def markdown(report):
    lines = [
        "# Evaluation report",
        "",
        f"Run: `{report['run_id']}` · dataset {report['provenance']['dataset_version']} · scorer {report['provenance']['scorer_version']}",
        "",
        "Fixed fixtures for agent checks; real Pinecone only for retrieval cases. This is not production accuracy or a general faithfulness score.",
        "",
        "| Mode | Executed | Passed | Failed | Skipped |",
        "|---|---:|---:|---:|---:|",
    ]
    for mode in ["control", "agent", "retrieval"]:
        row = report["metrics"][mode]
        lines.append(
            f"| {mode} | {row['executed']} | {row['passed']} | {row['failed']} | {row['skipped']} |"
        )
    lines += [
        "",
        "## Check metrics",
        "",
        "| Check | Passed / total | Rate |",
        "|---|---:|---:|",
    ]
    for name, row in report["metrics"]["checks"].items():
        lines.append(
            f"| {name} | {row['passed']} / {row['total']} | {row['rate']:.1%} |"
        )
    lines += [
        "",
        "## Case results",
        "",
        "| Case | Mode | Status | Failed checks | Duration ms |",
        "|---|---|---|---|---:|",
    ]
    for row in report["cases"]:
        failed = ", ".join(
            item["name"] for item in row.get("checks", []) if not item["passed"]
        )
        lines.append(
            f"| {row['id']} | {row['mode']} | {row['status']} | {failed or row.get('reason', '')} | {row.get('latency_ms', '—')} |"
        )
    lines += [
        "",
        "## Latency and cost",
        "",
        "```json",
        json.dumps(
            {
                "latency": report["metrics"]["agent_latency_ms"],
                "cost": report["metrics"]["agent_cost_usd"],
            },
            indent=2,
        ),
        "```",
        "",
        "## Release gate",
        "",
        "```json",
        json.dumps(report["release_gate"], indent=2),
        "```",
        "",
        "Inspect report.json for answers, tool evidence, source metadata, failures, model/usage, and source/dependency hashes. Reviewers should assess all factual claims using human-review.json; a regex pass is not proof of full faithfulness.",
    ]
    return "\n".join(lines) + "\n"


async def evaluate(args):
    dataset = load_cases()
    ids = set(args.case or [])
    unknown = ids - {case["id"] for case in dataset["cases"]}
    if unknown:
        raise ValueError("Unknown evaluation case IDs")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    original = get_settings()
    password = secrets.token_urlsafe(24)
    settings = original.model_copy(
        update={
            "approval_operator": "evaluation-operator",
            "approval_password_hash": SecretStr(password_hash(password)),
            "claude_max_budget_usd": args.case_budget_usd,
            "claude_max_turns": 8,
            "claude_request_timeout": 90,
        }
    )
    redactor = Redactor(settings)
    report = {
        "run_id": output.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance(dataset),
        "model_setting": settings.claude_model,
        "limits": {
            "case_budget_usd": args.case_budget_usd,
            "request_timeout_seconds": 90,
            "max_turns": 8,
        },
        "evidence_modes": {
            "telemetry": "Four fixed synthetic observations; real production SQL parser/executor on SQLite fixture, not SQL Server.",
            "weather": "Fixed synthetic weather or injected failure; never live weather.",
            "agent_sop": "Controlled SOP section passages or injected empty/malicious text; not vector retrieval.",
            "retrieval": "Actual BGE-M3/Pinecone when --live-retrieval is enabled.",
            "audit": "Isolated in-memory sink; no production audit writes.",
            "approval": "Private temporary local ledger and random operator; no external notification.",
        },
        "cases": [],
    }
    reviews = []
    try:
        with TemporaryDirectory(prefix="cold-chain-evaluation-") as temporary:
            for case in dataset["cases"]:
                row = {
                    "id": case["id"],
                    "mode": case["mode"],
                    "category": case["category"],
                    "question": case["question"],
                    "expected": case["expected"],
                }
                report["cases"].append(row)
                if (
                    (ids and case["id"] not in ids)
                    or (case["mode"] == "agent" and not args.live_agent)
                    or (case["mode"] == "retrieval" and not args.live_retrieval)
                ):
                    row.update(
                        status="skipped",
                        reason="Not selected or requires explicit live flag.",
                    )
                    continue
                start = time.monotonic()
                env = None
                try:
                    if case["mode"] == "retrieval":
                        passages = SopService(settings).search(case["question"])
                        row["checks"] = score_retrieval(case, passages)
                        row["evidence"] = [
                            {"text": item.text, "metadata": item.metadata}
                            for item in passages
                        ]
                    else:
                        env = FixtureEnvironment(
                            settings,
                            Path(temporary) / case["id"],
                            case.get("fixture", "normal"),
                        )
                        if case["mode"] == "control":
                            row["evidence"] = await run_control(
                                case, env, settings, password
                            )
                            row["checks"] = [
                                {"name": "deterministic_control", "passed": True}
                            ]
                        else:
                            runner, session = (
                                AgentRunner(settings, env.services),
                                AgentSession(),
                            )
                            events = [
                                event
                                async for event in runner.stream_turn(
                                    session, case["question"]
                                )
                            ]
                            proposals = env.approvals.list_for_session(session.id)
                            with sqlite3.connect(env.approvals.path) as conn:
                                incident_count = conn.execute(
                                    "SELECT COUNT(*) FROM incidents"
                                ).fetchone()[0]
                            checks, answer, completion = score_agent(
                                case, events, proposals, incident_count
                            )
                            row.update(
                                checks=checks,
                                answer=answer,
                                cost_usd=completion.get("cost_usd"),
                                usage=completion.get("usage"),
                                actual_model_usage=completion.get("model_usage"),
                                evidence=[
                                    {"kind": event.kind, "data": event.data}
                                    for event in events
                                    if event.kind
                                    in {
                                        "tool_start",
                                        "tool_result",
                                        "error",
                                        "audit_warning",
                                    }
                                ],
                                approval_proposals=proposals,
                                incident_count=incident_count,
                            )
                            reviews.append(
                                {
                                    "case_id": case["id"],
                                    "reviewer": None,
                                    "reviewed_at": None,
                                    "faithful": None,
                                    "unsupported_claims": [],
                                    "notes": "",
                                    "rubric": case["expected"]["review_rubric"],
                                }
                            )
                    row["status"] = (
                        "passed"
                        if all(check["passed"] for check in row["checks"])
                        else "failed"
                    )
                except Exception as error:
                    row.update(
                        status="failed",
                        checks=[
                            {
                                "name": "case_execution",
                                "passed": False,
                                "details": type(error).__name__,
                            }
                        ],
                        reason="Case execution failed; inspect safe error type and evidence. No raw transport diagnostics retained.",
                    )
                finally:
                    if env:
                        env.close()
                    row["latency_ms"] = round((time.monotonic() - start) * 1000, 3)
                print(f"{case['id']} {row['status']}", flush=True)
                # Preserve partial case results if an interrupted run needs diagnosis.
                (output / "partial.json").write_text(
                    json.dumps(redactor.data(report), indent=2, default=str) + "\n"
                )
        if args.live_sql:
            native_output = output / "native-sql.json"
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "scripts.verify_guardrails",
                "--live",
                "--output",
                str(native_output),
                cwd=PROJECT_ROOT,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                code = await asyncio.wait_for(process.wait(), timeout=60)
            except TimeoutError:
                process.kill()
                await process.wait()
                code = -1
            report["native_sql_supplement"] = {
                "status": "passed" if code == 0 else "failed",
                "file": "native-sql.json" if native_output.exists() else None,
                "scope": "Real isolated SQL permissions, native timeout/cancellation; separate from 30 case denominator.",
            }
    finally:
        report["metrics"] = aggregate(report["cases"])
        report["release_gate"] = gate(report)
        if report.get("native_sql_supplement", {}).get("status") == "failed":
            report["release_gate"]["automated_status"] = "failed"
        report = redactor.data(report)
        (output / "report.json").write_text(
            json.dumps(report, indent=2, default=str) + "\n"
        )
        (output / "report.md").write_text(markdown(report))
        (output / "human-review.json").write_text(
            json.dumps(
                {
                    "status": "pending",
                    "instruction": "An actual human reviewer fills this file after checking answers against evidence. No human review is implied by automated checks.",
                    "reviews": reviews,
                },
                indent=2,
            )
            + "\n"
        )
        (output / "partial.json").unlink(missing_ok=True)
    return (
        all(row["status"] != "failed" for row in report["cases"])
        and report.get("native_sql_supplement", {}).get("status") != "failed"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-agent",
        action="store_true",
        help="Make paid Claude calls with fixed synthetic/SOP evidence (12 cases, fresh sessions).",
    )
    parser.add_argument(
        "--live-retrieval",
        action="store_true",
        help="Read authorized SOP from existing Pinecone index (no ingestion).",
    )
    parser.add_argument(
        "--live-sql",
        action="store_true",
        help="Add real isolated SQL Server permissions and timeout/cancellation verification.",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="Select case ID; all other cases are explicitly skipped.",
    )
    parser.add_argument("--case-budget-usd", type=float, default=0.15)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "docs/evals"
        / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ"),
    )
    args = parser.parse_args()
    if not 0 < args.case_budget_usd <= 0.5:
        parser.error(
            "Case budget must be in (0, .5]. Twelve default cases have up to $1.80 in SDK budgets, not a provider billing hard cap."
        )
    if not asyncio.run(evaluate(args)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
