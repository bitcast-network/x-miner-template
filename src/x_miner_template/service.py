"""Application service joining campaign discovery to the Bitcast miner SDK."""

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Protocol, cast

from bitcast_x.campaigns import CampaignRecord
from bitcast_x.errors import ProtocolError
from bitcast_x.miner.engine import MinerSdk
from bitcast_x.miner.store import EventStatus

from x_miner_template.results import MinerResultsClient

LOGGER = logging.getLogger(__name__)


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
    results_client: MinerResultsClient | None = None

    async def campaigns(self) -> list[dict[str, object]]:
        """Return open-campaign fields needed to complete the miner flow."""

        if self.results_client is not None:
            public_campaigns = list(await self.results_client.campaigns())
            return [campaign for campaign in public_campaigns if self._can_serve(campaign)]
        feed_campaigns = await self.campaign_source.fetch_campaigns()
        return [
            campaign.model_dump(mode="json")
            for campaign in feed_campaigns
            if self._can_serve(campaign.model_dump(mode="json"))
        ]

    def _can_serve(self, campaign: dict[str, object]) -> bool:
        access = campaign.get("access")
        if not isinstance(access, dict):
            return False
        exclusive = access.get("exclusive_miner_hotkey")
        return exclusive is None or exclusive == self.sdk.engine.miner_hotkey

    async def create_claim(self, campaign_id: str, creator_x_id: str, draft: str) -> dict[str, str]:
        """Create and finalize a claim before telling a creator it is safe to post."""

        claim_id = self.sdk.create_claim(
            campaign_id=campaign_id,
            creator_x_id=creator_x_id,
            draft=draft,
        )
        await self._await_commit()
        status = self.sdk.claim_status(claim_id)
        return {"claim_id": claim_id, "status": status.value if status else "unknown"}

    async def submit_tweet(
        self, campaign_id: str, tweet_id: str, claim_id: str | None
    ) -> dict[str, str]:
        """Durably accept a tweet mapping for background commitment and verification."""

        if claim_id is not None:
            expected = self._claim_campaign_id(claim_id)
            if expected is None:
                raise ProtocolError("submission claim_id does not belong to this miner")
            if expected != campaign_id:
                raise ProtocolError(
                    f"campaign_id {campaign_id!r} does not match claim campaign {expected!r}"
                )

        submission_id = self.sdk.submit_tweet(
            campaign_id=campaign_id,
            tweet_id=tweet_id,
            claim_id=claim_id,
        )
        status = self.sdk.submission_status(submission_id)
        return {
            "submission_id": submission_id,
            "status": status.value if status else "unknown",
        }

    async def _await_commit(self) -> None:
        """Wait briefly for finalization; durable work continues in the background on timeout."""

        try:
            await asyncio.wait_for(
                self.sdk.engine.commit_ready(force=True),
                timeout=self.commit_timeout_seconds,
            )
        except TimeoutError:
            return

    def claim_status(self, claim_id: str) -> dict[str, str]:
        """Read one durable claim status."""

        status = self.sdk.claim_status(claim_id)
        if status is None:
            return {"claim_id": claim_id, "status": "not_found"}
        result = {"claim_id": claim_id, "status": status.value}
        campaign_id = self._claim_campaign_id(claim_id)
        if campaign_id is not None:
            result["campaign_id"] = campaign_id
        return result

    def submission_status(self, submission_id: str) -> dict[str, str]:
        """Read one durable submission status."""

        status = self.sdk.submission_status(submission_id)
        return {
            "submission_id": submission_id,
            "status": status.value if status else "not_found",
        }

    async def submissions(self) -> list[dict[str, object]]:
        """Return durable submissions enriched with the latest validator evaluation."""

        submissions = cast(list[dict[str, object]], self.sdk.submissions())
        if self.results_client is None:
            return submissions
        output: list[dict[str, object]] = []
        for submission in submissions:
            try:
                result = await self.results_client.submission(str(submission["submission_id"]))
            except Exception:
                LOGGER.exception(
                    "submission result lookup failed; returning durable local state",
                    extra={"submission_id": submission["submission_id"]},
                )
                output.append(submission)
            else:
                output.append({**submission, **result})
        return output

    async def sync_submission_results(self) -> None:
        """Poll central attribution results for every locally pending submission."""

        if self.results_client is None:
            return
        for submission in self.sdk.submissions():
            if submission["status"] != EventStatus.VERIFICATION_PENDING.value:
                continue
            submission_id = str(submission["submission_id"])
            try:
                result = await self.results_client.submission(submission_id)
            except Exception:
                LOGGER.exception(
                    "submission result sync failed; local state retained",
                    extra={"submission_id": submission_id},
                )
                continue
            status = result.get("status")
            if status == EventStatus.ATTRIBUTED.value:
                self.sdk.record_submission_result(submission_id, EventStatus.ATTRIBUTED)
            elif status == EventStatus.REJECTED.value:
                self.sdk.record_submission_result(submission_id, EventStatus.REJECTED)

    def _claim_campaign_id(self, claim_id: str) -> str | None:
        """Read the campaign bound to a durable claim event."""

        with sqlite3.connect(self.sdk.engine.store.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM events WHERE event_id = ? AND kind = 'claim'",
                (claim_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        campaign_id = payload.get("campaign_id")
        return campaign_id if isinstance(campaign_id, str) else None

    async def qualification(self) -> dict[str, object]:
        """Read current on-chain miner qualification."""

        result = await self.sdk.qualification_status()
        return dict(result)
