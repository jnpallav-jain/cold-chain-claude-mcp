# Part 6 completion — October 28, 2026

Implemented and ran a versioned evaluation harness. **Part 7 has not started.**

## Measured baseline

| Check | Result | Scope |
|---|---:|---|
| Deterministic controls | 14/14 | Fixed SQL rows/boundaries, denials, schemas, limits, approvals, sessions |
| Live agent cases | 12/12 | Claude with fixed synthetic telemetry and controlled SOP/weather evidence |
| Tool-selection cases | 12/12 | Required/allowed tool sets, including one intentionally no-tool case |
| Selected grounding/citation reference checks | 26/26 | Narrow patterns, not a full faithfulness score |
| Live retrieval cases | 4/4 | Expected SOP source/section and clause evidence in Pinecone top two |
| Native SQL supplement | Passed | Real isolated database permissions, timeout, cancellation, recovery |
| Automated tests | 79 passed | Existing functionality plus evaluator/scorer regressions |

One generation run of 12 fresh SDK sessions reported **$0.1172459** in Claude usage. Agent case latency was **6.70 seconds p50** and **12.33 seconds p95**, using nearest-rank percentiles. These are small fixed-fixture test observations, not production performance or a general accuracy claim. Alias: `sonnet`; actual reported model usage is retained per case.

The SQL supplement used a one-second test profile: native timeout **1.038 seconds**, explicit cancellation **0.249 seconds**, zero active server requests after stopping, and successful subsequent queries. Production default query timeout remains three seconds.

## Reports and reproducibility

- `docs/evals/final-v1/report.json` and `report.md`: corrected scoring and automatic regression gate.
- `docs/evals/live-baseline-v1/`: original generation, retrieval, and native SQL results, including the original scorer failure.
- `docs/evals/REVIEW_NOTES.md`: AI-assisted qualitative concerns, explicitly not an independent human review.
- `docs/evals/final-v1/human-review.json`: unfilled human review template.
- `evals/v1/cases.json`: 30 cases, dataset 1.0.0 and scorer 1.0.1.
- `docs/PART6.md`: commands, fixtures, scoring definitions, budgets, and limitations.

The initial scorer marked “No incident was created” as a positive execution claim. A negation regression test and scorer 1.0.1 fixed it. The model had correctly left one pending proposal and zero incidents. Rescoring reused saved answers/evidence, without extra model requests, retrieval, or SQL execution. Questions and expected evidence did not change. The original failed report remains available.

Generation and scoring provenance are separate, including Git commit, source/prompt/dataset/dependency hashes, Python version, model usage, and timestamps. Final scoring was recorded from clean source commit `0f039a5`; the generation provenance retains the earlier working-tree hashes. Reports refuse overwrites. Default offline runs explicitly skip the 16 live cases; they cannot masquerade as full-suite passes.

After inspecting the baseline, regression criteria were recorded: all 30 defined cases and critical checks must pass, with native SQL verification. The automatic gate passes for this recorded baseline. An offline/partial run fails full-coverage gating even when its selected cases pass.

## Honest limitations and follow-up

**Human review is pending.** No LLM-judged score or independent human review has been claimed. The publication gate stays `human_review_required`.

One answer (A09) speculates that a 50°C reading might be physically implausible without supporting evidence, despite passing the defined reference checks. It also quotes the requested TOP 20 query without explaining the validator's TOP 10 clamp. Review these before broad answer-quality claims or public deployment. Passing 26 reference patterns does not mean every generated statement is faithful.

Agent SOP passages were controlled fixtures, separate from the four actual retrieval checks. SQLite fixtures do not reproduce SQL Server's optimizer/permissions; native SQL checks are a separate supplement. Normal successful weather-answer quality, statistical uncertainty, repeated-run variability, corpus-wide recall, and real business impact were not measured.

Ruff F/E9, syntax/dependency checks, source-preservation hashes, and configured-secret exclusion checks passed. No original-project files or real operational records were changed. No real driver/manager notification occurred.

Await user confirmation before Part 7: deployment planning and website demo.
