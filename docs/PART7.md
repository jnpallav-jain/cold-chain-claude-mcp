# Part 7 — local website verified; AWS deployment pending

October 28, 2026. AWS is the selected provider. No AWS resources have been created and no public demo URL is available yet.

## Verified implementation

The Streamlit workspace has a separate viewer sign-in, sample questions, historical/synthetic labels, timestamped weather evidence, SOP passages/source sections, normalized SQL, execution traces, conversation reset, and simulation approval controls. The demo excludes the administrative audit viewer. Separate viewer/operator credentials were generated locally; their private handoff file is `data/control/first-login.txt` (mode 600, ignored by Git). Do not publish or share that file. `.env` stores salted password hashes and server-side API/SQL credentials.

`src/web.py` checks admission before constructing an SDK runner. The SQLite-backed `DemoControl` persists login attempts, hashed session tokens, request leases, hourly admission, and daily reservations. Defaults: one active website request, ten requests per shared reviewer per hour, a 15-cent SDK request allowance, and 150 cents of nonrefundable admission reservations per UTC day. New browser sessions do not reset the principal's rate limit or daily ledger. Sessions expire after one hour; password rotation invalidates existing tokens. Five failed logins in a minute temporarily block login.

These are single-instance demo controls, not multi-tenant SSO or a provider-enforced billing cap. A request can exceed an SDK budget at a model-turn boundary. Reservations are conservative admission accounting, not actual billed cost. Configure an Anthropic project spending limit before wider access. Limits do not cover owner-run CLI/evaluation commands. Run one website instance; independent copies with separate control volumes have separate counters. No external notifications are integrated.

The model runtime receives blank overrides for other configured secret environment variables; business tools retain their configuration in the parent process. The Docker web service receives no SQL admin password. A one-off `bootstrap` service gets administrative credentials only for SQL setup.

The empty-result prompt now prohibits unsupported explanations and requires quoting the tool's `normalized_sql`. The updated 30-case evaluation run passes its defined checks; human review remains pending. See `docs/evals/part7-runtime-v1/`.

## Local commands

The local containers are currently stopped. To start this project's existing SQL instance and the authenticated website:

```bash
cd '/Users/pallavjain/my-git/AI Engineer/cold-chain-claude-mcp'
docker compose -f compose.yaml -f compose.demo.yaml up -d sqlserver web
```

Open `http://127.0.0.1:8501`. Read the viewer credentials privately from `data/control/first-login.txt`; the operator password is different. The app port is loopback-bound, and the SQL port remains loopback-bound. The public proxy overlay is not active.

For a fresh installation, configure local credentials and model cache before building:

```bash
.venv/bin/python -m scripts.configure_demo --generate
.venv/bin/python -m scripts.prepare_embeddings
docker compose -f compose.yaml -f compose.demo.yaml build web
docker compose -f compose.yaml -f compose.demo.yaml up -d sqlserver
# Once SQL is accepting connections; bootstrap preserves an existing table:
docker compose -f compose.yaml -f compose.demo.yaml --profile setup run --rm bootstrap
docker compose -f compose.yaml -f compose.demo.yaml up -d web
```

The current project is already configured. The credential script refuses silent rotation; do not regenerate credentials just to start the app. `prepare_embeddings` copies an existing local BGE-M3 cache without downloading. A new machine needs the public model downloaded separately into `data/cache/embeddings`; the container mounts this cache read-only and inference runs offline.

The Dockerfile installs CPU Torch, pinned Python dependencies, Microsoft ODBC Driver 18, and the packaged native SDK runtime. It runs as UID 10001 with a read-only root filesystem, writable private runtime/control volumes, dropped capabilities, no-new-privileges, bounded PIDs, and a memory limit. Build context excludes `.env`, local credentials, runtime caches, inherited SOP files, and source data. Images have not been pushed to a registry.

## Health, readiness, pause, shutdown

`/_stcore/health` is a liveness check, not proof that SQL, Pinecone, embeddings, or Anthropic are usable. Deep readiness verifies SQL view reads/audit inserts, actual cached embedding/Pinecone retrieval, and native SDK startup without a model request:

```bash
docker compose -f compose.yaml -f compose.demo.yaml exec -T web python -m scripts.deployment_check --deep
# Block new model admissions; in-flight requests are not cancelled:
docker compose -f compose.yaml -f compose.demo.yaml exec -T web python -m scripts.demo_control stop
# Resume admissions:
docker compose -f compose.yaml -f compose.demo.yaml exec -T web python -m scripts.demo_control resume
# Stop website immediately, retaining volumes:
docker compose -f compose.yaml -f compose.demo.yaml stop web
# Optional: stop this project's SQL instance too:
docker compose stop sqlserver
```

Avoid `down --volumes`: it deletes persistent simulation, admission, runtime, and SQL data. Back up durable volumes before migrations or cleanup. No automatic retention/backup service has been configured.

## AWS plan and current blocker

Candidate architecture: a single x86-64 Linux EC2 host in `us-east-1`, with Docker Compose, persistent encrypted EBS, private SQL networking, and HTTPS reverse proxy. The existing Pinecone index and Anthropic API remain external services. Use Session Manager administration and no inbound SSH/database ports. The prepared `compose.public.yaml` and `deploy/Caddyfile` require an owned DNS hostname and have not been applied. No anonymous public access has been enabled.

The Linux web container was tested on local aarch64 Docker; the existing SQL image runs through amd64 emulation locally. For AWS SQL Server support, use a native Intel/AMD x86-64 host. The target amd64 deployment still needs validation on the selected AWS host. Deep readiness observed about 2.21 GB peak RSS in the check process; this is not a full-host memory benchmark. An 8 GiB instance is a candidate for the bounded sample workload, with sizing confirmed by deployment testing.

The AWS connection can authenticate. Rechecks of `ec2:DescribeInstanceTypes`, `ec2:DescribeVpcs`, and `ssm:GetParameter` in `us-east-1` are explicitly denied by an AWS Organizations service control policy. A role named `AccountFullAccessRole` does not remove the observed organization-policy restriction. No attempt was made to bypass it or create paid resources. The organization administrator must permit the intended deployment operations, or the connection must point to the intended account with suitable access.

AWS Pricing returned an on-demand Linux `t3a.large` rate of $0.0752/hour in `us-east-1` on October 28, 2026: approximately $54.90 for 730 running hours, **compute only**. This is a planning estimate, not an approved spend or a total deployment quote. Storage, public IPv4, domain/DNS, transfer, monitoring, API/Pinecone usage, and tax are additional. Availability, AMI, VPC, and full costs must be verified once the policy blocker is resolved. Use standard burst-credit mode if selecting a T3a instance to avoid surplus-credit billing; sustained CPU load may then throttle.

Before a public resume URL: obtain suitable AWS access, agree on cost/runtime and an owned domain, review inherited SOP publication rights or replace it with authorized demo content, finish the actual human answer review, validate native amd64 deployment and TLS/access controls, then approve the concrete resource/data-transfer plan. Part 7 is incomplete until the hosted workflow and URL are verified. Part 8 has not started.

References: [Streamlit Docker deployment](https://docs.streamlit.io/deploy/tutorials/docker), [Streamlit configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml), [SQL Server container support](https://learn.microsoft.com/en-us/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16), [Claude agent hosting](https://platform.claude.com/cookbook/claude-agent-sdk-07-hosting-the-agent).
