"""LLM deployment configuration and pricing.

See docs/09-model-deployment.md for deployment details.
Rates are per 1M tokens. Update here when pricing changes.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRates:
    """Token pricing for a model (per 1M tokens)."""

    input_rate: float  # USD per 1M input tokens
    output_rate: float  # USD per 1M output tokens


# Pricing per 1M tokens - update when rates change.
# cia-chat serves gpt-4o 2024-11-20. Cost is looked up from the served model
# name, and also from the deployment name when that is what the response returns.
MODEL_RATES: dict[str, ModelRates] = {
    "gpt-4o-mini": ModelRates(input_rate=0.15, output_rate=0.60),
    "gpt-4o-mini-2024-07-18": ModelRates(input_rate=0.15, output_rate=0.60),
    "gpt-4o": ModelRates(input_rate=2.50, output_rate=10.00),
    "gpt-4o-2024-11-20": ModelRates(input_rate=2.50, output_rate=10.00),
    "cia-chat": ModelRates(input_rate=2.50, output_rate=10.00),
    # Azure OpenAI list price for text-embedding-3-small. Embeddings have no output tokens.
    "text-embedding-3-small": ModelRates(input_rate=0.02, output_rate=0.0),
    "cia-embed": ModelRates(input_rate=0.02, output_rate=0.0),
}

# Pinned chat deployment. See docs/09-model-deployment.md.
PINNED_API_VERSION = "2024-10-21"
CHAT_DEPLOYMENT = "cia-chat"
CHAT_MODEL = "gpt-4o"
CHAT_MODEL_VERSION = "2024-11-20"

# cia-embed is deployed and is not the encoder that retrieval scores.
# The active encoder is the 384-dim local model in src/retrieve/model_config.json.
# Mixing that space with text-embedding-3-small (1536) is an error in retrieve().
FOUNDRY_EMBED_DEPLOYMENT = "cia-embed"
FOUNDRY_EMBED_MODEL = "text-embedding-3-small"
FOUNDRY_EMBED_VERSION = "1"
FOUNDRY_EMBED_DIM = 1536

# Default rates if model not in table
DEFAULT_RATES = ModelRates(input_rate=0.15, output_rate=0.60)


@dataclass(frozen=True)
class DeploymentConfig:
    """Azure OpenAI deployment configuration."""

    endpoint: str
    api_key: str
    deployment_name: str
    api_version: str
    temperature: float = 0.0
    seed: int | None = 42


def get_deployment_config() -> DeploymentConfig:
    """Load deployment config from environment variables.

    Raises:
        ValueError: If required environment variables are missing.
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", CHAT_DEPLOYMENT)
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", PINNED_API_VERSION)

    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required")
    if not api_key:
        raise ValueError("AZURE_OPENAI_API_KEY environment variable is required")

    return DeploymentConfig(
        endpoint=endpoint,
        api_key=api_key,
        deployment_name=deployment,
        api_version=api_version,
    )


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Compute cost for a model call.

    Args:
        model: Model identifier (e.g., "gpt-4o-mini").
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Cost in USD.
    """
    rates = MODEL_RATES.get(model, DEFAULT_RATES)
    input_cost = (input_tokens / 1_000_000) * rates.input_rate
    output_cost = (output_tokens / 1_000_000) * rates.output_rate
    return input_cost + output_cost
