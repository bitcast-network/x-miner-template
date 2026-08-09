"""Production composition root for the web miner process."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import uvicorn
from bitcast_x.campaigns import CampaignFeedClient
from bitcast_x.config import Settings
from bitcast_x.errors import ChainOperationError
from bitcast_x.logging import configure_logging
from bitcast_x.miner.service import build_sdk, load_wallet
from bitcast_x.transport import create_miner_app
from fastapi import FastAPI

from x_miner_template.app import create_app
from x_miner_template.config import WebSettings
from x_miner_template.service import MinerService

LOGGER = logging.getLogger(__name__)


def build_app(protocol_settings: Settings, web_settings: WebSettings) -> FastAPI:
    """Build a chain-backed app and its managed startup lifecycle."""

    if protocol_settings.campaign_feed_url is None:
        raise ValueError("BITCAST_X_CAMPAIGN_FEED_URL is required")
    if protocol_settings.public_ip is None:
        raise ValueError("BITCAST_X_PUBLIC_IP is required")

    wallet = load_wallet(protocol_settings)
    runtime: dict[str, Any] = {"ready": False}

    async def is_ready() -> bool:
        return bool(runtime["ready"])

    async def authorize_validator(hotkey: str) -> bool:
        chain = runtime.get("chain")
        if chain is None:
            return False
        metagraph = await chain.metagraph()
        if metagraph is None:
            return False
        neuron = metagraph.by_hotkey(hotkey)
        return neuron is not None and bool(neuron.validator_permit)

    protocol_app = create_miner_app(
        miner_hotkey=str(wallet.hotkey.ss58_address),
        provider=lambda request, caller: get_service().sdk.engine.batch_page(request, caller),
        authorize_validator=authorize_validator,
        max_request_bytes=protocol_settings.max_request_bytes,
        auth_max_age=protocol_settings.auth_max_age_seconds,
        auth_allowed_skew=protocol_settings.auth_allowed_skew_seconds,
        requests_per_minute=protocol_settings.validator_requests_per_minute,
        readiness=is_ready,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        chain, sdk = await build_sdk(protocol_settings)
        campaign_source = CampaignFeedClient(
            protocol_settings.campaign_feed_url,
            cache_path=protocol_settings.state_dir / "campaign-feed.json",
            timeout=protocol_settings.request_timeout_seconds,
            max_response_bytes=protocol_settings.max_response_bytes,
        )
        runtime["chain"] = chain
        runtime["service"] = MinerService(
            sdk=sdk,
            campaign_source=campaign_source,
            commit_timeout_seconds=web_settings.force_commit_timeout_seconds,
        )
        commit_task: asyncio.Task[None] | None = None

        async def commit_loop() -> None:
            while True:
                try:
                    await sdk.engine.commit_ready()
                except Exception:
                    LOGGER.exception("queued commitment failed; durable state retained")
                await asyncio.sleep(min(0.5, protocol_settings.batch_max_age_seconds / 2))

        try:
            try:
                await chain.advertise_endpoint(
                    wallet,
                    ip=protocol_settings.public_ip,
                    port=protocol_settings.port,
                )
            except ChainOperationError:
                LOGGER.exception(
                    "endpoint advertisement failed; continuing with existing on-chain axon if any"
                )
            commit_task = asyncio.create_task(commit_loop())
            runtime["ready"] = True
            LOGGER.info("miner ready hotkey=%s", sdk.engine.miner_hotkey)
            yield
        finally:
            runtime["ready"] = False
            if commit_task is not None:
                commit_task.cancel()
                with suppress(asyncio.CancelledError):
                    await commit_task
            await campaign_source.close()
            await chain.close()

    def get_service() -> MinerService:
        service = runtime.get("service")
        if not isinstance(service, MinerService):
            raise RuntimeError("miner service is not ready")
        return service

    app = create_app(get_service, protocol_app)
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    """Load configuration and run one web/miner server."""

    protocol_settings = Settings()
    configure_logging(
        level=protocol_settings.log_level,
        json_output=protocol_settings.log_format == "json",
    )
    app = build_app(protocol_settings, WebSettings())
    uvicorn.run(app, host=protocol_settings.host, port=protocol_settings.port)


if __name__ == "__main__":
    main()
