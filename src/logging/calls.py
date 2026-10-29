"""Shared model-call logger for all LLM stages.

Every model call in the codebase goes through call_model(). There must be no
other call site that touches the client directly.

See docs/09-model-deployment.md for deployment configuration.
"""

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AzureOpenAI

from src.llm.config import compute_cost


class ModelCallError(Exception):
    """Error during model call (schema failure, parse error, etc.)."""

    def __init__(self, message: str, *, call_ids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.call_ids = call_ids


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


def _write_payload(run_id: str, call_id: str, payload: dict[str, Any], runs_dir: Path) -> str:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{call_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _safe_error(exc: Exception) -> dict[str, Any]:
    """Retain diagnostic codes, never exception text, headers, URLs or request bodies."""
    error: dict[str, Any] = {"type": type(exc).__name__}
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        error["http_status"] = status
    code = getattr(exc, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
        error["code"] = code
    return error


def _request_client(client: AzureOpenAI) -> AzureOpenAI:
    # SDK retries would hide HTTP attempts from this logger's explicit retry loop.
    return client.with_options(max_retries=0) if isinstance(client, AzureOpenAI) else client


def _attempt_row(
    *,
    run_id: str,
    call_id: str,
    stage: str,
    deployment_name: str,
    prompt_hash: str,
    temperature: float,
    seed: int | None,
    attempt: int,
    logical_call_id: str,
    latency_ms: int,
    runs_dir: Path,
    response: Any = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    payload = response.model_dump() if response is not None else {}
    usage = payload.get("usage")
    known = (
        isinstance(usage, dict)
        and isinstance(usage.get("prompt_tokens"), int)
        and isinstance(
            usage.get("completion_tokens", 0)
            if stage == "embed"
            else usage.get("completion_tokens"),
            int,
        )
    )
    payload["_call_trace"] = {
        "outcome": "failed" if error is not None else "success",
        "usage_known": known,
        "attempt_index": attempt,
        "logical_call_id": logical_call_id,
        "error": _safe_error(error) if error is not None else None,
    }
    # Keep the existing non-null SQL row contract. These numeric zero placeholders
    # are unknown, not free calls; E8 reads _call_trace and emits null totals.
    input_tokens = usage["prompt_tokens"] if known else 0
    output_tokens = usage.get("completion_tokens", 0) if known else 0
    served_model = payload.get("model") or "unknown"
    return {
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
        "retries": attempt,
        "cost": compute_cost(served_model, input_tokens, output_tokens) if known else 0.0,
        "raw_json_path": _write_payload(run_id, call_id, payload, runs_dir),
    }


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
    record_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[ParsedResponse, dict[str, Any]]:
    """Log every transport attempt; preserve the final response/row return contract.

    Persistence errors propagate without issuing another paid request. The shared
    caller retries provider errors once; SDK retries are disabled for this call.
    """
    prompt_hash = _compute_prompt_hash(prompt_path)
    kwargs: dict[str, Any] = {
        "model": deployment_name,
        "messages": messages,
        "temperature": temperature,
    }
    if seed is not None:
        kwargs["seed"] = seed
    if response_format is not None:
        kwargs["response_format"] = response_format
    request_client = _request_client(client)
    call_ids = []
    for attempt in range(2):
        call_id = str(uuid.uuid4())
        call_ids.append(call_id)
        start_time = time.perf_counter()
        response, error = None, None
        try:
            response = request_client.chat.completions.create(**kwargs)
        except Exception as exc:
            error = exc
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        row = _attempt_row(
            run_id=run_id,
            call_id=call_id,
            stage=stage,
            deployment_name=deployment_name,
            prompt_hash=prompt_hash,
            temperature=temperature,
            seed=seed,
            attempt=attempt,
            logical_call_id=call_ids[0],
            latency_ms=latency_ms,
            runs_dir=runs_dir,
            response=response,
            error=error,
        )
        if record_attempt is not None:
            record_attempt(row)
        if error is not None:
            if attempt == 0:
                continue
            raise ModelCallError(
                f"Model call failed after retry: {_safe_error(error)}; calls={','.join(call_ids)}",
                call_ids=tuple(call_ids),
            ) from None
        if not response.choices:
            raise ModelCallError("Model response contained no choices", call_ids=tuple(call_ids))
        parsed = ParsedResponse(
            call_id=call_id,
            content=response.choices[0].message.content or "",
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            served_model=row["served_model"],
            latency_ms=latency_ms,
            retries=attempt,
        )
        return parsed, row
    raise AssertionError("Unreachable retry state")


def accounting_from_raw(path: str) -> dict[str, Any]:
    """Read trace flags for E8 without changing the shared ModelCall SQL contract."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"outcome": "unknown", "usage_known": False}
    if not isinstance(payload, dict):
        return {"outcome": "unknown", "usage_known": False}
    trace = payload.get("_call_trace")
    if isinstance(trace, dict):
        return {
            "outcome": trace.get("outcome", "unknown"),
            "usage_known": trace.get("usage_known") is True,
        }
    # Older raw provider responses and local encoder traces remain readable.
    if "model_id" in payload and "input_tokens" in payload:
        return {"outcome": "failed" if payload.get("error") else "success", "usage_known": True}
    usage = payload.get("usage")
    return {
        "outcome": "success" if "choices" in payload or "data" in payload else "unknown",
        "usage_known": isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int),
    }


def call_embedding(
    client: AzureOpenAI,
    *,
    run_id: str,
    deployment_name: str,
    texts: list[str],
    runs_dir: Path = Path("runs"),
    record_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[tuple[float, ...]], dict[str, Any]]:
    """Embed a batch. This is the only ``embeddings.create`` call site.

    The row uses stage ``embed`` so E8 can see it beside chat calls.
    """
    from src.llm.config import FOUNDRY_EMBED_MODEL, FOUNDRY_EMBED_VERSION

    if not texts or any(not text.strip() for text in texts):
        raise ModelCallError("Embedding input must be a nonempty batch of nonblank texts")
    call_id = str(uuid.uuid4())
    identity = f"{deployment_name}|{FOUNDRY_EMBED_MODEL}|{FOUNDRY_EMBED_VERSION}".encode()
    prompt_hash = hashlib.sha1(f"blob {len(identity)}\0".encode() + identity).hexdigest()
    start_time = time.perf_counter()
    response, error = None, None
    try:
        response = _request_client(client).embeddings.create(
            model=deployment_name, input=list(texts)
        )
    except Exception as exc:
        error = exc
    row = _attempt_row(
        run_id=run_id,
        call_id=call_id,
        stage="embed",
        deployment_name=deployment_name,
        prompt_hash=prompt_hash,
        temperature=0.0,
        seed=None,
        attempt=0,
        logical_call_id=call_id,
        latency_ms=int((time.perf_counter() - start_time) * 1000),
        runs_dir=runs_dir,
        response=response,
        error=error,
    )
    if record_attempt is not None:
        record_attempt(row)
    if error is not None:
        raise ModelCallError(
            f"Embedding call failed: {_safe_error(error)}; call={call_id}",
            call_ids=(call_id,),
        ) from None
    ordered = sorted(response.data, key=lambda item: item.index)
    return [tuple(float(value) for value in item.embedding) for item in ordered], row


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
        parsed, _ = call_model(
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
            record_attempt=self._record_attempt,
        )
        return parsed

    def embed(self, *, run_id: str, texts: list[str]) -> list[tuple[float, ...]]:
        """Log one embedding batch against cia-embed, not the chat deployment."""
        from src.llm.config import FOUNDRY_EMBED_DEPLOYMENT

        vectors, _ = call_embedding(
            self.client,
            run_id=run_id,
            deployment_name=FOUNDRY_EMBED_DEPLOYMENT,
            texts=texts,
            runs_dir=self.runs_dir,
            record_attempt=self._record_attempt,
        )
        return vectors

    def _record_attempt(self, row: dict[str, Any]) -> None:
        """Audit independently of later candidate/register rollback, like local encodes.

        The run must already be committed and the caller must not hold a write lock.
        This logger never commits the caller's pending business changes.
        """
        from sqlalchemy.orm import Session

        from src.persist.models import ModelCall

        with Session(bind=self.session.get_bind()) as trace, trace.begin():
            trace.add(ModelCall(**row))
