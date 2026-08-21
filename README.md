# Bitcast X reference miner product

A deliberately small but complete creator product built on the Bitcast X miner application API.
It is the example a miner can copy when building a Stitch3-like experience for one or more
ecosystems.

The product can:

- show miner registration and qualification;
- discover only authorized protocol-v2 campaigns;
- filter campaigns and results across one or many enabled ecosystems;
- browse every page of the combined account leaderboard and filter it to one enabled ecosystem;
- show campaign briefs, timing, pools, statistics and capabilities;
- check creator eligibility and rank evidence using immutable numeric X IDs;
- optionally reject drafts unless all three validator-compatible OpenRouter checks approve them;
- create idempotent claims and wait for `safe_to_post`;
- recover claims after browser, product or node downtime;
- submit preclaim or direct-mode tweets idempotently;
- show both claim and submission commitment proofs plus the complete validator
  decision, evaluation, attribution, score breakdown, metrics and feedback;
- open any campaign to its full brief and campaign tweets;
- show owner-private total USD reward recommendations.

Campaign publishing remains centralized in Bitcast. Creator payments remain the miner product's
responsibility and are intentionally not represented as Bitcast payment state.

## Architecture

```text
Browser
  -> this product backend (creator auth boundary)
      -> bearer-authenticated /api/v1 calls
          -> Bitcast X miner node (hotkey + durable private claims)
              -> hotkey-signed central Bitcast reads
```

The browser never receives the node bearer token or the miner hotkey. This repository owns no
Bittensor wallet code and can be deployed, replaced or scaled independently from the stateful miner
node. The bundled HTTP Basic gate is suitable for a protected reference deployment; replace it
with the product's real creator authentication and X-account association in production.

## Run locally

Run a current `bitcast-x run-miner-api` node first, then:

```bash
cp .env.example .env
# Configure X_MINER_NODE_URL and X_MINER_NODE_TOKEN.
uv sync --all-extras
uv run x-miner-template
```

Open `http://127.0.0.1:8080`. If `X_MINER_WEB_PASSWORD` is set, use the configured Basic Auth
username and password. `GET /health` remains unauthenticated for load balancers.

## Docker

```bash
docker build --no-cache -t x-miner-template .
docker run --rm -p 8080:8080 --env-file .env x-miner-template
```

The container is stateless and runs as UID 10001. The miner node, not this web product, owns the
hotkey, SQLite protocol state, chain commitments and validator batch endpoint.

## Configuration

| Variable | Purpose |
|---|---|
| `X_MINER_NODE_URL` | Private URL of the miner node |
| `X_MINER_NODE_TOKEN` | 64-character node application credential; server-side only |
| `X_MINER_HOST` / `X_MINER_PORT` | Product listener, default `0.0.0.0:8080` |
| `X_MINER_REQUEST_TIMEOUT_SECONDS` | Normal node request timeout, default 30 seconds |
| `X_MINER_CLAIM_TIMEOUT_SECONDS` | Claim commitment timeout, default 120 seconds |
| `X_MINER_OPENROUTER_API_KEY` | Optional server-side key enabling strict tweet draft prechecks |
| `X_MINER_OPENROUTER_MODEL` | OpenRouter model, default `qwen/qwen3-32b:nitro` |
| `X_MINER_OPENROUTER_TIMEOUT_SECONDS` | Timeout for each OpenRouter request, default 90 seconds |
| `X_MINER_WEB_USERNAME` | Optional hosted-demo Basic Auth username |
| `X_MINER_WEB_PASSWORD` | Optional hosted-demo Basic Auth password |

When the OpenRouter key is configured, the product runs the same frozen prompt version selected by
the campaign three times at temperature zero. The template is intentionally more conservative than
the validator: all three checks must return `YES` before the claim is forwarded. If the key is not
configured, claims continue normally and the creator sees a light warning that draft precheck is
disabled. OpenRouter outages are reported as retryable errors and never mislabelled as a brief
failure.

The frozen prompt copy currently tracks `bitcast-x` commit
`7411d34208a86d55f6fb72f2de6b3a6953f1a089`.

The campaign's `prompt_version` is mandatory while precheck is enabled. If a campaign references a
newer prompt version that this template has not copied yet, the claim fails before any chain call and
the creator is told that the template must be updated. The template never falls back to an older
prompt version silently.

Claim creation uses a longer deadline because it may wait for an on-chain batch to finalize. If that
deadline is still exceeded, the product looks up the exact durable operation by its external ID and
returns the recovered claim instead of reporting a generic server error or creating a duplicate.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```
