"""Creator-facing reference product backed by a separate miner node."""

import base64
from collections.abc import Awaitable, Callable
from hmac import compare_digest
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from x_miner_template.config import Settings
from x_miner_template.draft_precheck import (
    DraftPrechecker,
    DraftPrecheckUnavailableError,
    UnsupportedPromptVersionError,
)
from x_miner_template.node import MinerNodeClient, MinerNodeError, MinerNodeTimeout

STATIC_DIR = Path(__file__).parent / "static"
EcosystemFilter = Annotated[list[str] | None, Query()]


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1, max_length=128)
    creator_x_id: str = Field(pattern=r"^[0-9]+$")
    draft: str = Field(min_length=1, max_length=20_000)
    external_id: str | None = Field(default=None, min_length=1, max_length=256)


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1, max_length=128)
    tweet_id: str = Field(pattern=r"^[0-9]+$")
    claim_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    creator_x_id: str = Field(pattern=r"^[0-9]+$")
    external_id: str | None = Field(default=None, min_length=1, max_length=256)


def _basic_credentials(header: str) -> tuple[str, str] | None:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    return (username, password) if separator else None


def create_app(
    settings: Settings,
    client_provider: Callable[[], MinerNodeClient],
    *,
    draft_prechecker: DraftPrechecker | None = None,
) -> FastAPI:
    """Build the reference product while keeping node credentials server-side."""

    app = FastAPI(title="Bitcast X reference miner product", docs_url=None, redoc_url=None)

    def get_client() -> MinerNodeClient:
        return client_provider()

    Client = Annotated[MinerNodeClient, Depends(get_client)]
    password = settings.web_password.get_secret_value() if settings.web_password else None

    @app.middleware("http")
    async def authenticate_demo(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if password is None or request.url.path == "/health":
            return await call_next(request)
        credentials = _basic_credentials(request.headers.get("authorization", ""))
        authorized = bool(
            credentials
            and compare_digest(credentials[0], settings.web_username)
            and compare_digest(credentials[1], password)
        )
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"detail": "Reference product authentication required."},
                headers={"WWW-Authenticate": 'Basic realm="Bitcast X reference miner"'},
            )
        return await call_next(request)

    @app.exception_handler(MinerNodeError)
    async def miner_node_error(_request: Request, error: MinerNodeError) -> JSONResponse:
        headers = {"Retry-After": error.retry_after} if error.retry_after else None
        return JSONResponse(status_code=error.status_code, content=error.body, headers=headers)

    @app.exception_handler(MinerNodeTimeout)
    async def miner_node_timeout(_request: Request, _error: MinerNodeTimeout) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content={
                "error": {
                    "code": "miner_node_timeout",
                    "message": (
                        "The miner is still processing this request. Check the durable "
                        "operation before retrying."
                    ),
                    "retryable": True,
                }
            },
            headers={"Retry-After": "5"},
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "app.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/styles.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "styles.css",
            media_type="text/css",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy", "service": "x-miner-template"}

    @app.get("/api/status")
    async def status(client: Client) -> dict[str, Any]:
        node_health, qualification = await client.health(), await client.qualification()
        return {"node": node_health, "qualification": qualification}

    @app.get("/api/ecosystems")
    async def ecosystems(client: Client) -> dict[str, Any]:
        return await client.ecosystems()

    @app.get("/api/campaigns")
    async def campaigns(
        client: Client,
        ecosystem_id: EcosystemFilter = None,
    ) -> dict[str, Any]:
        return await client.campaigns(ecosystem_id or [])

    @app.get("/api/leaderboard")
    async def leaderboard(
        client: Client,
        ecosystem_id: EcosystemFilter = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return await client.leaderboard(ecosystem_id or [], limit, offset)

    @app.get("/api/campaigns/{campaign_id}")
    async def campaign(campaign_id: str, client: Client) -> dict[str, Any]:
        return await client.campaign(campaign_id)

    @app.get("/api/campaigns/{campaign_id}/eligibility/{creator_x_id}")
    async def eligibility(
        campaign_id: str,
        creator_x_id: str,
        client: Client,
    ) -> dict[str, Any]:
        return await client.eligibility(campaign_id, creator_x_id)

    @app.get("/api/campaigns/{campaign_id}/tweets")
    async def campaign_tweets(
        campaign_id: str,
        client: Client,
        ecosystem_id: EcosystemFilter = None,
    ) -> dict[str, Any]:
        return await client.campaign_tweets(campaign_id, ecosystem_id or [])

    @app.get("/api/draft-precheck/status")
    async def draft_precheck_status() -> dict[str, Any]:
        enabled = draft_prechecker is not None
        return {
            "enabled": enabled,
            "mode": "all_three_must_pass" if enabled else "disabled",
            "checks": 3 if enabled else 0,
            "provider": "openrouter" if enabled else None,
        }

    @app.post("/api/claims")
    async def create_claim(
        body: ClaimRequest,
        client: Client,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        if draft_prechecker is not None:
            campaign = await client.campaign(body.campaign_id)
            try:
                precheck = await draft_prechecker.evaluate(campaign, body.draft)
            except UnsupportedPromptVersionError as error:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": {
                            "code": "draft_precheck_version_unsupported",
                            "message": str(error),
                        }
                    },
                )
            except (DraftPrecheckUnavailableError, ValueError) as error:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "code": "draft_precheck_unavailable",
                            "message": str(error),
                        }
                    },
                    headers={"Retry-After": "15"},
                )
            if not precheck.meets_brief:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "draft_precheck_failed",
                            "message": (
                                "Tweet draft did not pass all three prechecks. "
                                f"{precheck.failure_reason}"
                            ),
                        },
                        "precheck": precheck.model_dump(mode="json"),
                    },
                )
        external_id = body.external_id or idempotency_key
        claim_payload = body.model_dump(mode="json", exclude_none=True)
        claim_payload["external_id"] = external_id
        try:
            result: dict[str, Any] = await client.request(
                "POST",
                "/api/v1/claims",
                json=claim_payload,
                idempotency_key=idempotency_key,
                request_timeout=settings.claim_timeout_seconds,
            )
        except MinerNodeTimeout as timeout_error:
            recovered: dict[str, Any] = await client.request(
                "GET",
                "/api/v1/claims",
                params=[
                    ("campaign_id", body.campaign_id),
                    ("creator_x_id", body.creator_x_id),
                    ("external_id", external_id),
                ],
            )
            exact_claim = next(
                (
                    item
                    for item in recovered.get("items", [])
                    if item.get("external_id") == external_id
                ),
                None,
            )
            if exact_claim is None:
                raise timeout_error
            return JSONResponse(
                content=exact_claim,
                headers={"X-Bitcast-Claim-Recovered": "true"},
            )
        return JSONResponse(content=result)

    @app.get("/api/claims")
    async def claims(
        client: Client,
        campaign_id: str | None = None,
        creator_x_id: str | None = None,
        external_id: str | None = None,
        ecosystem_id: EcosystemFilter = None,
    ) -> dict[str, Any]:
        params = [("ecosystem_id", item) for item in ecosystem_id or []]
        if campaign_id:
            params.append(("campaign_id", campaign_id))
        if creator_x_id:
            params.append(("creator_x_id", creator_x_id))
        if external_id:
            params.append(("external_id", external_id))
        result: dict[str, Any] = await client.request("GET", "/api/v1/claims", params=params)
        return result

    @app.get("/api/claims/{claim_id}")
    async def claim(claim_id: str, client: Client) -> dict[str, Any]:
        result: dict[str, Any] = await client.request("GET", f"/api/v1/claims/{claim_id}")
        return result

    @app.post("/api/submissions")
    async def create_submission(
        body: SubmissionRequest,
        client: Client,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result: dict[str, Any] = await client.request(
            "POST",
            "/api/v1/submissions",
            json=body.model_dump(mode="json", exclude_none=False),
            idempotency_key=idempotency_key,
        )
        return result

    @app.get("/api/submissions")
    async def submissions(
        client: Client,
        campaign_id: str | None = None,
        creator_x_id: str | None = None,
        tweet_id: str | None = None,
        external_id: str | None = None,
        ecosystem_id: EcosystemFilter = None,
    ) -> dict[str, Any]:
        params = [("ecosystem_id", item) for item in ecosystem_id or []]
        if campaign_id:
            params.append(("campaign_id", campaign_id))
        if creator_x_id:
            params.append(("creator_x_id", creator_x_id))
        if tweet_id:
            params.append(("tweet_id", tweet_id))
        if external_id:
            params.append(("external_id", external_id))
        result: dict[str, Any] = await client.request("GET", "/api/v1/submissions", params=params)
        return result

    @app.get("/api/submissions/{submission_id}")
    async def submission(submission_id: str, client: Client) -> dict[str, Any]:
        result: dict[str, Any] = await client.request("GET", f"/api/v1/submissions/{submission_id}")
        return result

    return app
