"""Optional pessimistic tweet-draft evaluation for the reference product."""

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from x_miner_template.draft_prompts import PROMPT_GENERATORS, generate_brief_evaluation_prompt

LOGGER = logging.getLogger(__name__)


class DraftEvaluation(BaseModel):
    """Outcome of one OpenRouter evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meets_brief: bool
    reasoning: str
    detailed_breakdown: str | None = None
    check: int


class DraftPrecheckResult(BaseModel):
    """Strict aggregate: every configured check must approve the draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meets_brief: bool
    checks: tuple[DraftEvaluation, ...]

    @property
    def failure_reason(self) -> str:
        failed = [item.reasoning for item in self.checks if not item.meets_brief]
        return " ".join(failed) or "The draft did not pass every precheck."


class DraftPrechecker(Protocol):
    """Template-owned semantic precheck boundary."""

    async def evaluate(
        self,
        campaign: Mapping[str, Any],
        draft: str,
    ) -> DraftPrecheckResult: ...


class DraftPrecheckUnavailableError(RuntimeError):
    """Raised when OpenRouter cannot provide all required verdicts."""


class UnsupportedPromptVersionError(RuntimeError):
    """Raised when the campaign requires evaluator logic absent from this template."""


class OpenRouterDraftPrechecker:
    """Run the validator-compatible prompts with stricter three-of-three semantics."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen/qwen3-32b:nitro",
        api_url: str = "https://openrouter.ai/api/v1/chat/completions",
        num_checks: int = 3,
        draft_max_length: int = 10_000,
        max_response_bytes: int = 2_000_000,
        timeout: float = 90.0,
        attempts: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenRouter API key cannot be empty")
        if num_checks <= 0 or draft_max_length <= 0 or max_response_bytes <= 0 or attempts <= 0:
            raise ValueError("draft precheck limits must be positive")
        self._api_url = api_url
        self._model = model
        self._num_checks = num_checks
        self._draft_max_length = draft_max_length
        self._max_response_bytes = max_response_bytes
        self._timeout = timeout
        self._attempts = attempts
        self._headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bitcast.ai",
            "X-Title": "Bitcast X Miner Template",
        }
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(trust_env=False)

    async def close(self) -> None:
        """Close an internally owned HTTP pool."""

        if self._owns_client:
            await self._client.aclose()

    async def evaluate(
        self,
        campaign: Mapping[str, Any],
        draft: str,
    ) -> DraftPrecheckResult:
        """Approve only when all three validator-compatible checks return YES."""

        campaign_id = str(campaign.get("campaign_id") or "unknown")
        brief = campaign.get("brief")
        prompt_version = campaign.get("prompt_version")
        if not isinstance(brief, str) or not brief.strip():
            raise ValueError("campaign does not contain a usable brief")
        if not isinstance(prompt_version, int) or isinstance(prompt_version, bool):
            raise UnsupportedPromptVersionError(
                "Campaign prompt version is missing. Update the template before claiming."
            )
        if prompt_version not in PROMPT_GENERATORS:
            raise UnsupportedPromptVersionError(
                f"Campaign requires unsupported prompt version {prompt_version}. "
                "Update the template before claiming."
            )

        prompt_brief = {
            "id": campaign_id,
            "brief": brief,
            "prompt_version": prompt_version,
        }
        text = draft[: self._draft_max_length]
        checks: list[DraftEvaluation] = []
        for check in range(1, self._num_checks + 1):
            prompt = generate_brief_evaluation_prompt(
                prompt_brief,
                f"{text} {check}",
                prompt_version,
            )
            try:
                response_text = await self._request(prompt)
            except httpx.HTTPError as exc:
                LOGGER.warning(
                    "draft precheck unavailable campaign=%s check=%s",
                    campaign_id,
                    check,
                )
                raise DraftPrecheckUnavailableError(
                    "Tweet precheck is temporarily unavailable. Please try again."
                ) from exc
            checks.append(parse_draft_evaluation(response_text, check=check))

        return DraftPrecheckResult(
            meets_brief=all(item.meets_brief for item in checks),
            checks=tuple(checks),
        )

    async def _request(self, prompt: str) -> str:
        last_error: httpx.HTTPError | None = None
        for attempt in range(self._attempts):
            try:
                async with self._client.stream(
                    "POST",
                    self._api_url,
                    headers=self._headers,
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "max_tokens": 4096,
                    },
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    declared = int(response.headers.get("content-length", 0))
                    if declared > self._max_response_bytes:
                        raise httpx.ProtocolError("OpenRouter response exceeds byte limit")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise httpx.ProtocolError("OpenRouter response exceeds byte limit")
                        chunks.append(chunk)
                payload = TypeAdapter(dict[str, Any]).validate_json(b"".join(chunks))
                content = payload["choices"][0]["message"].get("content")
                if not isinstance(content, str) or not content:
                    raise httpx.ProtocolError("OpenRouter response content is empty")
                return content
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = (
                    exc
                    if isinstance(exc, httpx.HTTPError)
                    else httpx.ProtocolError("malformed OpenRouter response")
                )
                if attempt + 1 < self._attempts:
                    await asyncio.sleep(2 ** (attempt + 1))
        assert last_error is not None
        raise last_error


def parse_draft_evaluation(text: str, *, check: int) -> DraftEvaluation:
    """Parse the same markdown verdict, breakdown, and summary used by validators."""

    verdict = re.search(r"## Verdict\s*\n\s*(YES|NO)", text, re.IGNORECASE)
    breakdown = re.search(
        r"## (?:Requirement-by-Requirement|Objective Requirements)[ \t]*\n"
        r"(.*?)(?:\n## Verdict|\n## |$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    summary = re.search(
        r"## Summary\s*\n\s*(.*?)(?:\n##|\n```|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return DraftEvaluation(
        meets_brief=bool(verdict and verdict.group(1).upper() == "YES"),
        reasoning=summary.group(1).strip() if summary else "Unable to parse response",
        detailed_breakdown=breakdown.group(1).strip() if breakdown else None,
        check=check,
    )
