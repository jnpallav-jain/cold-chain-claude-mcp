"""Pause/resume model admission or inspect readiness locally; no secret values are printed."""

import argparse
import json
from src.config import get_settings
from src.services.demo import DemoControl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stop", "resume", "status"])
    args = parser.parse_args()
    control = DemoControl(get_settings())
    if args.action == "stop":
        control.stop_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        control.stop_path.write_text("Paused by local operator.\n")
    elif args.action == "resume":
        control.stop_path.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "configured": control.configured,
                "paused": control.stop_path.exists(),
                "action": args.action,
                "scope": "Admission only; already running calls are not cancelled. Stop the app process/container for immediate shutdown.",
            }
        )
    )


if __name__ == "__main__":
    main()
