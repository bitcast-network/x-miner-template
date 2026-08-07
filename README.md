# Bitcast X miner template

A minimal, deployable miner website for Bitcast X v3 (SN93 mechanism 1). It provides the complete
creator flow and runs the miner protocol in the same process:

1. Load the public campaign feed and on-chain qualification status.
2. Commit an exact draft with the registered miner hotkey.
3. Wait for finalization before showing `safe_to_post`.
4. Accept the published tweet URL or ID and commit its mapping to the claim.
5. Serve finalized batches to validator-permitted hotkeys over Bittensor v11 signed HTTP.

There is intentionally no user authentication, database server, frontend framework, branding, or
platform-specific payout logic. Durable SQLite state and browser-local operation IDs make the flow
survive process and page restarts. Consensus-sensitive batching, signing, validator authorization,
commitment capacity, recovery, and chain communication come directly from a commit-pinned
`bitcast-x-v3` dependency.

## What “verification” means

`safe_to_post` means the draft claim has been finalized and independently read back from chain.
After the tweet is submitted, `verification_pending` means validators can fetch and independently
check the tweet, author, campaign eligibility, qualification, timing, draft match, and attribution.
The current protocol does not send the validator's eventual verdict back to the miner, so this
template does not invent an immediate accepted/rejected result.

## Requirements

- Python 3.12 or Docker
- A Bittensor coldkey/hotkey already registered as a miner on netuid 93
- A public IPv4 address and inbound TCP port 8095
- The published campaign-feed and qualification configuration
- Persistent storage for `/var/lib/bitcast-x`

The process loads existing Bittensor keys. It never creates, imports, or copies them. The hotkey
must be available inside the standard wallet tree configured by `BITCAST_X_WALLET_PATH`.

## Run locally

```bash
cp .env.example .env
# Edit the placeholders in .env.
uv sync --all-extras
uv run x-miner-template
```

Open `http://localhost:8095`. Useful machine endpoints are:

- `GET /health` — process and protocol version
- `GET /ready` — endpoint advertisement completed
- `GET /api/docs` — UI API documentation
- `POST /v2/batches` — signed, validator-only protocol endpoint

## Run with Docker

The source protocol repository is private, so the image build needs GitHub read access in the
environment performing the build. The finished image does not contain Git credentials.

```bash
GITHUB_TOKEN="$(gh auth token)" docker build \
  --secret id=github_token,env=GITHUB_TOKEN \
  -t x-miner-template .
docker run --rm -p 8095:8095 --env-file .env \
  -v "$PWD/state:/var/lib/bitcast-x" \
  -v "$HOME/.bittensor/wallets:/home/miner/.bittensor/wallets:ro" \
  x-miner-template
```

Use a real persistent volume in production. Losing `miner.sqlite3` loses the private draft reveals
needed to prove subsequent submissions. Run exactly one process/replica per wallet and state
volume; this is a stateful miner, not a horizontally replicated stateless website.

## Configuration

All protocol configuration uses the upstream `BITCAST_X_` environment variables. The minimal set
is documented in [.env.example](.env.example). `X_MINER_FORCE_COMMIT_TIMEOUT_SECONDS` controls how
long a UI request waits for chain finalization; a timeout is safe because the event and any
prepared batch remain durable and recoverable.

Do not expose the wallet directory through the web server, bake keys into an image, or commit an
`.env` file. TLS and basic network hardening belong at the deployment boundary (for example a
load balancer or reverse proxy); validator messages remain hotkey-signed end to end.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The template deliberately depends on a specific reviewed `bitcast-x-v3` commit. Upgrade that pin
explicitly after reviewing its protocol compatibility notes and rerunning this repository's gates.
