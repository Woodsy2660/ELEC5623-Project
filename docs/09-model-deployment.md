# 09 — Model deployment

## Azure OpenAI configuration

The project uses Azure OpenAI Service via the Microsoft Foundry deployment. All model calls
are pinned to a specific deployment and version for reproducibility.

### Deployment settings

| Setting | Value |
|---------|-------|
| Endpoint | `https://<resource>.openai.azure.com/` |
| API Version | `2024-08-01-preview` |
| Deployment name | `gpt-4o-mini` |
| Model version | `2024-07-18` |
| Temperature | `0` |
| Seed | `42` (for reproducibility within variance bounds) |

### Environment variables

```bash
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

Store these in `.env` (never committed). `.env.example` lists the variable names only.

## Pricing (for cost calculation)

Rates are per 1M tokens, recorded here so they can be updated without code changes.

| Model | Input (per 1M) | Output (per 1M) |
|-------|----------------|-----------------|
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-4o | $2.50 | $10.00 |

These rates are loaded from `src/llm/config.py` and used by the call logger to compute
per-call cost. Update the config when rates change.

## Structured outputs

The deployment supports structured outputs with JSON schema enforcement in strict mode.
This was confirmed by the smoke test. Both extraction (FR05) and classification (FR07/08)
use schema-constrained responses.

Request parameters for strict mode:
```python
response_format={
    "type": "json_schema",
    "json_schema": {
        "name": "extraction_result",
        "strict": True,
        "schema": schema_dict
    }
}
```

## Logging

Every model call is logged to `model_calls` with:
- `deployment_name`: what we requested (from config)
- `served_model`: what actually responded (from response headers/body)
- `prompt_hash`: git blob hash of the prompt file
- `temperature`, `seed`: settings used
- `input_tokens`, `output_tokens`: from usage in response
- `latency_ms`: wall-clock time
- `retries`: 0 or 1 (max one retry on schema failure)
- `cost`: computed from rates
- `raw_json_path`: path to raw response JSON on disk

Raw responses are written to `runs/<run_id>/<call_id>.json`, not stored in SQLite.
