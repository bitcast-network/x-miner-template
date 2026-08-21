"""Offline tests for the reference product and server-side node boundary."""

from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from x_miner_template.app import create_app
from x_miner_template.config import Settings
from x_miner_template.draft_precheck import (
    DraftEvaluation,
    DraftPrecheckResult,
    DraftPrecheckUnavailableError,
    UnsupportedPromptVersionError,
)
from x_miner_template.node import MinerNodeClient, MinerNodeError, MinerNodeTimeout

NODE_TOKEN = "n" * 64
DEMO_PASSWORD = "strong-demo-password"  # noqa: S105


class Node:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def health(self) -> dict[str, Any]:
        return {"status": "healthy", "protocol_version": "3"}

    async def qualification(self) -> dict[str, Any]:
        return {"eligible": True, "miner_hotkey": "miner", "checked_block": 100}

    async def ecosystems(self) -> dict[str, Any]:
        return {"items": [{"ecosystem_id": "tao", "name": "TAO", "enabled": True}]}

    async def campaigns(self, ecosystems: list[str]) -> dict[str, Any]:
        self.requests.append({"operation": "campaigns", "ecosystems": ecosystems})
        return {"items": [{"campaign_id": "campaign", "ecosystem_ids": ["tao"]}]}

    async def leaderboard(
        self,
        ecosystems: list[str],
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "operation": "leaderboard",
                "ecosystems": ecosystems,
                "limit": limit,
                "offset": offset,
            }
        )
        return {
            "ecosystem_ids": ecosystems,
            "accounts": [
                {
                    "rank": 1,
                    "username": "creator",
                    "score": 0.9,
                    "scores": {"tao": 0.9},
                }
            ],
        }

    async def campaign(self, campaign_id: str) -> dict[str, Any]:
        return {"campaign_id": campaign_id}

    async def eligibility(self, campaign_id: str, creator_x_id: str) -> dict[str, Any]:
        return {"campaign_id": campaign_id, "creator_x_id": creator_x_id, "eligible": True}

    async def campaign_tweets(self, campaign_id: str, ecosystems: list[str]) -> dict[str, Any]:
        return {"campaign_id": campaign_id, "ecosystems": ecosystems, "tweets": []}

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        record = {"method": method, "path": path, **kwargs}
        self.requests.append(record)
        if path == "/api/v1/claims" and method == "POST":
            return {"claim_id": "a" * 32, "usability": {"safe_to_post": True}}
        if path == "/api/v1/submissions" and method == "POST":
            return {"submission_id": "b" * 32, "status": "tweet_received"}
        return {"items": []}


class Prechecker:
    def __init__(
        self,
        *,
        meets_brief: bool = True,
        unavailable: bool = False,
        unsupported_version: bool = False,
    ) -> None:
        self.meets_brief = meets_brief
        self.unavailable = unavailable
        self.unsupported_version = unsupported_version
        self.requests: list[dict[str, Any]] = []

    async def evaluate(self, campaign: dict[str, Any], draft: str) -> DraftPrecheckResult:
        self.requests.append({"campaign": campaign, "draft": draft})
        if self.unavailable:
            raise DraftPrecheckUnavailableError("Tweet precheck is temporarily unavailable.")
        if self.unsupported_version:
            raise UnsupportedPromptVersionError(
                "Campaign requires unsupported prompt version 6. "
                "Update the template before claiming."
            )
        checks = tuple(
            DraftEvaluation(
                meets_brief=self.meets_brief,
                reasoning="approved" if self.meets_brief else f"check {check} rejected",
                check=check,
            )
            for check in range(1, 4)
        )
        return DraftPrecheckResult(meets_brief=self.meets_brief, checks=checks)


def settings(*, password: str | None = None) -> Settings:
    return Settings(
        node_url="http://node.test",
        node_token=SecretStr(NODE_TOKEN),
        web_username="demo",
        web_password=SecretStr(password) if password else None,
    )


def test_static_product_and_health_are_served() -> None:
    web = TestClient(create_app(settings(), Node))

    page = web.get("/")

    assert page.status_code == 200
    assert "Reference Miner" in page.text
    assert "reward recommendations" in page.text
    assert "Top ecosystem voices" in page.text
    assert "Campaign tweets" in page.text
    assert 'id="leaderboard-filters"' in page.text
    assert 'data-page="leaderboard"' in page.text
    assert 'id="leaderboard-page-status"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert web.get("/app.js").headers["cache-control"] == "no-cache"
    assert web.get("/styles.css").headers["cache-control"] == "no-cache"
    assert web.get("/health").json()["service"] == "x-miner-template"


