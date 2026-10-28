# Evaluation dataset v1.0.0

30 authored cases: C01–C14 deterministic controls, A01–A12 live Claude with fixed evidence, R01–R04 real BGE-M3/Pinecone retrieval. Scorer revision 1.0.1 corrects a negation false positive; questions/reference expectations are unchanged. Preserve reports from earlier scorers.

- `telemetry.csv`: four fabricated historical observations copied from this project's sample fixture, not the external Kaggle dataset.
- `weather.json`: a fixed synthetic weather observation, not a live forecast. Success values/timestamp are exercised in C08; A08 injects a controlled failure. This set does not measure normal weather-answer quality.
- `cases.json`: questions, modes, explicit tool expectations, fixture variants, reference patterns, and qualitative review rubrics.
- SOP passages come from the existing local policy document. The agent fixtures inject selected sections directly, so agent scores do not measure vector retrieval. R01–R04 independently query the real index. Reference source/section plus required terms must be present in the top two passages; this is evidence coverage, not labeled corpus-wide recall or ranking precision.
- `release_criteria.json`: regression thresholds established after inspecting the baseline, requiring full coverage, all defined checks, native SQL verification, and separate human review before publication. Thresholds concern this small fixed set only.

Default runs are offline and explicitly skip live cases. Every output directory is new; the harness refuses to overwrite a previous run. Live answers are nondeterministic, even with fixed evidence; preserve repeated runs rather than selecting only favorable results.

The phrase “grounded reference checks” means narrow regular-expression checks of selected expected facts and citations. It does not establish that every claim is supported, that the answer is complete, or that its citation actually entails every sentence. Schema checks validate argument shapes, not query intent. The tool-selection score checks each case's required and allowed tool sets, not an optimal execution sequence. No LLM judge, human-reviewed faithfulness percentage, business KPI, or production accuracy is asserted.
