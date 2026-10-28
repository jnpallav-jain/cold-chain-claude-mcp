# Part 6 — repeatable evaluations

Implemented October 28, 2026. The harness separates controls, agent behavior with fixed evidence, and actual vector retrieval. All scores include their denominators and scope. This phase adds no public deployment.

## Commands

From the project root:

```bash
# Offline only; no model, Pinecone, weather, or SQL Server calls.
.venv/bin/python -m scripts.evaluate

# All 30 cases plus native SQL verification. Paid model calls; authorized test evidence only.
.venv/bin/python -m scripts.evaluate --live-agent --live-retrieval --live-sql

# Selected cases: other cases are reported as skipped, not passed.
.venv/bin/python -m scripts.evaluate --live-agent --case A02 --case A12

# Re-score preserved answers/evidence after a scorer-only correction, with no API usage.
.venv/bin/python -m scripts.rescore_evaluation \
  --source docs/evals/live-baseline-v1/report.json \
  --output docs/evals/my-new-rescore
```

Default output uses a fresh timestamped directory under `docs/evals/`. `--output` can specify a new directory, but existing directories are never overwritten. Failed cases cause a nonzero exit code; an offline run can succeed while its full-coverage release gate fails because live cases were skipped. No skipped case becomes a pass.

Each live agent case uses a fresh application/SDK session with an SDK budget of $0.15 by default, eight turns, and a 90-second request timeout. Twelve case budgets total $1.80, not a hard provider billing cap; interrupted runs may have unreported usage. Cases run sequentially. No application API keys or real operator credentials appear in cases or reports.

## Evidence boundaries

`src/evaluation/fixtures.py` loads four synthetic rows into a private SQLite database and attaches its schema as `FDE_VIEWS`. It uses the real production telemetry validator/executor and MCP adapters, with SQLite SQL generation supported by the existing test adapter. This does not reproduce SQL Server permissions or its query optimizer. `--live-sql` separately runs `verify_guardrails` against the already-isolated SQL Server; native timeout/cancellation evidence is retained outside the 30-case denominator.

Weather is fixed synthetic data or a controlled error; no Open-Meteo request is made. Controlled SOP evidence is selected from the existing document, with explicit variants for no passages and malicious embedded instructions. These injected passages isolate answer behavior; they are not measurements of Pinecone retrieval. The four R cases query the actual configured BGE-M3 dense/Pinecone index read-only, without changing ingestion or index contents.

Audit output goes to an isolated in-memory sink. Approval proposals use a temporary local ledger with a random test operator; it is deleted afterward. Chat approval cannot execute the proposal. No real human password is needed and no external notifications are sent. SDK runtime transcripts remain in the existing ignored private runtime directories; reports do not include authentication configuration.

## Scoring and provenance

Cases and expected behavior are in `evals/v1/cases.json`. Reports contain:

- Case-level assertions, failures, actual answers, captured tool arguments/results, source metadata, proposal state, latency, and available usage/cost.
- Model alias and actual model usage per case; each case starts fresh, allowing known SDK cost totals to be summed without resumption double counting. Unreported costs remain unknown.
- Dataset/scorer versions; hashes of dataset, telemetry, weather, SOP, prompt, dependency lock, runtime/evaluator source; Git commit and tracked working-tree state; Python and installed dependency versions.
- Separate mode denominators, nearest-rank agent latency percentiles, and an explicit human-review template.

C cases cover exact fixture SQL results and boundaries, unsupported SQL, schemas, cancellation handles, shared call budget, approval credentials/session binding, rejection/expiry, session reset, and an injected SDK maximum-turn terminal error. Maximum-turn handling is not a live forced-loop benchmark. Native SQL behavior is measured separately.

A cases check expected tool sets, Pydantic argument shapes, expected success/failure, selected reference facts/citations, known injection markers, narrowly recognizable positive execution claims, exact SQL rows where specified, and absence of unapproved incidents. Argument-schema pass rates are case-level and include the no-tool case; do not call them a measured per-call SQL-intent accuracy. SQL result checks are distinct from answer wording checks.

R cases require the expected source/section in the top two passages and coverage of selected clause terms. This is source/section hit@2 and reference evidence coverage@2, not comprehensive retrieval recall, MRR, or ranking precision.

**Faithfulness limit:** reference patterns test selected facts; they do not parse or judge every answer claim, catch every negation, verify all inequalities semantically, or prove completeness. No LLM-as-judge metric is used. Actual human review remains pending; no human-reviewed faithfulness score is published. `docs/evals/REVIEW_NOTES.md` records AI-assisted qualitative concerns the patterns did not detect.

## Baseline and regression criteria

The initial live report is retained in `docs/evals/live-baseline-v1/`. It has one scorer false positive on the statement “No incident was created.” Scorer 1.0.1 fixes this issue; the `rescore_evaluation` command recomputes checks using saved evidence without regenerating answers, rerunning retrieval/native SQL, or incurring more Claude cost. Generation and scoring provenance are stored separately. It refuses to rescore if questions/expectations changed.

Regression criteria were established after inspecting this baseline: all 14 control, 12 agent, and four retrieval cases must execute and pass; critical named checks must pass; the native SQL supplement must pass. Missing coverage fails the automatic gate. These thresholds define regressions on this small set, not production release approval. The publication gate remains `human_review_required` and does not auto-certify manual review from an edited file.

The current completion report points to the final rescored report. Review an actual human's completed `human-review.json` before using broad answer-quality claims. Do not edit the old report or remove failed cases to improve a score. A changed prompt, model, dataset, or tool implementation calls for a new generation run; rescoring alone is only for scorer corrections on the same evidence.
