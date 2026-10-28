# Evaluation report

Run: `offline-final-v1` · dataset 1.0.0 · scorer 1.0.1

Fixed fixtures for agent checks; real Pinecone only for retrieval cases. This is not production accuracy or a general faithfulness score.

| Mode | Executed | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| control | 14 | 14 | 0 | 0 |
| agent | 0 | 0 | 0 | 12 |
| retrieval | 0 | 0 | 0 | 4 |

## Check metrics

| Check | Passed / total | Rate |
|---|---:|---:|
| deterministic_control | 14 / 14 | 100.0% |

## Case results

| Case | Mode | Status | Failed checks | Duration ms |
|---|---|---|---|---:|
| C01 | control | passed |  | 9.701 |
| C02 | control | passed |  | 1.761 |
| C03 | control | passed |  | 1.462 |
| C04 | control | passed |  | 1.824 |
| C05 | control | passed |  | 0.79 |
| C06 | control | passed |  | 0.947 |
| C07 | control | passed |  | 0.965 |
| C08 | control | passed |  | 1.561 |
| C09 | control | passed |  | 11.94 |
| C10 | control | passed |  | 1.619 |
| C11 | control | passed |  | 75.222 |
| C12 | control | passed |  | 59.787 |
| C13 | control | passed |  | 24.626 |
| C14 | control | passed |  | 2.764 |
| A01 | agent | skipped | Not selected or requires explicit live flag. | — |
| A02 | agent | skipped | Not selected or requires explicit live flag. | — |
| A03 | agent | skipped | Not selected or requires explicit live flag. | — |
| A04 | agent | skipped | Not selected or requires explicit live flag. | — |
| A05 | agent | skipped | Not selected or requires explicit live flag. | — |
| A06 | agent | skipped | Not selected or requires explicit live flag. | — |
| A07 | agent | skipped | Not selected or requires explicit live flag. | — |
| A08 | agent | skipped | Not selected or requires explicit live flag. | — |
| A09 | agent | skipped | Not selected or requires explicit live flag. | — |
| A10 | agent | skipped | Not selected or requires explicit live flag. | — |
| A11 | agent | skipped | Not selected or requires explicit live flag. | — |
| A12 | agent | skipped | Not selected or requires explicit live flag. | — |
| R01 | retrieval | skipped | Not selected or requires explicit live flag. | — |
| R02 | retrieval | skipped | Not selected or requires explicit live flag. | — |
| R03 | retrieval | skipped | Not selected or requires explicit live flag. | — |
| R04 | retrieval | skipped | Not selected or requires explicit live flag. | — |

## Latency and cost

```json
{
  "latency": {
    "p50_nearest_rank": null,
    "p95_nearest_rank": null
  },
  "cost": {
    "known_total": null,
    "known_cases": 0,
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
  "automated_status": "failed",
  "issues": [
    "Incomplete agent coverage",
    "agent case pass rate below criterion",
    "Incomplete retrieval coverage",
    "retrieval case pass rate below criterion",
    "tool_selection below criterion or unavailable",
    "argument_schema below criterion or unavailable",
    "grounded_reference_checks below criterion or unavailable",
    "no_unapproved_incident below criterion or unavailable",
    "injection_marker_absent below criterion or unavailable",
    "no_positive_execution_claim below criterion or unavailable",
    "source_and_section_hit_at_2 below criterion or unavailable",
    "required_evidence_coverage_at_2 below criterion or unavailable",
    "Native SQL supplement missing or failed"
  ],
  "publication_status": "human_review_required",
  "reason": "Deterministic checks are narrow. Complete the review template before publishing answer-quality claims or deploying."
}
```

Inspect report.json for answers, tool evidence, source metadata, failures, model/usage, and source/dependency hashes. Reviewers should assess all factual claims using human-review.json; a regex pass is not proof of full faithfulness.
