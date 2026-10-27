# 09 — Model deployment

Resource: `Consulting-Agent-System` in resource group `Consultant-Agent`,
Australia East, kind `AIServices`, SKU `S0`. Subscription: Azure for Students.

A second account, `Consulting-open-ai`, is in the same group and is not used.

## What is deployed

| Deployment | Model | Version | SKU | Capacity | Upgrade |
|---|---|---|---|---|---|
| `cia-chat` | `gpt-4o` | `2024-11-20` | GlobalStandard | 50 | `NoAutoUpgrade` |
| `cia-embed` | `text-embedding-3-small` | `1` | GlobalStandard | 50 | `NoAutoUpgrade` |

`cia-chat` is the chat deployment the pipeline calls. It is the only model on this
resource whose catalogue row sets `jsonSchemaResponse`. Regional Standard quota for
gpt-4o is 0, so the deployment uses GlobalStandard (450 thousand tokens per minute
available before this deployment).

`cia-embed` is deployed and is **not** the encoder retrieval scores. See below.

An older deployment, `gpt-6.1-sol` version `2026-09-29`, is already on the resource
with upgrade option `OnceNewDefaultVersionAvailable` and capacity 500. It is not the
experiment deployment. Do not repoint it.

## Which encoder retrieval uses

The active dense encoder is local:

| Field | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Version | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| Dimension | 384 |
| Config | `src/retrieve/model_config.json` (`encoder_role`: `active`) |

Track B has not measured recall@k on authored dev scenarios. The published checks are
software tests and one unit-fixture smoke of the local model. Switching the live
encoder to `text-embedding-3-small` (1536 dimensions) would not throw away a measured
recall number, and it would also not be justified by a measured failure. The
architecture keeps the Foundry embedding API as the last step of the upgrade ladder,
and it breaks offline determinism.

So `requirement_versions` are written with the local 384-dim identity. `cia-embed`
stays available for a later switch after recall is measured. Retrieval raises if a
query and a stored version disagree on `embedding_model`, `embedding_version`, or
`embedding_dim`. A 1536-dim vector is not cosine-scored against a 384-dim vector.

## Client settings

| Setting | Value |
|---|---|
| OpenAI endpoint | `https://consulting-agent-system.openai.azure.com/` |
| API version | `2024-10-21` |
| Chat deployment | `cia-chat` |
| Temperature | `0` |
| Seed | `42` |

`2024-10-21` is the GA data-plane version that documents `response_format` of type
`json_schema`. Structured outputs first appeared in `2024-08-01-preview`. The `v1`
path also supports them. Neither `latest` nor a preview version is the pin: structured
output behaviour has changed between versions.

The API version is a client choice. The CLI does not report it.

### Environment variables

```bash
AZURE_OPENAI_ENDPOINT=https://consulting-agent-system.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=cia-chat
AZURE_OPENAI_API_VERSION=2024-10-21
```

Store these in `.env` (never committed). `.env.example` lists the same names with the
non-secret values filled in. `src/llm/config.py` defaults the deployment to `cia-chat`
and the API version to `2024-10-21` when the variables are unset. The key and endpoint
are still required.

## Pricing (for cost calculation)

Rates are per 1M tokens, recorded here so they can be updated without guessing.

| Model | Input (per 1M) | Output (per 1M) |
|---|---|---|
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-4o / gpt-4o-2024-11-20 / cia-chat | $2.50 | $10.00 |

These rates are loaded from `src/llm/config.py`. The logger prices whatever model name
the response reports. `text-embedding-3-small` has no chat rate because the pipeline
does not call it.

## Structured outputs

`cia-chat` is the deployment for schema-constrained responses. Both extraction (FR05)
and classification (FR07/08) send `strict: true`. On 2026-10-26 a single call with
API version `2024-10-21`, temperature 0, and an enum schema returned
`{"label":"new"}`. The served model was `gpt-4o-2024-11-20`. The same client asked
`cia-embed` for one vector and received 1536 dimensions from `text-embedding-3-small`.
That check is not an evaluation run.

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
