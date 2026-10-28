"""Provision the local demo's operator password hash without putting secrets in chat or argv."""

from getpass import getpass
import os
from src.config import PROJECT_ROOT
from src.services.approvals import password_hash


def main():
    operator = input("Operator name [dispatcher]: ").strip() or "dispatcher"
    if (
        not operator.isascii()
        or not operator.replace("-", "").replace("_", "").isalnum()
        or len(operator) > 64
    ):
        raise SystemExit("Use up to 64 letters, digits, underscores or hyphens.")
    password = getpass("New operator password (12–256 characters): ")
    if password != getpass("Repeat password: "):
        raise SystemExit("Passwords did not match; nothing changed.")
    encoded = password_hash(password)
    path = PROJECT_ROOT / ".env"
    current = path.read_text() if path.exists() else ""
    lines = [
        line
        for line in current.splitlines()
        if not line.startswith(("APPROVAL_OPERATOR=", "APPROVAL_PASSWORD_HASH="))
    ]
    lines.extend(
        [f"APPROVAL_OPERATOR={operator}", f"APPROVAL_PASSWORD_HASH='{encoded}'"]
    )
    temporary = path.with_name(".env.operator-tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(lines) + "\n")
    os.replace(temporary, path)
    print(
        "Operator configured. Restart the CLI/Streamlit process to load the new settings. No password was displayed."
    )


if __name__ == "__main__":
    main()
