"""Application service joining campaign discovery to the Bitcast miner SDK."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from bitcast_x.campaigns import CampaignRecord
from bitcast_x.miner.engine import MinerSdk


class CampaignSource(Protocol):
    """Campaign feed operations required by the web application."""

    async def fetch_campaigns(self) -> tuple[CampaignRecord, ...]: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class MinerService:
    """Small use-case layer with explicit commitment completion semantics."""

    sdk: MinerSdk
    campaign_source: CampaignSource
    commit_timeout_seconds: float

    async def campaigns(self) -> list[dict[str, object]]:
        """Return open-campaign fields needed to complete the miner flow."""

        campaigns = await self.campaign_source.fetch_campaigns()
        return [campaign.model_dump(mode="json") for campaign in campaigns]

    async def create_claim(self, campaign_id: str, creator_x_id: str, draft: str) -> dict[str, str]:
        """Create and finalize a claim before telling a creator it is safe to post."""

        claim_id = self.sdk.create_claim(
            campaign_id=campaign_id,
            creator_x_id=creator_x_id,
            draft=draft,
        )
        await asyncio.wait_for(
            self.sdk.engine.commit_ready(force=True),
            timeout=self.commit_timeout_seconds,
        )
        status = self.sdk.claim_status(claim_id)
        return {"claim_id": claim_id, "status": status.value if status else "unknown"}

    async def submit_tweet(
        self, campaign_id: str, tweet_id: str, claim_id: str | None
    ) -> dict[str, str]:
        """Commit a published tweet mapping for validator retrieval and verification."""

        submission_id = self.sdk.submit_tweet(
            campaign_id=campaign_id,
            tweet_id=tweet_id,
            claim_id=claim_id,
        )
        await asyncio.wait_for(
            self.sdk.engine.commit_ready(force=True),
            timeout=self.commit_timeout_seconds,
        )
        status = self.sdk.submission_status(submission_id)
        return {
            "submission_id": submission_id,
            "status": status.value if status else "unknown",
        }

    def claim_status(self, claim_id: str) -> dict[str, str]:
        """Read one durable claim status."""

        status = self.sdk.claim_status(claim_id)
        return {"claim_id": claim_id, "status": status.value if status else "not_found"}

    def submission_status(self, submission_id: str) -> dict[str, str]:
        """Read one durable submission status."""

        status = self.sdk.submission_status(submission_id)
        return {
            "submission_id": submission_id,
            "status": status.value if status else "not_found",
        }

    async def qualification(self) -> dict[str, object]:
        """Read current on-chain miner qualification."""

        result = await self.sdk.qualification_status()
        return dict(result)
