"""Server-side client for the Bitcast X miner application API."""

from typing import Any

import httpx


class MinerNodeError(Exception):
    """An error response from the configured miner node."""

    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.retry_after = response.headers.get("retry-after")
        try:
            self.body: dict[str, Any] = response.json()
        except ValueError:
            self.body = {
                "error": {
                    "code": "upstream_error",
                    "message": "The miner node returned an invalid response.",
                    "retryable": response.status_code >= 500,
                }
            }
        super().__init__(str(self.body))


class MinerNodeClient:
    """Keep the node bearer credential on the product backend."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 30) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = await self._client.request(
            method,
            path,
            params=tuple(params or ()),
            json=json,
            headers=headers,
        )
        if response.is_error:
            raise MinerNodeError(response)
        return response.json()

    async def health(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("GET", "/health")
        return result

    async def qualification(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("GET", "/api/v1/qualification")
        return result

    async def ecosystems(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("GET", "/api/v1/ecosystems")
        return result

    async def campaigns(self, ecosystem_ids: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET",
            "/api/v1/campaigns",
            params=[("ecosystem_id", item) for item in ecosystem_ids],
        )
        return result

    async def leaderboard(self, ecosystem_ids: list[str], limit: int = 100) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET",
            "/api/v1/leaderboard",
            params=[
                *[("ecosystem_id", item) for item in ecosystem_ids],
                ("limit", str(limit)),
            ],
        )
        return result

    async def campaign(self, campaign_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("GET", f"/api/v1/campaigns/{campaign_id}")
        return result

    async def eligibility(self, campaign_id: str, creator_x_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET",
            f"/api/v1/campaigns/{campaign_id}/eligibility/{creator_x_id}",
        )
        return result

    async def campaign_tweets(self, campaign_id: str, ecosystem_ids: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET",
            f"/api/v1/campaigns/{campaign_id}/tweets",
            params=[("ecosystem_id", item) for item in ecosystem_ids],
        )
        return result
