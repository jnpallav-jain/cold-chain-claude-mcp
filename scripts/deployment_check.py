"""Local/container readiness checks. No raw credentials or transport diagnostics are printed."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import resource
import time
from claude_agent_sdk import ClaudeSDKClient
from src.config import get_settings
from src.orchestrator import AgentSession, build_agent_options
from src.services.container import get_services
from src.services.audit import AuditEvent


async def check(deep):
    settings = get_settings()
    settings.require(
        "demo_password_hash",
        "approval_password_hash",
        "anthropic_api_key",
        "pinecone_api_key",
        "sql_agent_password",
    )

    # Format check only; the actual browser login verifies a password separately.
    for field in [settings.demo_password_hash, settings.approval_password_hash]:
        parts = field.get_secret_value().split("$")
        assert (
            len(parts) == 3
            and parts[0] == "scrypt"
            and len(parts[1]) == 32
            and len(parts[2]) == 128
        )
    import pyodbc

    assert "ODBC Driver 18 for SQL Server" in pyodbc.drivers()
    services = get_services()
    result = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "uid": os.getuid(),
        "odbc_driver_present": True,
        "configuration_present": True,
        "deep": deep,
        "admin_password_present_in_app": bool(
            settings.sql_admin_password.get_secret_value()
        ),
    }
    if deep:
        start = time.monotonic()
        telemetry = services.telemetry.query(
            "SELECT TOP 1 Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET"
        )
        assert len(telemetry.rows) == 1
        services.audit.write(
            AuditEvent(
                "deployment-readiness",
                "readiness",
                "deployment_check",
                "Readiness check using isolated resources; no model request.",
            )
        )
        passages = services.sop.search(
            "fresh perishables critical temperature breach threshold"
        )
        assert passages and any(
            item.metadata.get("source_file") == "Cold_Chain_Incident_SOP_v2.md"
            for item in passages
        )
        from pydantic import SecretStr

        dummy = settings.model_copy(
            update={"anthropic_api_key": SecretStr("non-credential-startup-check")}
        )
        options = build_agent_options(dummy, services, AgentSession())
        async with asyncio.timeout(30):
            async with ClaudeSDKClient(options=options) as client:
                assert await client.get_server_info() is not None
        import torch

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result.update(
            sql_view_read=True,
            sql_audit_insert=True,
            pinecone_retrieval=True,
            local_embedding_loaded=True,
            sdk_runtime_initialized=True,
            model_request_made=False,
            torch_cuda_available=torch.cuda.is_available(),
            elapsed_seconds=round(time.monotonic() - start, 3),
            process_peak_rss_bytes=rss if platform.system() == "Darwin" else rss * 1024,
        )
    return {"status": "passed", **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(check(args.deep))
    except Exception as error:
        result = {
            "status": "failed",
            "error_type": type(error).__name__,
            "message": "Readiness failed; check private server configuration and service availability.",
        }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
