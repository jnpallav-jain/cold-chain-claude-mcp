"""Start the authenticated Streamlit demo, failing closed if configuration is missing."""

import argparse
import os
import sys
from src.config import Settings, PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged port from 1024 to 65535.")
    os.environ["DEMO_MODE"] = "true"
    settings = Settings()
    settings.require(
        "demo_password_hash",
        "anthropic_api_key",
        "pinecone_api_key",
        "sql_agent_password",
    )
    os.chdir(PROJECT_ROOT)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/ui.py",
            "--server.headless=true",
            "--server.address=" + args.bind,
            "--server.port=" + str(args.port),
        ],
    )


if __name__ == "__main__":
    main()
