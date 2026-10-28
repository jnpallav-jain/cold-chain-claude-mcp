"""Start the bundled SDK runtime and inspect MCP registration without a model request."""

import asyncio
import json
from claude_agent_sdk import ClaudeSDKClient
from src.config import Settings
from src.orchestrator import AgentSession, build_agent_options
from src.services.container import get_services


async def verify():
    # Non-credential placeholder: never uses the user's API key and never calls query().
    options = build_agent_options(
        Settings(
            _env_file=None,
            anthropic_api_key="sdk-startup-check-not-a-real-key",
            claude_model="sonnet",
        ),
        get_services(),
        AgentSession(),
    )
    async with asyncio.timeout(30):
        async with ClaudeSDKClient(options=options) as client:
            info = await client.get_server_info()
            assert info is not None, "SDK initialization response missing"
            status = await client.get_mcp_status()
            safe = [
                {"name": item.get("name"), "status": item.get("status")}
                for item in status.get("mcpServers", [])
            ]
            print(
                json.dumps(
                    {
                        "runtime_initialized": True,
                        "model_request_made": False,
                        "mcp_servers_reported_before_query": safe,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    try:
        asyncio.run(verify())
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "SDK startup verification failed; no raw diagnostics printed.",
                }
            )
        )
        raise SystemExit(1)