def test_claims_are_automatically_recovered_when_a_campaign_is_opened() -> None:
    web = TestClient(create_app(settings(), Node))

    page = web.get("/")
    javascript = web.get("/app.js")

    assert "Existing claims are loaded automatically" in page.text
    select_campaign = javascript.text.split("async function selectCampaign", maxsplit=1)[1].split(
        "function renderSelectedCampaign", maxsplit=1
    )[0]
    assert "state.selectedCampaign.capabilities.requires_claim" in select_campaign
    assert "/^\\d+$/.test(creatorId())" in select_campaign
    assert "await recoverClaim();" in select_campaign


def test_optional_basic_auth_protects_product_but_not_health() -> None:
    web = TestClient(create_app(settings(password=DEMO_PASSWORD), Node))

    assert web.get("/").status_code == 401
    assert web.get("/api/campaigns").status_code == 401
    assert web.get("/health").status_code == 200
    assert web.get("/", auth=("demo", DEMO_PASSWORD)).status_code == 200


def test_status_and_repeated_ecosystem_filters_are_proxied() -> None:
    node = Node()
    web = TestClient(create_app(settings(), lambda: node))

    status = web.get("/api/status")
    campaigns = web.get("/api/campaigns?ecosystem_id=tao&ecosystem_id=ai_agents")

    assert status.json()["qualification"]["eligible"] is True
    assert campaigns.json()["items"][0]["campaign_id"] == "campaign"
    assert node.requests[0] == {
        "operation": "campaigns",
        "ecosystems": ["tao", "ai_agents"],
    }


def test_combined_leaderboard_filters_and_limit_are_proxied() -> None:
    node = Node()
    web = TestClient(create_app(settings(), lambda: node))

    response = web.get(
        "/api/leaderboard?ecosystem_id=tao&ecosystem_id=ai_agents&limit=25&offset=50"
    )

    assert response.status_code == 200
    assert response.json()["accounts"][0]["username"] == "creator"
    assert node.requests[0] == {
        "operation": "leaderboard",
        "ecosystems": ["tao", "ai_agents"],
        "limit": 25,
        "offset": 50,
    }


def test_claim_and_submission_forward_idempotency_without_exposing_node_token() -> None:
    node = Node()
    web = TestClient(create_app(settings(), lambda: node))
    claim_body = {
        "campaign_id": "campaign",
        "creator_x_id": "123",
        "draft": "Exact draft",
        "external_id": "creator-claim",
    }

    claim = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "claim-key-0001"},
        json=claim_body,
    )
    submission = web.post(
        "/api/submissions",
        headers={"Idempotency-Key": "submission-key-0001"},
        json={
            "campaign_id": "campaign",
            "tweet_id": "999",
            "claim_id": "a" * 32,
            "creator_x_id": "123",
        },
    )

    assert claim.json()["usability"]["safe_to_post"] is True
    assert submission.json()["status"] == "tweet_received"
    assert node.requests[0]["idempotency_key"] == "claim-key-0001"
    assert node.requests[1]["idempotency_key"] == "submission-key-0001"
    assert NODE_TOKEN not in str(node.requests)


def test_claim_timeout_recovers_exact_durable_claim() -> None:
    class TimedOutNode(Node):
        async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            self.requests.append({"method": method, "path": path, **kwargs})
            if method == "POST":
                raise MinerNodeTimeout(method, path)
            external_id = dict(kwargs["params"])["external_id"]
            return {
                "items": [
                    {
                        "claim_id": "c" * 32,
                        "external_id": external_id,
                        "usability": {"status": "pending", "safe_to_post": False},
                    }
                ]
            }

    node = TimedOutNode()
    web = TestClient(create_app(settings(), lambda: node))

    response = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "recover-timeout-claim"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    )

    assert response.status_code == 200
    assert response.headers["x-bitcast-claim-recovered"] == "true"
    assert response.json()["claim_id"] == "c" * 32
    assert node.requests[0]["json"]["external_id"] == "recover-timeout-claim"
    assert node.requests[0]["request_timeout"] == 120
    assert node.requests[1]["params"] == [
        ("campaign_id", "campaign"),
        ("creator_x_id", "123"),
        ("external_id", "recover-timeout-claim"),
    ]


def test_unreconciled_claim_timeout_is_a_retryable_gateway_timeout() -> None:
    class MissingClaimNode(Node):
        async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            if method == "POST":
                raise MinerNodeTimeout(method, path)
            return {"items": []}

    web = TestClient(create_app(settings(), MissingClaimNode))

    response = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "missing-timeout-claim"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    )

    assert response.status_code == 504
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"] == {
        "code": "miner_node_timeout",
        "message": (
            "The miner is still processing this request. Check the durable operation before "
            "retrying."
        ),
        "retryable": True,
    }


def test_precheck_status_is_disabled_and_claims_still_work_without_key() -> None:
    node = Node()
    web = TestClient(create_app(settings(), lambda: node))

    status = web.get("/api/draft-precheck/status")
    claim = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "claim-without-precheck"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Exact draft"},
    )

    assert status.json() == {
        "enabled": False,
        "mode": "disabled",
        "checks": 0,
        "provider": None,
    }
    assert claim.status_code == 200
    assert node.requests[0]["path"] == "/api/v1/claims"


