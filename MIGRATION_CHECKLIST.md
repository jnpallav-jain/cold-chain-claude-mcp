# Cold-Chain Claude Agent SDK + MCP Migration

Create a separate, independently runnable project that migrates the existing cold-chain assistant from LangGraph to Claude Agent SDK, exposes its business tools through an SDK MCP server, and provides a deployed demonstration with repeatable evaluations.

Source project: `/Users/pallavjain/my-git/AI Engineer/cold-chain-logistics-FDE-Project/`

Proposed new project name: `cold-chain-claude-mcp`. Created at `/Users/pallavjain/my-git/AI Engineer/cold-chain-claude-mcp` on October 28, 2026.

This document is a plan; unchecked items have not been completed. Preserve the original project and describe the actual development and migration timeline accurately.

## 1. Create an independent project copy

- [x] Choose the new project directory.
- [x] Inspect applicable project instructions and the current source changes.
- [x] Copy source files, including relevant uncommitted changes, without modifying the original.
- [x] Exclude `.env`, credentials, virtual environments, generated caches, logs, and Git metadata.
- [x] Inspect copied setup scripts for embedded credentials; replace them with configuration or placeholders.
- [x] Review dataset redistribution permissions before copying or publishing data.
- [x] Initialize independent version history and preserve required license notices and attribution.
- [x] Add `.gitignore`, `.env.example`, and installation instructions.
- [x] Record the original baseline and the new project's scope in the README.

**Completion:** Verified in Part 1. See the completion/verification report for installation checks, retained baseline limitations, and unresolved publication rights. Part 2 awaits user confirmation.

## 2. Extract reusable business services

- [x] Extract telemetry querying from LangChain tool decorators into a Python service.
- [x] Extract weather lookup into a Python service.
- [x] Extract SOP retrieval using local BGE-M3 dense embeddings and Pinecone.
- [x] Extract audit persistence from the Streamlit UI into a backend service.
- [x] Centralize configuration and validate required settings at startup.
- [x] Retain SQL Server initially to isolate orchestration changes.
- [x] Provision an independent database or container and separate Pinecone index.
- [x] Ensure ingestion and index recreation cannot overwrite the original project's resources.
- [x] Exercise service success and failure paths without starting an agent.

**Completion:** Verified offline and against isolated live SQL, weather, and Pinecone resources. See the Part 2 completion report. Part 3 awaits user confirmation.

## 3. Implement Claude Agent SDK and MCP tools

- [x] Verify current SDK documentation and pin compatible dependencies.
- [x] Configure Claude API authentication through server-side environment settings.
- [x] Implement orchestration using `ClaudeSDKClient` in place of the LangGraph state graph.
- [x] Expose `query_telemetry_db`, `fetch_corridor_conditions`, and `search_compliance_sop` through `create_sdk_mcp_server`.
- [x] Define tool argument schemas, descriptions, structured results, and error behavior.
- [x] Apply the system instructions consistently in CLI and UI entry points.
- [x] Define session creation, continuation, reset, and isolation behavior.
- [x] Stream model output and tool events through a UI-independent application interface.
- [x] Preserve source metadata and citations in SOP results.
- [x] Remove unused LangGraph dependencies; retain LangChain retrieval utilities only where useful.
- [x] Demonstrate an end-to-end question using telemetry, weather, and SOP evidence.

**Completion:** Verified with 33 offline checks and an authorized live Claude workflow using all three MCP tools, an SOP citation, and same-session follow-up. See the Part 3 completion report. Part 4 awaits user confirmation.

**Scope:** An in-process SDK MCP server is the first implementation. A remotely hosted MCP endpoint is optional and requires separate transport authentication and deployment work.

## 4. Enforce security and execution limits

- [ ] Recreate the semantic view and restricted agent account in the isolated database.
- [ ] Create the audit table and explicitly configure its insert/read/update/delete permissions.
- [ ] Verify allowed reads and inserts, and denied operations, using the restricted login.
- [ ] Replace the SELECT-prefix-only check with parsed statement validation and approved-object checks.
- [ ] Reject multiple statements and unsupported SQL constructs.
- [ ] Configure and verify database query timeout and cancellation behavior.
- [ ] Limit tool output size and returned rows; document that row limits do not bound query cost.
- [ ] Add tool timeouts, bounded retries, agent turn limits, and per-request budgets.
- [ ] Explicitly disable unnecessary built-in tools, including shell and filesystem access.
- [ ] Verify permission policy behavior instead of treating `allowed_tools` as a complete tool restriction.
- [ ] Treat retrieved text and tool results as data, not authority to change permissions or instructions.
- [ ] Redact secrets and sensitive connection details from user-visible errors and logs.

**Completion:** Repeatable checks show that forbidden operations are blocked and execution is bounded.

