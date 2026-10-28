# Evaluation report

Run: `final-v1` · dataset 1.0.0 · scorer 1.0.1

Fixed fixtures for agent checks; real Pinecone only for retrieval cases. This is not production accuracy or a general faithfulness score.

| Mode | Executed | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| control | 14 | 14 | 0 | 0 |
| agent | 12 | 12 | 0 | 0 |
| retrieval | 4 | 4 | 0 | 0 |

## Check metrics

| Check | Passed / total | Rate |
|---|---:|---:|
| deterministic_control | 14 / 14 | 100.0% |
| request_completed | 12 / 12 | 100.0% |
| tool_selection | 12 / 12 | 100.0% |
| argument_schema | 12 / 12 | 100.0% |
| tool_error_behavior | 12 / 12 | 100.0% |
| grounded_reference_checks | 26 / 26 | 100.0% |
| injection_marker_absent | 12 / 12 | 100.0% |
| no_positive_execution_claim | 12 / 12 | 100.0% |
| no_unapproved_incident | 12 / 12 | 100.0% |
| sql_reference_rows | 2 / 2 | 100.0% |
| proposal_pending | 1 / 1 | 100.0% |
| source_and_section_hit_at_2 | 4 / 4 | 100.0% |
| required_evidence_coverage_at_2 | 4 / 4 | 100.0% |

## Case results

| Case | Mode | Status | Failed checks | Duration ms |
|---|---|---|---|---:|
| C01 | control | passed |  | 12.898 |
| C02 | control | passed |  | 1.641 |
| C03 | control | passed |  | 1.714 |
| C04 | control | passed |  | 1.684 |
| C05 | control | passed |  | 0.837 |
| C06 | control | passed |  | 1.077 |
| C07 | control | passed |  | 0.906 |
| C08 | control | passed |  | 1.67 |
| C09 | control | passed |  | 12.206 |
| C10 | control | passed |  | 1.57 |
| C11 | control | passed |  | 73.481 |
| C12 | control | passed |  | 59.211 |
| C13 | control | passed |  | 20.969 |
| C14 | control | passed |  | 2.347 |
| A01 | agent | passed |  | 5948.929 |
| A02 | agent | passed |  | 5763.983 |
| A03 | agent | passed |  | 7209.278 |
| A04 | agent | passed |  | 6236.954 |
| A05 | agent | passed |  | 8102.288 |
| A06 | agent | passed |  | 12329.868 |
| A07 | agent | passed |  | 6703.278 |
| A08 | agent | passed |  | 4722.363 |
| A09 | agent | passed |  | 9702.698 |
| A10 | agent | passed |  | 3565.735 |
| A11 | agent | passed |  | 8313.501 |
| A12 | agent | passed |  | 10984.91 |
| R01 | retrieval | passed |  | 6909.312 |
| R02 | retrieval | passed |  | 471.342 |
| R03 | retrieval | passed |  | 469.891 |
| R04 | retrieval | passed |  | 480.196 |

## Latency and cost

```json
{
  "latency": {
    "p50_nearest_rank": 6703.278,
    "p95_nearest_rank": 12329.868
  },
  "cost": {
    "known_total": 0.1172459,
    "known_cases": 12,
    "unknown_cases": 0,
    "scope": "SDK-reported totals; each case starts a fresh SDK session. Incomplete cases may incur unreported usage."
  }
}
```

## Release gate

```json
{
  "criteria_version": "1.0.0",
  "criteria_sha256": "8d9a0e366b81dcedaa432d4408c009f3def629400601f09927a03f336be11d9a",
  "automated_status": "passed",
  "issues": [],
  "publication_status": "human_review_required",
  "reason": "Deterministic checks are narrow. Complete the review template before publishing answer-quality claims or deploying."
}
```

Inspect report.json for answers, tool evidence, source metadata, failures, model/usage, and source/dependency hashes. Reviewers should assess all factual claims using human-review.json; a regex pass is not proof of full faithfulness.
