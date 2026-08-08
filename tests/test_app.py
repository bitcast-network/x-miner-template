"""Offline HTTP tests for the complete creator-facing miner flow."""

from pathlib import Path

from bitcast_x.campaigns import CampaignRecord
from bitcast_x.miner import BatchPolicy, FinalizedCommitment, MinerEngine, MinerSdk, MinerStore
from bitcast_x.miner.engine import CapacityBudget
from bitcast_x.protocol import CommitmentEnvelope, CommitmentPosition
from bitcast_x.transport import create_miner_app
from fastapi.testclient import TestClient

from x_miner_template.app import create_app
from x_miner_template.service import MinerService

MINER = "5E2FKe891uQ7Y1xQ1PLjU7WAouhkxbdJhmovEapJ2cUQv5oA"


class Submitter:
    """Finalizing in-memory chain adapter for HTTP tests."""

    async def capacity(self, _envelope: CommitmentEnvelope) -> CapacityBudget:
        return CapacityBudget(remaining_space=100, next_call_charge=100)

    async def latest(self) -> None:
        return None

    async def submit(self, envelope: CommitmentEnvelope) -> FinalizedCommitment:
        return FinalizedCommitment(
            position=CommitmentPosition(block=100, extrinsic_index=1),
            stored_envelope=envelope.encode(),
        )


class Feed:
    """Minimal campaign source for creator-facing HTTP tests."""

    async def fetch_campaigns(self) -> tuple[CampaignRecord, ...]:
        return (
            CampaignRecord.model_validate(
                {
                    "access": {
                        "campaign_id": "campaign",
                        "mechanism_id": 1,
                        "mining_protocol": "preclaim_v2",
                        "scoring_close_block": 100,
                    },
                    "title": "Campaign",
                    "brief": "Write an original post.",
                    "ecosystem_id": "tao",
                    "opens_at": "2026-08-01T00:00:00Z",
                    "closes_at": "2026-08-10T00:00:00Z",
                    "reward_pool_usd": "1000",
                }
            ),
        )

    async def close(self) -> None:
        return None


def client(tmp_path: Path) -> TestClient:
    """Create an app using real durable miner state and a fake chain."""

    engine = MinerEngine(
        miner_hotkey=MINER,
        store=MinerStore(tmp_path / "miner.sqlite3"),
        submitter=Submitter(),
        policy=BatchPolicy(max_age_seconds=5),
    )
    service = MinerService(MinerSdk(engine), Feed(), 5)  # type: ignore[arg-type]
    protocol = create_miner_app(
        miner_hotkey=MINER,
        provider=engine.batch_page,
        authorize_validator=lambda _hotkey: _authorized(),
    )
    return TestClient(create_app(lambda: service, protocol))


async def _authorized() -> bool:
    return True


def test_campaign_listing_uses_campaign_metadata_source(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/campaigns")

    assert response.status_code == 200
    assert response.json()[0]["access"]["campaign_id"] == "campaign"


def test_claim_then_submission_are_finalized(tmp_path: Path) -> None:
    web = client(tmp_path)
    claim = web.post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    )
    assert claim.status_code == 200
    assert claim.json()["status"] == "safe_to_post"

    submission = web.post(
        "/api/submissions",
        json={
            "campaign_id": "campaign",
            "tweet_id": "999",
            "claim_id": claim.json()["claim_id"],
        },
    )
    assert submission.status_code == 200
    assert submission.json()["status"] == "verification_pending"


def test_rejects_non_numeric_x_identifiers(tmp_path: Path) -> None:
    response = client(tmp_path).post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "@handle", "draft": "draft"},
    )
    assert response.status_code == 422
