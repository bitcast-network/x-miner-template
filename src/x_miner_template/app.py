"""FastAPI boundary for the operator UI and validator protocol endpoint."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from bitcast_x.errors import BitcastXError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from x_miner_template.service import MinerService

STATIC_DIR = Path(__file__).parent / "static"


class ClaimRequest(BaseModel):
    """Creator input required to make a pre-publication claim."""

    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1, max_length=128)
    creator_x_id: str = Field(pattern=r"^[0-9]+$")
    draft: str = Field(min_length=1, max_length=20_000)


class SubmissionRequest(BaseModel):
    """Published tweet mapping submitted to the miner protocol."""

    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1, max_length=128)
    tweet_id: str = Field(pattern=r"^[0-9]+$")
    claim_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("claim_id", mode="before")
    @classmethod
    def empty_claim_is_none(cls, value: object) -> object:
        """Allow the UI to omit a claim for exclusive campaigns."""

        return None if value == "" else value


def create_app(service_provider: Callable[[], MinerService], protocol_app: FastAPI) -> FastAPI:
    """Create the combined human UI and signed validator HTTP service."""

    app = FastAPI(title="Bitcast X miner template", docs_url="/api/docs")

    def get_service() -> MinerService:
        return service_provider()

    Service = Annotated[MinerService, Depends(get_service)]

    @app.exception_handler(BitcastXError)
    async def protocol_error(_request: Request, error: BitcastXError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

    @app.get("/styles.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

    @app.get("/api/campaigns")
    async def campaigns(current: Service) -> list[dict[str, object]]:
        return await current.campaigns()

    @app.get("/api/qualification")
    async def qualification(current: Service) -> dict[str, object]:
        return await current.qualification()

    @app.post("/api/claims")
    async def create_claim(body: ClaimRequest, current: Service) -> dict[str, str]:
        return await current.create_claim(body.campaign_id, body.creator_x_id, body.draft)

    @app.get("/api/claims/{claim_id}")
    async def claim_status(claim_id: str, current: Service) -> dict[str, str]:
        result = current.claim_status(claim_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="claim not found")
        return result

    @app.post("/api/submissions")
    async def submit_tweet(body: SubmissionRequest, current: Service) -> dict[str, str]:
        return await current.submit_tweet(body.campaign_id, body.tweet_id, body.claim_id)

    @app.get("/api/submissions")
    async def submissions(current: Service) -> list[dict[str, object]]:
        return await current.submissions()

    @app.get("/api/submissions/{submission_id}")
    async def submission_status(submission_id: str, current: Service) -> dict[str, str]:
        result = current.submission_status(submission_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="submission not found")
        return result

    # Keep this mount last: validator-facing /health, /ready and /v2/batches
    # must coexist with the UI routes above.
    app.mount("/", protocol_app)
    return app
