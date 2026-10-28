# Evaluation report

Run: `offline-baseline-v1` · dataset 1.0.0 · scorer 1.0.0

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
| C01 | control | passed |  | 13.984 |
| C02 | control | passed |  | 1.944 |
| C03 | control | passed |  | 1.823 |
| C04 | control | passed |  | 1.996 |
| C05 | control | passed |  | 0.929 |
| C06 | control | passed |  | 1.125 |
| C07 | control | passed |  | 1.21 |
| C08 | control | passed |  | 2.345 |
| C09 | control | passed |  | 12.381 |
| C10 | control | passed |  | 1.977 |
| C11 | control | passed |  | 79.7 |
| C12 | control | passed |  | 58.749 |
| C13 | control | passed |  | 20.85 |
| C14 | control | passed |  | 2.232 |
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
  "automated_status": "baseline_only",
  "publication_status": "human_review_required",
  "reason": "Baseline first; release criteria not yet established."
}
```

Inspect report.json for answers, tool evidence, source metadata, failures, model/usage, and source/dependency hashes. Reviewers should assess all factual claims using human-review.json; a regex pass is not proof of full faithfulness.
