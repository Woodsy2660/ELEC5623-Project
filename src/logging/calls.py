"""Shared model-call logger for all LLM stages.

Every model call in the codebase goes through call_model(). There must be no
other call site that touches the client directly.

See docs/09-model-deployment.md for deployment configuration.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AzureOpenAI
from openai.types.chat import ChatCompletion

from src.llm.config import compute_cost


class ModelCallError(Exception):
    """Error during model call (schema failure, parse error, etc.)."""

    pass


@dataclass(frozen=True)
class ParsedResponse:
    """Result of a successful model call."""

    call_id: str
    content: str
    input_tokens: int
    output_tokens: int
    served_model: str
    latency_ms: int
    retries: int


def _compute_prompt_hash(prompt_path: Path) -> str:
    """Compute git blob hash of the prompt file."""
    content = prompt_path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def _write_raw_response(
    run_id: str,
    call_id: str,
    response: ChatCompletion,
    runs_dir: Path,
) -> str:
    """Write raw response JSON to disk and return the path."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_path = run_dir / f"{call_id}.json"
    raw_path.write_text(
        json.dumps(response.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return str(raw_path)


def call_model(
    client: AzureOpenAI,
    *,
    run_id: str,
    stage: str,
    prompt_path: Path,
    messages: list[dict[str, str]],
    response_format: dict[str, Any] | None = None,
    deployment_name: str,
    temperature: float = 0.0,
    seed: int | None = 42,
    runs_dir: Path = Path("runs"),
) -> tuple[ParsedResponse, dict[str, Any]]:
    """Make a model call with logging.

    Args:
        client: Azure OpenAI client.
        run_id: Run ID for this pipeline execution.
        stage: Pipeline stage (e.g., "extract", "classify").
        prompt_path: Path to the versioned prompt file.
        messages: Chat messages to send.
        response_format: Optional JSON schema for structured output.
        deployment_name: Deployment name we're requesting.
        temperature: Temperature setting.
        seed: Random seed for reproducibility.
        runs_dir: Directory for storing raw responses.

    Returns:
        Tuple of (ParsedResponse, row_data for model_calls table).

    Raises:
        ModelCallError: On schema failure after retry.
    """
    call_id = str(uuid.uuid4())
    prompt_hash = _compute_prompt_hash(prompt_path)

    # Build request kwargs
    kwargs: dict[str, Any] = {
        "model": deployment_name,
        "messages": messages,
        "temperature": temperature,
    }
    if seed is not None:
        kwargs["seed"] = seed
    if response_format is not None:
        kwargs["response_format"] = response_format

    retries = 0
    last_error: Exception | None = None

    for attempt in range(2):  # Max one retry
        start_time = time.perf_counter()

        try:
            response = client.chat.completions.create(**kwargs)
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract response data
            content = response.choices[0].message.content or ""
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0

            # Get served model from response (what actually answered)
            served_model = response.model or deployment_name

            # Write raw response to disk
            raw_json_path = _write_raw_response(run_id, call_id, response, runs_dir)

            # Compute cost
            cost = compute_cost(served_model, input_tokens, output_tokens)

            # Build row data for model_calls table
            row_data = {
                "id": call_id,
                "run_id": run_id,
                "stage": stage,
                "deployment_name": deployment_name,
                "served_model": served_model,
                "prompt_hash": prompt_hash,
                "temperature": temperature,
                "seed": seed,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "retries": retries,
                "cost": cost,
                "raw_json_path": raw_json_path,
            }

            parsed = ParsedResponse(
                call_id=call_id,
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                served_model=served_model,
                latency_ms=latency_ms,
                retries=retries,
            )

            return parsed, row_data

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            last_error = e

            if attempt == 0:
                # First failure - retry once
                retries = 1
                continue
            else:
                # Second failure - raise
                raise ModelCallError(f"Model call failed after retry: {e}") from e

    # Should never reach here, but for type safety
    raise ModelCallError(f"Model call failed: {last_error}")


class CallLogger:
    """Context manager for logging model calls to the database.

    Usage:
        with CallLogger(session, client, config) as logger:
            result = logger.call(
                run_id=run_id,
                stage="extract",
                prompt_path=prompt_path,
                messages=messages,
                response_format=schema,
            )
    """

    def __init__(
        self,
        session: Any,  # SQLAlchemy Session
        client: AzureOpenAI,
        deployment_name: str,
        temperature: float = 0.0,
        seed: int | None = 42,
        runs_dir: Path = Path("runs"),
    ):
        self.session = session
        self.client = client
        self.deployment_name = deployment_name
        self.temperature = temperature
        self.seed = seed
        self.runs_dir = runs_dir

    def __enter__(self) -> "CallLogger":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def call(
        self,
        *,
        run_id: str,
        stage: str,
        prompt_path: Path,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
    ) -> ParsedResponse:
        """Make a logged model call.

        Returns:
            ParsedResponse with the model's output.

        Raises:
            ModelCallError: On failure after retry.
        """
        from src.persist.models import ModelCall

        parsed, row_data = call_model(
            self.client,
            run_id=run_id,
            stage=stage,
            prompt_path=prompt_path,
            messages=messages,
            response_format=response_format,
            deployment_name=self.deployment_name,
            temperature=self.temperature,
            seed=self.seed,
            runs_dir=self.runs_dir,
        )

        # Insert row into model_calls table
        model_call = ModelCall(**row_data)
        self.session.add(model_call)
        self.session.flush()

        return parsed
