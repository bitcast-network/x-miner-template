"""Production composition root for the reference miner product."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from x_miner_template.app import create_app
from x_miner_template.config import Settings
from x_miner_template.node import MinerNodeClient


def build_app(settings: Settings) -> FastAPI:
    """Build a product backend that owns no Bittensor key material."""

    runtime: dict[str, MinerNodeClient] = {}

    def get_client() -> MinerNodeClient:
        return runtime["client"]

    app = create_app(settings, get_client)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        client = MinerNodeClient(
            settings.node_url,
            settings.node_token.get_secret_value(),
            timeout=settings.request_timeout_seconds,
        )
        runtime["client"] = client
        try:
            yield
        finally:
            await client.close()

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
