"""Scoring module for E2, E3, E5 and related metrics.

This is the only module permitted to read gold_events.
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a completed run against gold data.")
    parser.add_argument(
        "--run",
        type=str,
        required=True,
        help="Run ID to score",
    )
    args = parser.parse_args()

    raise NotImplementedError(f"score not yet implemented: run={args.run}")


if __name__ == "__main__":
    main()
