# Part 5 — observability and human approval

Implemented October 28, 2026. This is a local demonstration with simulated incidents, not a production dispatch system. Part 6 evaluations and Part 7 deployment controls remain separate work.

## Backend traces

`src/services/observability.py` creates a request UUID, UTC timestamps, monotonic elapsed time, and a redacted audit writer. `src/orchestrator.py` uses it for request start/end, normalized tool start/result, completion, and errors. No Streamlit dependency is involved; the CLI uses the same runner.

The SDK's `PreToolUse`, `PostToolUse`, and `PostToolUseFailure` hooks record the real SDK tool-call ID, tool name, inputs, output, success/error, latency, and SDK session ID. Unfinished hook pairs receive an interrupted record when the request closes. Hook latency uses SDK `duration_ms` when supplied; otherwise it measures elapsed time between hooks. Normalized UI events and hook records describe the same call from different interfaces; count hook call IDs rather than counting every audit row as a tool call.

Request end records include total application duration, SDK/API duration, SDK-reported token usage, model usage, turns, and cost where available, including SDK terminal errors. Cost is retained as reported: resumed SDK sessions may report cumulative totals, so totals must not simply be added across conversation turns. No custom billing estimate or savings percentage is asserted.

SQL audit records continue to use parameterized INSERTs into `FDE_VIEWS.AgentAuditLog` through the restricted login. New fields are structured JSON inside `Content`; no SQL schema migration or added agent privileges are required. Administrative inspection remains in the UI's password-protected audit viewer.

Writes within one request are serialized and bounded to five seconds (or the shorter configured tool deadline), using the separate audit worker. If SQL audit persistence fails, the application emits an `audit_warning` and a safe server log containing request/event identifiers, without raw transport errors. Evidence retrieval and answers may continue with the warning. This is an explicit availability tradeoff: SQL tracing is best effort, not guaranteed delivery or a compliance-grade immutable log. Other concurrent requests may still encounter the bounded worker's busy response. Application audit waits at request start/end can add bounded overhead outside the SDK request timeout.

Reference checked against the installed SDK and [Anthropic's Python hook example](https://github.com/anthropics/claude-agent-sdk-python/blob/main/examples/hooks.py).

## Simulation control plane

`src/services/approvals.py` manages a separate, private local SQLite ledger at `data/control/approvals.sqlite3` by default. It is persistent application state, ignored by Git, separate from SDK runtime/cache files and the SQL agent connection. Back it up before cleanup; deleting this file deletes the local proposal/decision history. The process lazily creates it and its directory with private permissions. Filesystem administrators remain trusted; this is not a tamper-proof or cryptographically signed audit system.

The fourth MCP tool, `propose_incident_escalation`, accepts only summary, supporting evidence, and an SOP reference. Its adapter binds the proposal to the server-owned application session. It cannot accept a session override, approval flag, operator password, or replacement execution payload. There is no approve/reject/execute MCP tool and no SQL permission on the approval ledger. The model is instructed to propose only on an explicit user request after retrieving evidence; the human still assesses the correctness and sufficiency of the proposal's evidence.

A proposal contains a UUID, immutable stored JSON payload, SHA-256 payload digest, conversation ID, creation/expiry time, and pending status. Repeating the exact payload in the same conversation returns the existing proposal. A timeout can leave a pending proposal that becomes visible in the human review panel; it cannot create an incident automatically.

The human reviews the stored payload and submits its proposal ID and digest through the CLI/UI, with separate operator credentials. `decide()` authenticates internally on every decision; it does not trust a caller-provided authentication flag. Approval is bound to that exact session, proposal, and digest. The service rechecks the stored payload hash and expiry inside an SQLite `BEGIN IMMEDIATE` transaction.

- **Approve:** append approved event, create one simulated incident, mark the proposal executed, and append executed event in the same transaction.
- **Reject:** record rejection and mark rejected; later approval cannot execute it.
- **Invalid credentials, wrong session/digest, expired or decided proposal:** refuse execution and record the denial/expiry when the ledger is writable.
- **Repeated/concurrent approvals:** one incident per proposal is enforced by a unique database constraint and transaction serialization; repeats return the original ID and record duplicate prevention.
- **Ledger write failure:** roll back approval, incident creation, and execution events together. The application reports failure. No partial successful action is reported.

Decision events (including authenticated operator identity, timestamps, and incident ID) live in the SQLite ledger; SQL traces contain the agent proposal tool call. These are deliberately distinct stores. SQL audit loss does not disable the control plane when its authoritative local ledger remains healthy; local ledger failure prevents decisions from committing. There is no cross-database atomicity claim.

New conversation creates a new session and does not inherit pending proposals. Old records remain in the ledger. Proposals expire after 900 seconds by default (checked at decision time); an expired identical proposal cannot be revived in the same conversation. Start a new conversation and reassess. The UI displays up to 50 recent proposals per session.

## Set up a human operator

No reusable human password was generated or installed during automated verification. Proposals are disabled while `APPROVAL_PASSWORD_HASH` is blank. To enable local manual use:

```bash
cd '/Users/pallavjain/my-git/AI Engineer/cold-chain-claude-mcp'
.venv/bin/python -m scripts.configure_operator
```

Choose a separate 12–256 character password at the hidden terminal prompt. The script atomically preserves the other local `.env` entries and adds the operator name and salted scrypt hash with private file permissions. It prints neither password nor hash. Restart the CLI/Streamlit process because settings/services are cached. Never paste the operator password into chat.

This is one local operator, not deployed user authentication. Five failed authentication attempts trigger a process-local 60-second lockout. Restart resets the limiter; it is not a distributed brute-force defense, SSO, MFA, or authorization system for a public site. Production access controls and retention/backup policies belong to Part 7.

## Use

```bash
.venv/bin/python -m src.cli
# Ask: Assess the synthetic temperature breaches and propose a simulated escalation for human review.
# /approvals lists this conversation's proposals and prompts for a human decision and credentials.
```

In Streamlit, the **Human approval · simulation only** panel shows the server-stored proposal. Review its exact contents, select approve/reject, check the review confirmation, and authenticate. Rejection is the default. The panel also shows the durable decision trail. Resetting the conversation isolates its proposals. The UI's SQL admin audit credentials are separate from operator credentials.

There is no email, Slack, driver contact, shipment rerouting, or other external notification integration. The only approved effect is creation of a local record explicitly labeled as a simulation.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
# Paid model request using authorized synthetic fleet/SOP evidence:
.venv/bin/python -m scripts.verify_approval_workflow --live --output docs/part5-live-check.json
```

The live verifier uses a randomly generated temporary operator and temporary ledger. It does not install the test credentials into `.env`, send them to Claude, or leave a persistent test incident. SQL trace records remain for inspection. Offline tests cover negative approval cases, concurrent approvals, rollback, redaction, MCP boundaries, concurrent hook logging, error classification, and Streamlit approval/reset behavior. See `PART5_COMPLETION.md` for measured results.
