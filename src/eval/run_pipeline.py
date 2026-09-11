"""Main pipeline execution entry point for evaluation runs."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline in evaluation mode.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["demo", "eval"],
        required=True,
        help="Run mode: demo (human confirmation) or eval (gold decisions)",
    )
    parser.add_argument(
        "--candidate-source",
        type=str,
        choices=["gold", "extracted"],
        required=True,
        help="Source of candidates: gold (injected) or extracted (LLM-1)",
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
        f"run_pipeline not yet implemented: mode={args.mode}, "
        f"candidate_source={args.candidate_source}, repeat={args.repeat}"
    )


if __name__ == "__main__":
    main()
