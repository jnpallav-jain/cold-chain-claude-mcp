# Part 4 — Deterministic guardrails and execution limits

## SQL policy

`src/security/sql_policy.py` parses T-SQL with SQLGlot, validates an allowlisted AST, and regenerates the query. The original model text is never executed directly. Invalid input is rejected before opening a database connection.

The supported subset is one SELECT from `FDE_VIEWS.VW_ACTIVE_FLEET`, with its nine approved columns, literals, basic comparisons, AND/OR/NOT, IN/BETWEEN/LIKE, sorting, grouping, HAVING, and COUNT/SUM/MIN/MAX/AVG. Table/output aliases and simple arithmetic are supported. Wildcard projections expand to the fixed nine-column contract. A future added view column will not silently become part of a wildcard result.

Joins, CTEs, subqueries, UNION, SELECT INTO, external/system objects, catalog-qualified tables, variables, unapproved functions, comments, hints, TOP PERCENT/WITH TIES, and multiple statements are rejected. This intentionally supports less than general T-SQL. It is not a general SQL sandbox or a cost estimator.

Validated queries receive a server-side TOP bounded by `SQL_ROW_LIMIT`, and fetching is bounded again on the client. TOP/returned-row limits do not guarantee a cheap scan, aggregate, or sort. Native deadlines and restricted credentials provide separate controls.

## Database enforcement and actual cancellation

The restricted login can SELECT the semantic view and INSERT audit events. Direct raw-table reads and modifications, plus audit reads/updates/deletes/alteration, are disallowed. Administrative inspection and provisioning use separate credentials. Live evidence verifies the permissions in the dedicated database; nothing modifies the original project.

`SqlQueryExecutor` checks out a connection, sets pyodbc's statement timeout, and holds a query-specific cancellation handle. A tool/request deadline calls the active cursor's native `cancel()`. A backup daemon timer also requests cancellation if the driver exceeds its timeout. The handle detaches before cursor release, and failed/cancelled connections are invalidated rather than returned to the pool. A separate connection-pool wait timeout and native login timeout bound acquisition waits.

The live test uses a rollback-only table lock to make a harmless approved SELECT wait. It checks both native driver expiry and explicit cancellation, then inspects SQL Server for a remaining active request. These measurements apply to the tested driver/server environment; network/driver cleanup can add latency beyond a caller deadline.

## Default limits

| Setting | Default | Role |
|---|---|---|
| `SQL_QUERY_TIMEOUT` | 3 seconds | Native statement deadline; backup cancel follows after 0.5 seconds |
| `SQL_LOGIN_TIMEOUT` | 8 seconds | Driver connection/login timeout |
| `SQL_POOL_TIMEOUT` | 3 seconds | Pool checkout wait; each engine has 2 slots and no overflow |
| `SQL_ROW_LIMIT` | 10 | Server TOP and client row cap |
| `SQL_MAX_CHARS` | 8,000 | Input query size; AST also limited to 200 nodes and 256-character literals |
| `TOOL_TIMEOUT` | 45 seconds | Maximum caller wait per tool, reduced by the remaining request deadline |
| `TOOL_MAX_ATTEMPTS` | 1 | Up to 2 only when explicitly configured; retries only completed transient read failures |
| `TOOL_WORKER_LIMIT` | 2 | Business worker capacity; no unbounded queue |
| `TOOL_MAX_OUTPUT_BYTES` | 16,384 | UTF-8 JSON result cap; oversized output becomes a valid error result |
| `CLAUDE_MAX_TOOL_CALLS` | 8 | Shared attempt reservation across MCP tools in a request |
| `CLAUDE_MAX_PROMPT_CHARS` | 6,000 | User-question size cap |
| `CLAUDE_MAX_TURNS` | 8 | SDK model-turn bound |
| `CLAUDE_MAX_BUDGET_USD` | $0.50 | SDK budget setting; not an external billing/account hard cap |
| `CLAUDE_REQUEST_TIMEOUT` | 120 seconds | Application request deadline, followed by runtime/driver cleanup |

A timed-out operation is not automatically retried. Transient retries share the original tool deadline and are bounded by `TOOL_MAX_ATTEMPTS`. SDK/provider transport retries are separate from these application attempts. Weather uses its native HTTP timeout; Pinecone vector queries receive explicit socket deadlines; optional OpenAI embedding requests disable SDK retries and set a timeout. Local embedding weights must already be cached: model downloads no longer occur inside agent requests.

### Worker limitation

Python cannot forcibly stop a running embedding/native network thread. A timed-out non-SQL worker retains its slot until it finishes, limiting background work to the configured capacity. Once occupied slots are exhausted, new calls fail closed instead of queuing more work. Workers are daemon threads. Audit persistence has a separate single worker and bounded caller wait. This bounds caller wait and worker count, not CPU/memory per operation or every provider's server-side execution. Process isolation would be needed for hard preemption of arbitrary non-SQL native work.

## Permission and data boundaries

Built-in shell/filesystem/web/subagent tools remain disabled. Strict MCP configuration, empty settings sources, and an exact-name callback restrict calls to the three business tools. Tests reject names from other servers, suffix lookalikes, and built-ins. Live runtime metadata confirms the same three-tool exposure. `allowed_tools` is not treated as a complete restriction mechanism.

Retrieved passages are labeled evidence-only, and the shared system prompt treats tool content as data rather than authority. These controls prevent content from granting new tool permissions; they do not guarantee that every generated claim is faithful. Broader adversarial answer evaluation remains Part 6.

## Redaction

Configured SecretStr values and common connection/key patterns are redacted from tool results, outgoing user questions, normalized agent events, and application audit content. A streaming suffix buffer prevents configured secrets from leaking across text-delta boundaries. Raw CLI diagnostics and database exceptions are not shown to users. This is targeted credential redaction, not a general PII detector or a guarantee about third-party SDK internal logs/session files. Local runtime files remain private and ignored by Git.

## Verify

```bash
python -m unittest discover -s tests -v
python -m scripts.verify_guardrails --live --output docs/part4-live-check.json
python -m scripts.verify_services --live --output docs/part4-service-check.json
# Previously authorized data transfer and configured Claude credentials required:
python -m scripts.verify_agent --live --output docs/part4-agent-check.json
```

The first live command briefly holds a rollback-only lock in the dedicated synthetic database, then releases it. It does not execute a production action or a model request. See `PART4_COMPLETION.md` for results. Part 5 has not started.

## References

- [SQLGlot API](https://sqlglot.com/sqlglot)
- [pyodbc connection timeout and cursor cancellation API](https://github.com/mkleehammer/pyodbc/blob/master/src/pyodbc.pyi)
- [Microsoft SQLCancel behavior](https://learn.microsoft.com/en-us/sql/relational-databases/native-client/odbc/creating-a-driver-application-asynchronous-mode-and-sqlcancel?view=sql-server-ver15)
