"""Regression cases for bounded structured translation and reasoning budgets."""

import asyncio
import json

import httpx
import pytest

from test_providers import config, envelope, invoke, output

from sillage.providers import ProviderError


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def sleep(delay):
        pass
    monkeypatch.setattr("sillage.providers.asyncio.sleep", sleep)


def cues(count=4):
    return [{"id": f"cue-{i}", "text": f"__SILLAGE_0000__Hello {i}.__SILLAGE_0001__"} for i in range(count)]


def translated(batch):
    return [{"id": cue["id"], "text": cue["text"].replace("Hello", "Bonjour")} for cue in batch]


def request_batch(request):
    body = json.loads(request.content)
    return body, json.loads(body["messages"][1]["content"])


def test_deepseek_default_thinking_cannot_starve_the_json_answer():
    def handler(request):
        body, user = request_batch(request)
        assert body["model"] == "deepseek-flash"
        assert body["max_tokens"] >= 2048
        if body.get("thinking") != {"type": "disabled"}:
            data = envelope(text="")
            data["choices"][0].update(finish_reason="length")
            data["choices"][0]["message"]["reasoning_content"] = "synthetic reasoning"
            return httpx.Response(200, json=data)
        return httpx.Response(200, json=envelope(text=output(translated(user["segments"]))))
    result = invoke(handler, settings=config("deepseek", model="deepseek-flash"), segments=cues())
    assert result["translations"] == {cue["id"]: cue["text"] for cue in translated(cues())}


def test_output_budget_includes_json_ids_and_stays_bounded():
    budgets = []
    def handler(request):
        body, user = request_batch(request)
        budgets.append(body["max_completion_tokens"])
        return httpx.Response(200, json=envelope(text=output(translated(user["segments"]))))
    short = [{"id": f"cue-{i}", "text": "Hello."} for i in range(40)]
    long = [{"id": f"cue-{i}-" + "x" * 115, "text": "Hello."} for i in range(40)]
    invoke(handler, segments=short)
    invoke(handler, segments=long)
    assert 2048 <= budgets[0] < budgets[1] <= 8192


@pytest.mark.parametrize("kind", ["openai", "deepseek", "anthropic", "gemini", "ollama"])
def test_truncation_increases_budget_before_retrying(kind):
    budgets = []
    def handler(request):
        body = json.loads(request.content)
        budget = (body["generationConfig"]["maxOutputTokens"] if kind == "gemini"
                  else body["options"]["num_predict"] if kind == "ollama"
                  else body.get("max_completion_tokens", body.get("max_tokens")))
        budgets.append(budget)
        data = envelope(kind)
        if len(budgets) == 1:
            if kind == "anthropic":
                data["stop_reason"] = "max_tokens"
            elif kind == "gemini":
                data["candidates"][0]["finishReason"] = "MAX_TOKENS"
            elif kind == "ollama":
                data["done_reason"] = "length"
            else:
                data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=data)
    result = invoke(handler, settings=config(kind, retries=1))
    assert result["translations"] == {"a": "Bonjour."}
    assert budgets == [2048, 4096]
    assert result["usage"]["total_tokens"] == 30


def test_invalid_batch_recovers_in_two_validated_halves_with_scene_context():
    requests = []
    def handler(request):
        body, user = request_batch(request)
        requests.append(user)
        batch = user["segments"]
        if len(batch) == 4:
            return httpx.Response(200, json=envelope(text=output([])))
        if batch[0]["id"] == "cue-2":
            assert any(cue.get("translated", "").startswith("__SILLAGE_0000__Bonjour")
                       for cue in user["context"])
        return httpx.Response(200, json=envelope(text=output(translated(batch))))
    result = invoke(handler, settings=config(retries=1), segments=cues())
    assert [len(request["segments"]) for request in requests] == [4, 4, 2, 2]
    assert result["translations"] == {cue["id"]: cue["text"] for cue in translated(cues())}
    assert result["usage"]["total_tokens"] == 60
    assert {cue["id"] for cue in requests[2]["context"]} == {"cue-2", "cue-3"}


def test_failed_second_half_never_returns_partial_translations_or_splits_again():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        batch = user["segments"]
        sizes.append(len(batch))
        items = translated(batch) if len(batch) == 2 and batch[0]["id"] == "cue-0" else []
        return httpx.Response(200, json=envelope(text=output(items)))
    with pytest.raises(ProviderError, match="invalide ou incomplète"):
        invoke(handler, settings=config(retries=1), segments=cues())
    assert sizes == [4, 4, 2, 2]


def test_maximum_retry_setting_still_has_a_finite_recovery_budget():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        batch = user["segments"]
        sizes.append(len(batch))
        return httpx.Response(200, json=envelope(text=output(translated(batch) if len(batch) == 2 else [])))
    result = invoke(handler, settings=config(retries=5), segments=cues())
    assert sizes == [4] * 6 + [2, 2]
    assert len(result["translations"]) == 4


def test_cancellation_during_recovery_is_not_swallowed():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        sizes.append(len(user["segments"]))
        if len(sizes) == 3:
            raise asyncio.CancelledError
        return httpx.Response(200, json=envelope(text=output([])))
    with pytest.raises(asyncio.CancelledError):
        invoke(handler, settings=config(retries=1), segments=cues())
    assert sizes == [4, 4, 2]


@pytest.mark.parametrize("failure", ["auth", "rate-limit", "network", "refusal", "aborted", "invalid"])
def test_recovery_never_splits_nonstructural_failures_or_when_retries_disabled(failure):
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        sizes.append(len(user["segments"]))
        if failure == "network":
            raise httpx.ConnectError("private provider details", request=request)
        if failure in {"auth", "rate-limit"}:
            return httpx.Response(401 if failure == "auth" else 429)
        data = envelope(text=output([]))
        if failure == "refusal":
            data["choices"][0]["message"]["refusal"] = "private provider details"
        elif failure == "aborted":
            data["choices"][0]["finish_reason"] = "aborted"
        return httpx.Response(200, json=data)
    with pytest.raises(ProviderError) as error:
        invoke(handler, settings=config(retries=0 if failure == "invalid" else 1), segments=cues())
    assert sizes == ([4] if failure in {"auth", "refusal", "invalid"} else [4, 4])
    assert "private provider details" not in str(error.value)


def test_formatting_failure_has_a_specific_sanitized_diagnostic():
    with pytest.raises(ProviderError, match="balises protégées"):
        invoke(lambda request: httpx.Response(200, json=envelope(text=output([
            {"id": "cue-0", "text": "Bonjour sans balises"}]))), segments=cues(1))


def test_output_limit_has_a_specific_diagnostic_even_with_complete_json():
    data = envelope()
    data["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderError, match="limite de sortie"):
        invoke(lambda request: httpx.Response(200, json=data))
