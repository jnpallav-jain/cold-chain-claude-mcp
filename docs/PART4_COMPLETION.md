# Part 4 — Completed

Completed October 28, 2026. Project: `/Users/pallavjain/my-git/AI Engineer/cold-chain-claude-mcp`.

## Implemented

- Replaced SELECT-prefix validation with a fail-closed SQLGlot T-SQL AST policy and canonical SQL regeneration.
- Restricted SQL to one SELECT against the semantic view and its approved nine-column contract. Wildcards expand to those nine columns.
- Rejected multiple statements, joins/subqueries/CTEs, metadata/external objects, variables, unapproved functions, SELECT INTO, comments, hints, and other unsupported constructs before database access.
- Added server TOP clamping, client row limits, query/AST/literal size limits, connection-pool limits, and native SQL statement timeouts.
- Added query-specific cursor cancellation, a backup cancellation timer, and invalidation of cancelled/failed connections.
- Added shared request tool-call budgets, bounded business workers, tool wait deadlines, bounded transient retries, and valid JSON errors for oversized results.
- Added explicit Pinecone vector-query socket deadlines and optional OpenAI embedding request timeouts; local embedding downloads no longer occur during inference.
- Preserved strict SDK MCP exposure and exact-name permissions; tested rejection of built-ins and lookalike/other-server tool names.
- Added targeted credential/connection-detail redaction in outgoing questions, tool results, events, streamed text, and audit content. Streaming tests cover every split point of a configured secret.
- Added a separate bounded audit worker and visible audit failures.

## Verification

- **50 offline tests passed**, including the prior SDK/MCP/frontend/service suite and new SQL, worker-budget, retry, output-cap, and redaction checks.
- The SQL policy suite includes seven supported query examples, 25 rejected statement/construct examples, size/complexity checks, fixed wildcard expansion, and rejection before opening a connection.
- Live permissions allow view SELECT and audit INSERT while denying raw-table SELECT/INSERT/UPDATE/DELETE/ALTER and audit SELECT/UPDATE/DELETE/ALTER.
- A blocked approved SELECT expired under a one-second native timeout test profile in **1.038 seconds**. The application's default statement timeout remains three seconds.
- Explicit native cursor cancellation stopped another blocked query in **0.221 seconds**.
- Both stopped queries left **zero active SQL Server requests** for their connections. The rollback-only test locks were released, synthetic values were unchanged, and a subsequent query succeeded.
- Live SQL/weather/SOP services passed after the Pinecone timeout adapter was corrected and covered by an integration test.
- The previously authorized Claude smoke workflow passed with all three MCP tools, zero tool errors, an SOP citation, and a same-session follow-up. The runtime exposed exactly the three business tools.
- Dependency checks passed with 124 installed packages including project version 0.4.0. Raw credentials and private SDK transcripts remain excluded from Git.

Evidence: `docs/part4-live-check.json`, `docs/part4-service-check.json`, and `docs/part4-agent-check.json`. Operational details and defaults: `docs/PART4.md`.

## Precise limits

Native SQL timeout/cancellation is tested against the local ODBC/SQL Server environment; cleanup latency may vary with driver/network failures. Returned-row caps do not guarantee low query cost.

A timed-out embedding/network Python thread cannot be forcibly killed. It keeps its bounded worker slot until it finishes, and excess calls fail closed rather than creating an unbounded queue. These controls bound caller wait and concurrency, not CPU/memory per operation or all remote provider work. Hard preemption of arbitrary native work would require process isolation.

Credential redaction covers configured secrets and common patterns, not arbitrary PII. Permission tests do not establish universal resistance to answer manipulation by malicious retrieved text. The live Claude check is a smoke scenario, not an answer-quality benchmark.

The original source project remains unchanged. Part 5—fuller observability and human approval—has not started and requires user confirmation.
