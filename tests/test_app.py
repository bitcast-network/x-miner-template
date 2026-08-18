"""Offline HTTP tests for the complete creator-facing miner flow."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import bittensor as bt
import httpx
from bitcast_x.campaigns import CampaignRecord
from bitcast_x.miner import BatchPolicy, FinalizedCommitment, MinerEngine, MinerSdk, MinerStore
from bitcast_x.miner.engine import CapacityBudget
from bitcast_x.protocol import CommitmentEnvelope, CommitmentPosition
from bitcast_x.transport import BatchPageRequest, SignedMinerClient, create_miner_app
from fastapi.testclient import TestClient

from x_miner_template.app import create_app
from x_miner_template.service import MinerService

MINER = "5E2FKe891uQ7Y1xQ1PLjU7WAouhkxbdJhmovEapJ2cUQv5oA"
INTERNAL_TOKEN = "test-internal-token-that-is-at-least-32-chars"  # noqa: S105


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


class SlowSubmitter(Submitter):
    """Chain adapter that exceeds the UI force-commit timeout."""

    async def submit(self, envelope: CommitmentEnvelope) -> FinalizedCommitment:
        await asyncio.sleep(1)
        return await super().submit(envelope)


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
                    "display": "Campaign",
                    "brief": "Write an original post.",
                    "pools": ["tao", "hyperliquid"],
                    "opens_at": "2026-08-01T00:00:00Z",
                    "closes_at": "2026-08-10T00:00:00Z",
                    "reward_pool_usd": "1000",
                }
            ),
        )

    async def close(self) -> None:
        return None


class WrongMinerFeed(Feed):
    async def fetch_campaigns(self) -> tuple[CampaignRecord, ...]:
        campaign = (await super().fetch_campaigns())[0]
        access = campaign.access.model_copy(update={"exclusive_miner_hotkey": "5" + "F" * 47})
        return (campaign.model_copy(update={"access": access}),)


def client(tmp_path: Path, *, submitter: Submitter | None = None, timeout: float = 5) -> TestClient:
    """Create an app using real durable miner state and a fake chain."""

    engine = MinerEngine(
        miner_hotkey=MINER,
        store=MinerStore(tmp_path / "miner.sqlite3"),
        submitter=submitter or Submitter(),
        policy=BatchPolicy(max_age_seconds=5),
    )
    service = MinerService(MinerSdk(engine), Feed(), timeout)  # type: ignore[arg-type]
    protocol = create_miner_app(
        miner_hotkey=MINER,
        provider=engine.batch_page,
        authorize_validator=lambda _hotkey: _authorized(),
    )
    return TestClient(
        create_app(lambda: service, protocol, INTERNAL_TOKEN),
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )


async def _authorized() -> bool:
    return True


def test_creator_api_requires_internal_bearer_token(tmp_path: Path) -> None:
    web = client(tmp_path)
    del web.headers["Authorization"]

    response = web.get("/api/campaigns")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_v3_validator_protocol_does_not_use_internal_bearer_token(tmp_path: Path) -> None:
    web = client(tmp_path)
    del web.headers["Authorization"]

    health = web.get("/health")
    assert health.status_code == 200
    assert health.json()["protocol_version"] == "3"
    # A GET receives method-not-allowed only when the signed POST route exists.
    assert web.get("/v3/batches").status_code == 405


async def test_current_validator_client_fetches_template_v3_batches(tmp_path: Path) -> None:
    validator = bt.Wallet(name="validator", hotkey="default", path=str(tmp_path / "wallets"))
    validator.create_new_coldkey(use_password=False, suppress=True)
    validator.create_new_hotkey(use_password=False, suppress=True)
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
    app = create_app(lambda: service, protocol, INTERNAL_TOKEN)
    validator_client = SignedMinerClient(
        validator,
        miner_hotkey=MINER,
        base_url="http://miner.test",
        transport=httpx.ASGITransport(app=app),
    )

    try:
        response = await validator_client.fetch_batches(BatchPageRequest(after_sequence=0))
    finally:
        await validator_client.close()

    assert response.protocol_version == 3
    assert response.miner_hotkey == MINER
    assert response.batches == []


def test_campaign_listing_uses_campaign_metadata_source(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/campaigns")

    assert response.status_code == 200
    assert response.json()[0]["access"]["campaign_id"] == "campaign"
    assert response.json()[0]["display"] == "Campaign"
    assert response.json()[0]["pools"] == ["tao", "hyperliquid"]
    assert "title" not in response.json()[0]
    assert "ecosystem_id" not in response.json()[0]


def test_creator_ui_explains_both_qualification_paths() -> None:
    script = Path("src/x_miner_template/static/app.js").read_text()

    assert 'statusRow(dl, "Qualified via", path)' in script
    assert '"Self-stake"' in script
    assert "required_self_stake_alpha" in script
    assert '"Lock target"' in script


def test_campaign_listing_hides_campaign_exclusive_to_another_miner(tmp_path: Path) -> None:
    engine = MinerEngine(
        miner_hotkey=MINER,
        store=MinerStore(tmp_path / "miner.sqlite3"),
        submitter=Submitter(),
        policy=BatchPolicy(max_age_seconds=5),
    )
    service = MinerService(MinerSdk(engine), WrongMinerFeed(), 5)  # type: ignore[arg-type]
    protocol = create_miner_app(
        miner_hotkey=MINER,
        provider=engine.batch_page,
        authorize_validator=lambda _hotkey: _authorized(),
    )
    web = TestClient(
        create_app(lambda: service, protocol, INTERNAL_TOKEN),
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )

    assert web.get("/api/campaigns").json() == []


def test_claim_is_finalized_and_submission_is_durably_acknowledged(tmp_path: Path) -> None:
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
    assert submission.json()["status"] == "tweet_received"
    pending = web.get("/api/submissions")
    assert pending.status_code == 200
    assert pending.json()[0] == {
        "submission_id": submission.json()["submission_id"],
        "campaign_id": "campaign",
        "tweet_id": "999",
        "claim_id": claim.json()["claim_id"],
        "status": "tweet_received",
        "created_ns": pending.json()[0]["created_ns"],
    }


def test_exclusive_submission_retry_reuses_durable_event(tmp_path: Path) -> None:
    web = client(tmp_path)
    body = {"campaign_id": "campaign", "tweet_id": "999", "claim_id": None}

    first = web.post("/api/submissions", json=body)
    retried = web.post("/api/submissions", json=body)

    assert first.status_code == 200
    assert retried.status_code == 200
    assert retried.json() == first.json()
    assert len(web.get("/api/submissions").json()) == 1


def test_finalized_claim_and_submission_survive_restart_for_validator_fetch(
    tmp_path: Path,
) -> None:
    """The durable database remains the source for validator pages after restart."""

    database = tmp_path / "miner.sqlite3"
    web = client(tmp_path)
    claim = web.post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    ).json()
    submission = web.post(
        "/api/submissions",
        json={
            "campaign_id": "campaign",
            "tweet_id": "999",
            "claim_id": claim["claim_id"],
        },
    ).json()

    restarted = MinerEngine(
        miner_hotkey=MINER,
        store=MinerStore(database),
        submitter=Submitter(),
        policy=BatchPolicy(max_age_seconds=5),
    )
    asyncio.run(restarted.commit_ready(force=True))
    page = asyncio.run(
        restarted.batch_page(
            BatchPageRequest(after_sequence=0, max_batches=50),
            "validator-hotkey",
        )
    )

    assert page.next_sequence == 2
    assert page.batches[0].position == CommitmentPosition(block=100, extrinsic_index=1)
    assert [event["claim_id"] for event in page.batches[0].batch["events"]] == [claim["claim_id"]]
    assert [event["submission_id"] for event in page.batches[1].batch["events"]] == [
        submission["submission_id"]
    ]


async def test_result_outage_retains_durable_submission(tmp_path: Path) -> None:
    engine = MinerEngine(
        miner_hotkey=MINER,
        store=MinerStore(tmp_path / "miner.sqlite3"),
        submitter=Submitter(),
        policy=BatchPolicy(max_age_seconds=5),
    )
    sdk = MinerSdk(engine)
    submission_id = sdk.submit_tweet(
        campaign_id="campaign",
        tweet_id="999",
        claim_id=None,
    )
    await engine.commit_ready(force=True)
    results_client = AsyncMock()
    results_client.submission.side_effect = RuntimeError("results unavailable")
    service = MinerService(
        sdk,
        Feed(),  # type: ignore[arg-type]
        5,
        results_client=results_client,  # type: ignore[arg-type]
    )

    submissions = await service.submissions()
    await service.sync_submission_results()

    assert submissions == [
        {
            "submission_id": submission_id,
            "campaign_id": "campaign",
            "tweet_id": "999",
            "claim_id": None,
            "status": "verification_pending",
            "created_ns": submissions[0]["created_ns"],
        }
    ]
    assert results_client.submission.await_count == 2


def test_claim_timeout_returns_waiting_status(tmp_path: Path) -> None:
    web = client(tmp_path, submitter=SlowSubmitter(), timeout=0.05)
    claim = web.post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    )
    assert claim.status_code == 200
    body = claim.json()
    assert body["claim_id"]
    assert body["status"] == "waiting_for_commitment"


def test_submission_rejects_campaign_mismatch(tmp_path: Path) -> None:
    web = client(tmp_path)
    claim = web.post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    ).json()

    response = web.post(
        "/api/submissions",
        json={
            "campaign_id": "other-campaign",
            "tweet_id": "999",
            "claim_id": claim["claim_id"],
        },
    )
    assert response.status_code == 400
    assert "does not match claim campaign" in response.json()["detail"]


def test_rejects_non_numeric_x_identifiers(tmp_path: Path) -> None:
    response = client(tmp_path).post(
        "/api/claims",
        json={"campaign_id": "campaign", "creator_x_id": "@handle", "draft": "draft"},
    )
    assert response.status_code == 422
