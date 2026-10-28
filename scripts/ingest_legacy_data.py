"""Load only the configured isolated project's CSV; default refuses replacement."""

import argparse
from src.config import get_settings
from src.services.loader import load_telemetry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    count = load_telemetry(get_settings(), replace=args.replace)
    print(f"Loaded {count} records into the isolated project database.")


if __name__ == "__main__":
    main()
