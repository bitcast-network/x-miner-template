# Bitcast X reference miner product

A deliberately small but complete creator product built on the Bitcast X miner application API.
It is the example a miner can copy when building a Stitch3-like experience for one or more
ecosystems.

The product can:

- show miner registration and qualification;
- discover only authorized protocol-v2 campaigns;
- filter campaigns and results across one or many enabled ecosystems;
- browse a combined account leaderboard and filter it to one enabled ecosystem;
- show campaign briefs, timing, pools, statistics and capabilities;
- check creator eligibility and rank evidence using immutable numeric X IDs;
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
| `X_MINER_REQUEST_TIMEOUT_SECONDS` | Node request timeout |
| `X_MINER_WEB_USERNAME` | Optional hosted-demo Basic Auth username |
| `X_MINER_WEB_PASSWORD` | Optional hosted-demo Basic Auth password |

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```
