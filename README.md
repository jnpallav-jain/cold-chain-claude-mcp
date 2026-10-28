# Cold-Chain Claude MCP

Independent migration workspace for a cold-chain logistics assistant. **Status: Part 1 baseline; Claude Agent SDK and MCP are planned, not implemented.**

The baseline uses LangGraph to choose between SQL fleet queries, current weather lookup, and SOP retrieval through BGE-M3 + Pinecone. Subsequent phases replace orchestration, isolate services, enforce limits, add approval controls and repeatable evaluations, and deploy a demo.

## Local installation

Requires Python 3.12 or newer. From this directory:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip check
cp .env.example .env
```

For the dependency versions verified on macOS arm64/Python 3.12, install `requirements.lock.txt` first and then use `python -m pip install -e . --no-deps`. The original source pins are preserved separately in `requirements.source.txt`.

Fill credentials in `.env` locally only. Future Claude settings are placeholders; the current baseline still uses `Agent_llm`. No credentials or downloaded embedding weights are bundled. The ODBC Driver 18 for SQL Server is an additional native prerequisite for a live SQL connection.

This is a source-backed editable installation: run from the repository directory, which contains configuration and data files.

## Phase boundary

Do not run ingestion or the live UI yet. The inherited Pinecone names are hardcoded and its ingestion script can delete an index. Part 2 must configure a separate index and database container first. The example reserves SQL port 1434 and a new Pinecone index name, but the index variable is not wired into the baseline yet. No Docker, SQL, Pinecone, or paid model operations are executed by installation.

After the resource isolation and orchestration phases are complete, the intended UI entry point is `streamlit run src/ui.py`.

## Files

- `src/`: inherited tools, graph, UI, and prompt.
- `scripts/`: inherited ingestion and SQL view setup. SQL login creation now requires a securely supplied SQLCMD variable named `SQL_AGENT_PASSWORD`; do not place a real password in source.
- `data/sample/`: four fabricated fleet records, selected by default by the CSV loader.
- `data/policy/`: inherited SOP, retained for local development.
- `docs/BASELINE.md`: scope, provenance, and inherited limitations.
- `docs/VERIFICATION.md`: installation and source-copy validation results.
- `MIGRATION_CHECKLIST.md`: phased work and completion criteria.
- `ATTRIBUTION.md`: upstream credit and publication limitations.

## Data and claims

The external Kaggle CSV and original hash cache were not copied. Synthetic fleet records are historical demonstration data; current weather must not be presented as evidence of historical causation. Database permission checks, SDK integration, evaluations, and deployment must be independently verified in this copy before being claimed. No six-month SDK experience or production rollout is implied.

See [attribution and publication status](ATTRIBUTION.md) before distributing inherited material.
