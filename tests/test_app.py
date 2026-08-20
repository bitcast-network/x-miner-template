"""Offline tests for the reference product and server-side node boundary."""

from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from x_miner_template.app import create_app
from x_miner_template.config import Settings
from x_miner_template.node import MinerNodeClient, MinerNodeError

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
    assert web.get("/health").json()["service"] == "x-miner-template"


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
    assert requests[1].headers["Idempotency-Key"] == "claim-key-0001"
