# Cold-Chain Claude MCP

Independent migration of a cold-chain logistics assistant. **Part 7: the authenticated local website and Docker package are verified. AWS deployment is pending an organization-policy access fix; no public demo URL exists. See `docs/PART7_STATUS.md` and `docs/PART7.md`.**

The agent uses Claude Agent SDK with an in-process MCP server exposing three evidence tools for telemetry, weather, and SOP retrieval, plus a fourth tool that stores a simulated escalation proposal for human review. Both the CLI and Streamlit frontend use a shared prompt and event interface. Imports make no model or network calls.

## Install and configure

Requires Python 3.12+, Docker for the local SQL Server, and ODBC Driver 18 for SQL Server on the host.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install -e . --no-deps
python -m pip check
```

Copy `.env.example` to `.env` only when no local `.env` exists; supply credentials locally. The current development instance already has an ignored `.env`. Never overwrite its generated SQL passwords or commit it. `.env.example` documents all supported settings.

`src/config.py` resolves relative data paths from the project root. It accepts the inherited `Embeddings_model` and `Local_Embedding_Model` names as embedding aliases. Legacy DeepSeek/Ollama model selection has been retired. New configuration should use the uppercase names in the example.

## Isolated development resources

| Resource | Target |
|---|---|
| Docker Compose project | `cold-chain-claude-mcp` |
| SQL container | `cold-chain-claude-mcp-sqlserver-1` |
| Host address | `127.0.0.1:1434` |
| Docker data volume | `cold-chain-claude-mcp_sqlserver-data` |
| Application database | `cold_chain_claude_mcp` |
| Restricted login | `USR_CC_CLAUDE_RO` |
| Pinecone index | `cold-chain-claude-mcp-sop-local` |
| SOP namespace | `sop-v1` |

The SQL image uses amd64 emulation on Apple silicon. Its Developer edition is for development, not production licensing. Application engines use the dedicated database; an admin connection uses `master` only to create the database and login. Original database/index names are rejected by configuration.

Provisioning is explicit:

```bash
docker compose up -d --no-recreate sqlserver
python -m scripts.bootstrap_resources                 # display plan; no mutations
python -m scripts.bootstrap_resources --apply --component sql
python -m scripts.bootstrap_resources --apply --component pinecone
```

SQL bootstrap loads the four synthetic rows only if the raw table is absent, then applies the view and audit permissions. Re-running bootstrap preserves existing records. SQL passwords are read locally, never embedded in the SQL file. The Pinecone bootstrap validates dimension and metric and never deletes an incompatible index; it creates new indexes with deletion protection enabled.

After authorizing the policy text's transfer to Pinecone, ingestion is:

```bash
python -m scripts.ingest_sop_pinecone
```

The cache is scoped to index host, namespace, embedding settings, and splitter settings. Changed files upload versioned chunks before removing their previous tracked IDs. Failed uploads do not mark the changed file complete. Deletions only target tracked IDs in the configured namespace. No index recreation or broad namespace deletion is performed.

`python -m scripts.ingest_legacy_data` refuses to replace an existing telemetry table unless `--replace` is supplied. Its default input is the fabricated sample in `data/sample/`.

## Verify services independently

```bash
python -m unittest discover -s tests -v
python -m scripts.verify_services --live --skip-sop
# After authorized SOP ingestion:
python -m scripts.verify_services --live
```

The offline suite uses fixture data and injected dependencies. The live command contacts the dedicated SQL instance and weather service, writes a labeled audit event, checks permissions, and optionally retrieves SOP passages. It never invokes the agent or a chat model. Live results assume the four synthetic rows remain unchanged.

## Service boundaries

- `src/services/telemetry.py`: SQL view queries and bounded returned rows.
- `src/services/weather.py`: timestamped weather plus a clearly labeled wind-based demonstration heuristic.
- `src/services/sop.py`: lazy dense embedding model and Pinecone retrieval, preserving source metadata.
- `src/services/audit.py`: parameterized audit persistence and admin-only inspection interface.
- `src/services/observability.py`: request traces and SDK tool hooks with IDs, timings, usage/cost, redaction, and visible persistence failures.
- `src/services/approvals.py`: persistent local proposal/decision ledger and authenticated, atomic simulated incident creation.
- `src/services/documents.py`, `ingestion.py`, `loader.py`: document parsing and isolated ingestion.
- `src/agent_tools.py`: validated Claude SDK MCP adapters over the business services.
- `src/orchestrator.py`: shared Claude runner, streamed events, and isolated session continuation.
- `src/cli.py`: terminal chat and single-question entry point.
- `src/ui.py`: Streamlit frontend consuming the same runner as the CLI, plus an administrative audit viewer.

Set `ANTHROPIC_API_KEY` and `CLAUDE_MODEL` in `.env` before running the agent:

```bash
python -m src.cli
python -m src.cli --question "What is the fresh perishables temperature threshold?"
streamlit run src/ui.py
```

The CLI supports `/reset`, `/approvals`, and `/quit`. The UI supports New conversation. SDK session files stay under the ignored `data/cache/agent-runtime/` directory. No most-recent-global-session resume is used. Both entry points load the same system prompt. Restart the running app after changing `.env`; settings and service instances are cached per process. Backend tracing records request and tool lifecycles independently of the UI. SQL audit failures produce visible warnings. Approval decisions require their separate SQLite ledger to commit atomically.

For offline integration checks, run the unit tests. `python -m scripts.verify_sdk_runtime` checks bundled-runtime startup without a model request. The separate `python -m scripts.verify_agent --live` command makes paid Claude calls and sends retrieved evidence to Anthropic; use it only after authorizing that transfer. See `docs/PART3.md` and the Part 3 verification report for the exact verification status.

## Guardrails

SQL is parsed into an allowlisted T-SQL AST and regenerated before execution. Only one SELECT against the fleet view is allowed. Joins, nested queries, metadata/external sources, unknown functions, comments, and additional statements are rejected. Wildcards expand to the nine approved columns, and server/client row limits both apply. Row caps do not bound scan/sort cost: native SQL statement deadlines and query-specific cursor cancellation are separate controls.

Tools have bounded caller deadlines, shared request-call budgets, bounded worker capacity, output-size limits, and bounded transient retries (one attempt by default). Timed-out non-SQL threads retain their slots until finished; this prevents an unbounded queue but does not forcibly kill native embedding work. Configured credentials are redacted from tool/event/audit output, including streamed text.

Use `python -m scripts.verify_guardrails --live` for the dedicated database timeout/cancellation check. See `docs/PART4.md` for supported SQL, defaults, and precise limits.

Local embedding weights must be prepared before starting the agent. If not already cached, explicitly run `hf download BAAI/bge-m3 --cache-dir data/cache/embeddings` during setup; inference requests will not download them.

## Remaining phases and limitations

Part 5 approval is local and simulated. Set a separate operator password with `python -m scripts.configure_operator`, then restart the app. Proposals remain disabled until configured. See `docs/PART5.md`. Part 6 adds repeatable evaluations; Part 7 local deployment is verified; AWS deployment is blocked by account policy. This implementation is not a general-purpose SQL sandbox or a hard CPU/memory isolation boundary.

Fleet fixtures are fabricated historical data. Current weather cannot establish historical causation. This is a single-agent SDK implementation. No multi-agent system or public deployment is claimed. The small evaluation baseline measures specific checks, not general accuracy or human-reviewed faithfulness.

See `MIGRATION_CHECKLIST.md`, `docs/PART7.md`, `docs/PART6.md`, `docs/PART5.md`, `docs/PART4.md`, and `docs/PART3.md` for current behavior; `docs/PART2.md` and `docs/BASELINE.md` record earlier phases. `docs/VERIFICATION.md` records the historical Part 1 checks. Read `ATTRIBUTION.md` before distributing inherited code or SOP content; uploading to a private index does not establish public redistribution rights.

To stop the local SQL instance without deleting data, use `docker compose stop sqlserver`.

## Evaluations

```bash
.venv/bin/python -m scripts.evaluate                       # 14 offline controls; 16 live cases skipped
.venv/bin/python -m scripts.evaluate --live-agent --live-retrieval --live-sql
```

Live agent mode makes 12 paid Claude requests with fixed synthetic/SOP evidence, fresh sessions, and $0.15 SDK budgets per case by default. Retrieval mode reads the existing authorized Pinecone index. SQL mode runs native checks against the isolated SQL instance. Outputs go to new timestamped directories and preserve case failures, answers, tool evidence, latency/cost, and version hashes. See `docs/PART6.md` before interpreting scores. The final baseline passes 30 defined cases after a documented scorer correction; human review remains pending and a qualitative grounding concern is recorded.
