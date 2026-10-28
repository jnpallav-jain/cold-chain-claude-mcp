# Cold-Chain Claude MCP

Independent migration of a cold-chain logistics assistant. **Part 2: reusable services and isolated resources are implemented. Claude Agent SDK and MCP orchestration are planned for Part 3.**

The retained agent uses LangGraph. Its tools now call framework-independent Python services for telemetry, weather, and SOP retrieval. Audit persistence is also a backend service. Service imports make no model or network calls.

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

`src/config.py` resolves relative data paths from the project root. It accepts the inherited `Agent_llm`, `Embeddings_model`, and `Local_Embedding_Model` names as aliases. New configuration should use the uppercase names in the example.

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
- `src/services/documents.py`, `ingestion.py`, `loader.py`: document parsing and isolated ingestion.
- `src/agent_tools.py`: temporary LangChain adapters; Part 3 replaces these with MCP adapters.
- `src/ui.py`: retained Streamlit UI, now using backend audit persistence and centralized database settings.

The UI still emits audit events; full SDK-level lifecycle tracing belongs to Part 5. The retained graph requires its configured legacy model credentials and still has the original UI/system-prompt gap. Do not interpret service verification as an end-to-end agent evaluation. The intended UI entry point remains `streamlit run src/ui.py` after orchestration migration.

## Remaining phases and limitations

Part 3 migrates to Claude Agent SDK and in-process MCP. Part 4 adds parsed SQL validation, execution cancellation and budgets, and explicit agent tool restrictions. The current SELECT-prefix check is secondary; returned-row limits do not bound query cost. Part 5 adds approval controls and fuller observability; Part 6 adds agent evaluations; Part 7 deploys the website.

Fleet fixtures are fabricated historical data. Current weather cannot establish historical causation. No Claude runtime, multi-agent system, public deployment, or measured answer-quality score is claimed yet.

See `MIGRATION_CHECKLIST.md`, `docs/PART2.md`, and `docs/BASELINE.md` for status. `docs/VERIFICATION.md` records the historical Part 1 checks. Read `ATTRIBUTION.md` before distributing inherited code or SOP content; uploading to a private index does not establish public redistribution rights.

To stop the local SQL instance without deleting data, use `docker compose stop sqlserver`.
