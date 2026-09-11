"""Baseline system runner. Same logger and store, no retrieval, no engine."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the baseline system (no retrieval, no state engine)."
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["demo", "eval"],
        required=True,
        help="Run mode: demo (human confirmation) or eval (gold decisions)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        choices=[1, 2, 3],
        required=True,
        help="Repeat index for variance measurement (1, 2, or 3)",
    )
    args = parser.parse_args()

    raise NotImplementedError(
        f"run_baseline not yet implemented: mode={args.mode}, repeat={args.repeat}"
    )


if __name__ == "__main__":
    main()
