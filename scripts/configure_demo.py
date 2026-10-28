"""Configure separate viewer/operator credentials locally; never print password values."""

import argparse
from getpass import getpass
import os
import secrets
from src.config import PROJECT_ROOT
from src.services.approvals import password_hash


def configure(generate=False):
    if generate and (PROJECT_ROOT / "data/control/first-login.txt").exists():
        raise SystemExit(
            "Existing private credential handoff file detected; nothing changed."
        )
    if generate:
        viewer, operator = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    else:
        viewer = getpass("New viewer password (12–256 characters): ")
        if viewer != getpass("Repeat viewer password: "):
            raise SystemExit("Passwords did not match; nothing changed.")
        operator = getpass("New, different simulation operator password: ")
        if operator != getpass("Repeat operator password: ") or viewer == operator:
            raise SystemExit(
                "Passwords must match their confirmation and be different."
            )
    viewer_hash, operator_hash = password_hash(viewer), password_hash(operator)
    path = PROJECT_ROOT / ".env"
    existing = path.read_text() if path.exists() else ""
    replace = {
        "DEMO_USER": "reviewer",
        "DEMO_PASSWORD_HASH": viewer_hash,
        "APPROVAL_OPERATOR": "dispatcher",
        "APPROVAL_PASSWORD_HASH": operator_hash,
    }
    # Refuse silent credential rotation; rerun interactively only after explicit local removal.
    from dotenv import dotenv_values

    values = dotenv_values(path)
    if values.get("DEMO_PASSWORD_HASH") or values.get("APPROVAL_PASSWORD_HASH"):
        raise SystemExit(
            "Existing access/operator credentials detected; preserve them. Remove the specific entries locally if you intend to rotate them."
        )
    lines = [
        line
        for line in existing.splitlines()
        if not any(line.startswith(key + "=") for key in replace)
    ]
    lines.extend(f"{key}='{value}'" for key, value in replace.items())
    temp = path.with_name(".env.demo-tmp")
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(lines) + "\n")
    os.replace(temp, path)
    if generate:
        directory = PROJECT_ROOT / "data/control"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        credential_path = directory / "first-login.txt"
        fd = os.open(credential_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(
                f"Local invite-only demo credentials. Keep private.\nViewer username: reviewer\nViewer password: {viewer}\n\nSimulation operator: dispatcher\nOperator password: {operator}\n\nNo real notifications are sent. Restart the app after configuration.\n"
            )
        print(
            "Generated separate credentials in ignored data/control/first-login.txt (mode 600). Passwords were not printed."
        )
    else:
        print(
            "Viewer and operator password hashes configured. Restart the app; passwords were not printed."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Save random separate passwords to a private ignored local file rather than prompts.",
    )
    configure(parser.parse_args().generate)


if __name__ == "__main__":
    main()
