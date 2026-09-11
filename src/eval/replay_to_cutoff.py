"""Rebuild expected vs actual state from events up to a meeting cutoff."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay events to rebuild state after a specific meeting."
    )
    parser.add_argument(
        "--after-meeting",
        type=int,
        required=True,
        help="Meeting ordinal after which to compare state (e.g., 1, 2, 3)",
    )
    args = parser.parse_args()

    raise NotImplementedError(
        f"replay_to_cutoff not yet implemented: after_meeting={args.after_meeting}"
    )


if __name__ == "__main__":
    main()
