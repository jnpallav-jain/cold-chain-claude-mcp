# Verification evidence

The recorded local verification completed 92 automated tests and a fresh 30-case evaluation. These are separate suites with different scopes.

- [Browser workflow](browser.json): authenticated sign-in, telemetry/weather/SOP evidence, and a separately authenticated simulated incident approval. Automated browser QA, not independent human answer review.
- [Container readiness](container.json): Linux ARM64 non-root web container, SQL view reads and audit inserts, local BGE-M3 embeddings, actual Pinecone retrieval, and SDK startup without a model request. Native AMD64 cloud deployment remains unverified.
- [Latest evaluation](../evals/part7-runtime-v1/report.json): controls, fixed-evidence live agent cases, actual retrieval, and a separate native SQL supplement.

To rerun the offline tests from the project root:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

See [evaluation methodology](../EVALUATION.md) for paid live checks and interpretation. No production accuracy or human-reviewed faithfulness score is asserted.
