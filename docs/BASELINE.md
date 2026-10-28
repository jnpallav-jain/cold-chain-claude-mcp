# Migration baseline

The initial copy contains the current working-tree versions of the original Python sources, including the uncommitted IPython import and whitespace changes in `src/orchestrator.py`. `baseline-manifest.json` records source commit, working-tree status, and file fingerprints. Existing Git history was not copied.

Current functionality remains LangGraph + DeepSeek/OpenAI/Ollama, local BGE-M3 or OpenAI embeddings, Pinecone, SQL Server, and Streamlit. There is no Claude Agent SDK or MCP integration yet.

Part 1 changes are limited to independent packaging/documentation, sanitizing the SQL login password into a SQLCMD variable, and allowing `TELEMETRY_CSV_PATH` with a synthetic fallback. The original pinned requirements are retained in `requirements.source.txt`; installation adjustments are recorded in the verification report.

Known inherited limitations: import-time credentials and network/model initialization; SQL database hardcoded to master; hardcoded Pinecone index names; ingestion can delete/recreate an index; UI omits the system prompt; audit writes are best-effort; no automated evaluation harness; SELECT-prefix validation does not bound SQL cost. The audit-table setup is not included in the inherited SQL script.

Do not run ingestion or launch the live application against original credentials/resources during this phase. Part 2 introduces isolated resources and configuration before any service integration run.
