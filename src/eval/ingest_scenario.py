"""Load authored meetings plus gold event file into the database."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a scenario (meetings + gold events) into the database."
    )
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        help="Path to scenario directory (e.g., scenarios/dev/D1)",
    )
    args = parser.parse_args()

    raise NotImplementedError(f"ingest_scenario not yet implemented: {args.scenario}")


if __name__ == "__main__":
    main()
