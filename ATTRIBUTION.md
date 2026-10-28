# Attribution and publication status

The source project's README credits [nimowhyca/cold-chain-logistics-FDE-Project](https://github.com/nimowhyca/cold-chain-logistics-FDE-Project) as its starting point, with local fixes. This copy preserves that attribution. The Python tools, agent loop, Streamlit UI, ingestion scripts, SQL view setup, and SOP are inherited material unless explicitly listed as new work.

No LICENSE, COPYING, or NOTICE file was present in the local source tree. The accessible upstream repository page did not establish an explicit license. No broad license is asserted for inherited code or the SOP. Review applicable rights before public source distribution or publishing inherited content. This does not block private local development.

The Kaggle telemetry CSV was omitted because redistribution terms could not be verified. Its source URL is retained; a hand-authored synthetic fixture is provided instead. The inherited SOP is retained for local development and must also be reviewed before public publication.

New Part 1 work: independent packaging and environment instructions; credential removal; dataset-path configuration; synthetic data; baseline provenance and migration documentation. At the end of Part 1, Claude SDK, MCP integration, and a deployed website had not been implemented.

Part 2 contributions: centralized configuration, independent service interfaces and lazy resource loading, isolated resource provisioning, versioned/target-scoped ingestion caching, and service-level tests. The services preserve business logic from the inherited implementation where applicable.

Part 3 contributions: replacement of LangGraph orchestration with Claude Agent SDK, in-process MCP adapters, shared prompt and event protocol, session handling, rebuilt CLI/frontend integration, and offline SDK/MCP/frontend checks.

Part 4 contributions: fail-closed T-SQL AST validation, native driver deadlines and cursor cancellation, worker/call/output budgets, scoped retries, credential/event redaction, and deterministic/live guardrail checks.
