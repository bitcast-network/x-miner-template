"""Offline coverage for the replicated strict OpenRouter evaluator."""

import json

import httpx
import pytest

from x_miner_template.draft_precheck import (
    DraftPrecheckUnavailableError,
    OpenRouterDraftPrechecker,
    UnsupportedPromptVersionError,
)


def response(verdict: str, summary: str) -> str:
    return (
        "## Requirement-by-Requirement\n"
        "- Req 1: requirement — Met — evidence\n"
        f"## Verdict\n{verdict}\n"
        f"## Summary\n{summary}\n"
    )


def campaign(*, prompt_version: int = 2) -> dict[str, object]:
    return {
        "campaign_id": "campaign-1",
        "brief": "Explain why the product matters.",
        "prompt_version": prompt_version,
    }


async def test_all_three_checks_must_pass() -> None:
    requests: list[httpx.Request] = []
    replies = iter(
        [
            response("YES", "first approved"),
            response("NO", "second rejected"),
            response("YES", "third approved"),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evaluator = OpenRouterDraftPrechecker(api_key="secret", client=client)
    try:
        result = await evaluator.evaluate(campaign(), "A substantive product explanation")
    finally:
        await client.aclose()

    assert result.meets_brief is False
    assert [item.meets_brief for item in result.checks] == [True, False, True]
    assert result.failure_reason == "second rejected"
    assert len(requests) == 3
    payloads = [json.loads(request.content) for request in requests]
    assert all(payload["temperature"] == 0 for payload in payloads)
    assert all(payload["model"] == "qwen/qwen3-32b:nitro" for payload in payloads)
    assert "A substantive product explanation 1" in payloads[0]["messages"][0]["content"]
    assert "A substantive product explanation 3" in payloads[2]["messages"][0]["content"]


async def test_three_yes_verdicts_pass() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": response("YES", "approved")}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evaluator = OpenRouterDraftPrechecker(api_key="secret", client=client)
    try:
        result = await evaluator.evaluate(campaign(prompt_version=3), "Informed topic analysis")
    finally:
        await client.aclose()

    assert result.meets_brief is True
    assert len(result.checks) == 3


async def test_provider_failure_is_unavailable_not_content_rejection() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evaluator = OpenRouterDraftPrechecker(api_key="secret", attempts=1, client=client)
    try:
        with pytest.raises(DraftPrecheckUnavailableError, match="temporarily unavailable"):
            await evaluator.evaluate(campaign(), "Potentially valid draft")
    finally:
        await client.aclose()


async def test_missing_or_unknown_prompt_version_fails_before_provider_call() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evaluator = OpenRouterDraftPrechecker(api_key="secret", client=client)
    try:
        missing = campaign()
        missing.pop("prompt_version")
        with pytest.raises(UnsupportedPromptVersionError, match="version is missing"):
            await evaluator.evaluate(missing, "Draft")
        with pytest.raises(UnsupportedPromptVersionError, match="unsupported prompt version 6"):
            await evaluator.evaluate(campaign(prompt_version=6), "Draft")
    finally:
        await client.aclose()

    assert requests == []
