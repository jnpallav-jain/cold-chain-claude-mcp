# Historical Part 2 — Business services and isolated configuration

Part 3 replaces the temporary LangGraph adapter described below. See `PART3.md` and `PART3_STATUS.md` for current implementation and verification status.

The original project is preserved. This phase extracts telemetry, weather, SOP retrieval, and audit persistence into plain Python services with explicit settings and injectable connections. LangGraph remains only as the temporary orchestration adapter; the Claude migration has not started.

## Configuration and resource isolation

`Settings` reads only this project's `.env` plus explicitly supplied environment variables. Service credentials are validated at first use; import-only operations need none. Resource names are validated when settings load. The original `fde-sop-index-*` indexes, `master` as an application database, and the original agent account are rejected. SQL and Pinecone provisioning are opt-in commands with a non-mutating default plan.

The dedicated SQL container and volume use the Compose project name. SQL is bound to loopback port 1434. The application uses `cold_chain_claude_mcp`, with `USR_CC_CLAUDE_RO` restricted to the fleet view and audit inserts. The admin bootstrap uses `master` only to create the isolated database and login. Passwords were generated into the ignored local `.env`, and the user supplied the Pinecone key there.

The separate Pinecone index uses 1024-dimensional dense vectors and cosine similarity. A nonempty `sop-v1` namespace is used consistently for ingestion and retrieval. No automatic index deletion remains. Deletion protection is enabled on creation.

## Services

`TelemetryService.query()` returns column names and rows. `WeatherService.fetch()` returns typed, timestamped conditions with a labeled heuristic, not real traffic measurements. `SopService.search()` returns passages with metadata. `AuditService.write()` persists a parameterized event independently of Streamlit; audit reads require an explicitly supplied admin connection.

Local embeddings are cached in process. An existing BGE-M3 snapshot can be reused read-only; otherwise model downloads go under this project's ignored data cache. Models and clients are lazy so service imports do not download weights or contact APIs.

## Ingestion changes

CSV loading resolves paths from the repository and defaults to four fabricated records. Replacing existing telemetry data requires an explicit flag. SQL bootstrap checks for existing data before loading.

SOP parsing retains Markdown heading structure and 600-character chunks with 60-character overlap. The new SHA-256 cache includes the target host, index, namespace, embedding configuration and splitter identity. Versioned chunk IDs preserve the previous version during failed uploads. Cache updates are atomic and occur only after successful per-file operations. Failed deletion is retryable. Cache correctness assumes a single ingestion writer and that index contents are managed by this pipeline; manual deletions require cache invalidation/re-ingestion.

## Verification

The offline suite contains 19 checks covering resource isolation, lazy imports, missing credentials, SQL results, parameterized audit writes, weather validation and failure behavior, source metadata, dimension mismatch, CSV mapping, and retryable ingestion cache behavior. It is a service test suite, not a RAG answer-quality evaluation harness.

The live smoke command checks the synthetic SQL view, temperature filtering, audit inserts/admin inspection, permission error code 229 for four forbidden operations, and current weather. SOP retrieval is checked after authorized indexing. `part2-live-check.json` records the latest live evidence.

## Phase boundary

No Claude Agent SDK or MCP orchestration, human approval feature, SQL parser, query-cost controls, or website deployment is implemented in this phase. Those remain separate checklist parts and require user confirmation before proceeding.
