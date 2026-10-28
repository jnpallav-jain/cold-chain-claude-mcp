"""Re-score saved evidence with the current deterministic scorer; makes no model/network calls."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from src.orchestrator import AgentEvent
from src.services.sop import SopPassage
from src.evaluation.scoring import score_agent, score_retrieval
from scripts.evaluate import aggregate, gate, load_cases, markdown, provenance, sha


def rescore(source, output):
    dataset = load_cases()
    cases = {case["id"]: case for case in dataset["cases"]}
    prior = json.loads(source.read_text())
    # A scorer-only revision must not silently change the tasks or expected evidence.
    for row in prior["cases"]:
        current = cases[row["id"]]
        if (
            row["question"] != current["question"]
            or row["expected"] != current["expected"]
        ):
            raise ValueError("Dataset task changed; a new live run is required.")
    output.mkdir(parents=True, exist_ok=False)
    report = deepcopy(prior)
    report["generation_provenance"] = prior.get(
        "generation_provenance", prior["provenance"]
    )
    report["provenance"] = provenance(dataset)
    report["rescore"] = {
        "source_report": str(source),
        "source_report_sha256": sha(source),
        "source_run_id": prior["run_id"],
        "note": "No new generation, tool executions, retrieval, or native SQL checks. Latency/cost/evidence are retained from the source run.",
    }
    report["run_id"] = output.name
    report["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    for row in report["cases"]:
        if row["status"] == "skipped" or "answer" not in row and row["mode"] == "agent":
            continue
        if row["mode"] == "agent":
            events = [
                AgentEvent(item["kind"], item["data"]) for item in row["evidence"]
            ]
            events.append(AgentEvent("complete", {"text": row["answer"]})) if any(
                check["name"] == "request_completed" and check["passed"]
                for check in row["checks"]
            ) else None
            row["checks"], _, _ = score_agent(
                cases[row["id"]],
                events,
                row["approval_proposals"],
                row["incident_count"],
            )
        elif row["mode"] == "retrieval":
            row["checks"] = score_retrieval(
                cases[row["id"]], [SopPassage(**item) for item in row["evidence"]]
            )
        else:
            continue
        row["status"] = (
            "passed" if all(check["passed"] for check in row["checks"]) else "failed"
        )
    report["metrics"] = aggregate(report["cases"])
    report["release_gate"] = gate(report)
    if report.get("native_sql_supplement", {}).get("file"):
        # Keep the source reference rather than pretending native checks were rerun.
        report["native_sql_supplement"]["source_file"] = str(
            source.parent / prior["native_sql_supplement"]["file"]
        )
        report["native_sql_supplement"]["rerun"] = False
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "report.md").write_text(markdown(report))
    review = source.parent / "human-review.json"
    if review.exists():
        (output / "human-review.json").write_bytes(review.read_bytes())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = rescore(args.source, args.output)
    print(
        json.dumps(
            {
                mode: report["metrics"][mode]
                for mode in ["control", "agent", "retrieval"]
            },
            indent=2,
        )
    )
    if any(row["status"] == "failed" for row in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