def test_strict_precheck_failure_prevents_claim_forwarding() -> None:
    node = Node()
    prechecker = Prechecker(meets_brief=False)
    web = TestClient(create_app(settings(), lambda: node, draft_prechecker=prechecker))

    response = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "rejected-claim"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Weak draft"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "draft_precheck_failed"
    assert "all three" in response.json()["error"]["message"]
    assert prechecker.requests[0]["draft"] == "Weak draft"
    assert node.requests == []


def test_strict_precheck_pass_forwards_claim_and_unavailability_is_retryable() -> None:
    passing_node = Node()
    passing = TestClient(
        create_app(
            settings(),
            lambda: passing_node,
            draft_prechecker=Prechecker(meets_brief=True),
        )
    )
    passed = passing.post(
        "/api/claims",
        headers={"Idempotency-Key": "approved-claim"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Good draft"},
    )

    unavailable_node = Node()
    unavailable = TestClient(
        create_app(
            settings(),
            lambda: unavailable_node,
            draft_prechecker=Prechecker(unavailable=True),
        )
    )
    unavailable_response = unavailable.post(
        "/api/claims",
        headers={"Idempotency-Key": "unavailable-claim"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Good draft"},
    )

    assert passed.status_code == 200
    assert passing_node.requests[0]["path"] == "/api/v1/claims"
    assert unavailable_response.status_code == 503
    assert unavailable_response.headers["retry-after"] == "15"
    assert unavailable_response.json()["error"]["code"] == "draft_precheck_unavailable"
    assert unavailable_node.requests == []


def test_unsupported_campaign_prompt_version_blocks_claim() -> None:
    node = Node()
    web = TestClient(
        create_app(
            settings(),
            lambda: node,
            draft_prechecker=Prechecker(unsupported_version=True),
        )
    )

    response = web.post(
        "/api/claims",
        headers={"Idempotency-Key": "unsupported-version"},
        json={"campaign_id": "campaign", "creator_x_id": "123", "draft": "Draft"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "draft_precheck_version_unsupported"
    assert "Update the template" in response.json()["error"]["message"]
    assert node.requests == []


def test_recovery_filters_are_forwarded_without_changing_identifiers() -> None:
    node = Node()
    web = TestClient(create_app(settings(), lambda: node))

    web.get(
        "/api/claims?campaign_id=campaign&creator_x_id=123&external_id=claim-ref&ecosystem_id=tao"
    )
    web.get(
        "/api/submissions?campaign_id=campaign&creator_x_id=123&tweet_id=999"
        "&external_id=submission-ref&ecosystem_id=tao"
    )

    assert node.requests[0] == {
        "method": "GET",
        "path": "/api/v1/claims",
        "params": [
            ("ecosystem_id", "tao"),
            ("campaign_id", "campaign"),
            ("creator_x_id", "123"),
            ("external_id", "claim-ref"),
        ],
    }
    assert node.requests[1] == {
        "method": "GET",
        "path": "/api/v1/submissions",
        "params": [
            ("ecosystem_id", "tao"),
            ("campaign_id", "campaign"),
            ("creator_x_id", "123"),
            ("tweet_id", "999"),
            ("external_id", "submission-ref"),
        ],
    }


async def test_node_client_keeps_bearer_server_side_and_preserves_errors() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/claims"):
            return httpx.Response(
                409,
                json={"error": {"code": "idempotency_conflict", "message": "conflict"}},
                headers={"Retry-After": "5"},
            )
        return httpx.Response(200, json={"items": []})

    client = MinerNodeClient("http://node.test", NODE_TOKEN)
    await client._client.aclose()  # noqa: SLF001
    client._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://node.test",
        headers={"Authorization": f"Bearer {NODE_TOKEN}"},
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.campaigns(["tao", "ai_agents"])
        await client.leaderboard(["tao"], 25, 50)
        try:
            await client.request(
                "POST",
                "/api/v1/claims",
                json={"campaign_id": "campaign"},
                idempotency_key="claim-key-0001",
            )
        except MinerNodeError as error:
            assert error.status_code == 409
            assert error.retry_after == "5"
            assert error.body["error"]["code"] == "idempotency_conflict"
        else:
            raise AssertionError("expected MinerNodeError")
    finally:
        await client.close()

    assert requests[0].headers["Authorization"] == f"Bearer {NODE_TOKEN}"
    assert requests[0].url.params.multi_items() == [
        ("ecosystem_id", "tao"),
        ("ecosystem_id", "ai_agents"),
    ]
    assert requests[1].url.path == "/api/v1/leaderboard"
    assert requests[1].url.params.multi_items() == [
        ("ecosystem_id", "tao"),
        ("limit", "25"),
        ("offset", "50"),
    ]
    assert requests[2].headers["Idempotency-Key"] == "claim-key-0001"