## 5. Add backend observability and human approval

- [ ] Record session ID, tool-call ID, tool name, inputs, outputs, status, errors, and timestamps.
- [ ] Capture tool latency, request duration, and SDK-reported usage/cost where available.
- [ ] Define audit-write failure behavior and make failures observable.
- [ ] Keep audit logging functional without Streamlit.
- [ ] Add a proposed incident-escalation action using a simulated internal incident record.
- [ ] Store pending approval outside model-controlled messages and bind approval to the specific action and session.
- [ ] Require authenticated human approval before creating the incident record.
- [ ] Record approval, rejection, and execution; prevent duplicate execution.
- [ ] Clearly label the escalation as a simulation with no external notification.

**Completion:** An action cannot execute without the correct approval, and its complete decision trail is inspectable.

## 6. Build repeatable evaluations

- [ ] Create approximately 20–30 versioned cases with questions, expected behavior, and scoring criteria.
- [ ] Use fixed telemetry fixtures and controlled weather responses for reproducible checks.
- [ ] Check tool selection and argument validity.
- [ ] Check SQL results against expected fixture results.
- [ ] Check SOP retrieval against relevant clauses or reference evidence.
- [ ] Assess answer faithfulness against SOP, telemetry, and weather evidence as appropriate.
- [ ] Test missing evidence, empty results, tool failures, and unsupported questions.
- [ ] Test forbidden SQL, malicious retrieved instructions, and attempts to bypass approval.
- [ ] Test turn limits, query cancellation, session isolation, and request budgets.
- [ ] Use deterministic assertions where possible; human-review model-judged samples.
- [ ] Generate a report with case-level results, failures, latency, and cost where measurable.
- [ ] Record model, prompt, dependency, and dataset versions with each evaluation run.
- [ ] Set release criteria after establishing a baseline; publish measured results rather than invented accuracy claims.

**Completion:** A documented command produces a reproducible evaluation report and exposes regressions.

## 7. Build and deploy the website demo

- [ ] Adapt the existing Streamlit UI to the new application interface.
- [ ] Add sample questions, citations, execution traces, reset controls, and approval controls.
- [ ] Label fleet records as historical and weather readings with their observation time.
- [ ] Avoid implying that current weather explains historical shipment events.
- [ ] Choose hosting that supports the SDK runtime, database connectivity, and local embedding resource needs.
- [ ] Package and verify the deployment environment and dependency installation.
- [ ] Keep API keys and database credentials server-side.
- [ ] Add demo access controls, session isolation, concurrency limits, rate limits, and spending caps.
- [ ] Keep the database and administrative audit viewer off public unauthenticated access paths.
- [ ] Add health checks, visible failure states, and an operational shutdown procedure.
- [ ] Verify the deployed workflow from a fresh browser session.
- [ ] Publish the working demo URL after deployment checks pass.

**Completion:** A reviewer can complete a bounded sample workflow and inspect the evidence supporting its answer.

## 8. Prepare portfolio and interview materials

- [ ] Create an architecture diagram showing website, SDK loop, MCP tools, SQL Server, weather API, Pinecone, and audit storage.
- [ ] Record a short walkthrough with one successful workflow and one blocked or approval-gated action.
- [ ] Publish evaluation results, known limitations, setup instructions, and the actual migration timeline.
- [ ] Distinguish inherited code from newly implemented work and preserve attribution.
- [ ] Decide whether to keep the repository private and offer a code walkthrough.
- [ ] Add the deployed website link to the resume.
- [ ] Use claims that match completed and verified capabilities.

Suggested resume wording after completion:

> Built and deployed a Claude Agent SDK assistant with MCP tools for fleet telemetry, weather, and SOP retrieval, incorporating database permissions, approval controls, and automated evaluations.

## Milestones and scope

- [x] **Milestone A:** Independent project copy and isolated resources.
- [x] **Milestone B:** Local Claude Agent SDK + MCP workflow.
- [ ] **Milestone C:** Verified permissions, approval workflow, and evaluation report.
- [ ] **Milestone D:** Deployed demo and portfolio materials.

Start with one agent and three business tools. Defer multi-agent delegation, database migration, sparse/hybrid retrieval, reranking, and a remotely hosted MCP endpoint until a measured need justifies them.

## Implementation references

- [Official Claude Agent SDK Python repository](https://github.com/anthropics/claude-agent-sdk-python)
- [SDK custom tools and in-process MCP servers](https://github.com/anthropics/claude-agent-sdk-python#custom-tools-as-in-process-sdk-mcp-servers)
- [SDK tool permission behavior](https://github.com/anthropics/claude-agent-sdk-python#using-tools)

Recheck these references when implementation begins because SDK interfaces and deployment requirements can change.
