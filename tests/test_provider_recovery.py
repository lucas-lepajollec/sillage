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
    def text(value):
        return [text(part) for part in value] if isinstance(value, list) else value.replace("Hello", "Bonjour")
    return [{"id": cue["id"], "text": text(cue["text"])} for cue in batch]


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
    assert [len(request["segments"]) for request in requests] == [4, 2, 2]
    assert result["translations"] == {cue["id"]: cue["text"] for cue in translated(cues())}
    assert result["usage"]["total_tokens"] == 45
    assert {cue["id"] for cue in requests[1]["context"]} == {"cue-2", "cue-3"}


def test_failed_descendant_raises_without_losing_independently_valid_cues():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        batch = user["segments"]
        sizes.append(len(batch))
        items = translated(batch) if len(batch) == 2 and batch[0]["id"] == "cue-0" else []
        return httpx.Response(200, json=envelope(text=output(items)))
    with pytest.raises(ProviderError, match="JSON est lisible") as error:
        invoke(handler, settings=config(retries=1), segments=cues())
    assert set(error.value.translations) == {"cue-0", "cue-1"}
    assert sizes == [4, 2, 2, 1, 1]


def test_maximum_retry_setting_still_has_a_finite_recovery_budget():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        batch = user["segments"]
        sizes.append(len(batch))
        return httpx.Response(200, json=envelope(text=output(translated(batch) if len(batch) == 2 else [])))
    result = invoke(handler, settings=config(retries=5), segments=cues())
    assert sizes == [4, 4, 2, 2]
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
    assert sizes == [4, 2, 1]


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
            {"id": "cue-0", "text": "__SILLAGE_0001__Bonjour__SILLAGE_0000__"}]))), segments=cues(1))


def test_output_limit_has_a_specific_diagnostic_even_with_complete_json():
    data = envelope()
    data["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderError, match="limite de sortie"):
        invoke(lambda request: httpx.Response(200, json=data))


@pytest.mark.parametrize('kind', ['openai', 'deepseek', 'anthropic', 'gemini', 'ollama', 'openrouter', 'custom', 'groq', 'mistral', 'xai', 'lmstudio', 'vllm', 'llamacpp'])
def test_model_that_only_handles_single_cues_recovers_without_manual_restart(kind):
    sizes = []
    def handler(request):
        body = json.loads(request.content)
        content = (body['contents'][0]['parts'][0]['text'] if kind == 'gemini'
                   else body['input'] if kind == 'lmstudio'
                   else body['messages'][0]['content'] if kind == 'anthropic'
                   else body['messages'][1]['content'])
        batch = json.loads(content)['segments']
        sizes.append(len(batch))
        return httpx.Response(200, json=envelope(kind, output(translated(batch) if len(batch) == 1 else [])))
    settings = config(kind, retries=1)
    if kind == 'custom':
        settings['base_url'] = 'http://127.0.0.1:19999/v1'
    result = invoke(handler, settings=settings, segments=cues(8))
    assert len(sizes) == 15 and sizes[:4] == [8, 4, 2, 1]
    assert len(result['translations']) == 8
    assert result['batch_size'] == 1 and result['recovered'] is True
    assert result['requests'] == 15
    assert result['usage']['total_tokens'] == 225


def test_recovery_call_budget_is_shared_by_all_descendants():
    from sillage.providers import StructuredOutputError
    attempts = {}
    calls = []
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        calls.append(len(batch))
        key = batch[0]['id']
        attempts[key] = attempts.get(key, 0) + (len(batch) == 1)
        good = len(batch) == 1 and attempts[key] >= 6
        return httpx.Response(200, json=envelope(text=output(translated(batch) if good else [])))
    with pytest.raises(StructuredOutputError, match='limite de récupération') as error:
        invoke(handler, settings=config(retries=5), segments=cues(32))
    assert len(calls) == error.value.requests == 64
    assert error.value.usage['total_tokens'] == 64 * 15
    assert error.value.batch_size == 1


@pytest.mark.parametrize('wrapper', ['```json\n{}\n```', '```\n{}\n```', '\ufeff {} '])
def test_complete_json_fence_is_unwrapped_without_loosening_validation(wrapper):
    result = invoke(lambda request: httpx.Response(200, json=envelope(text=wrapper.format(output()))))
    assert result['translations'] == {'a': 'Bonjour.'}


def test_prose_outside_json_is_still_rejected():
    with pytest.raises(ProviderError, match='JSON invalide'):
        invoke(lambda request: httpx.Response(200, json=envelope(text='Here is the translation: ' + output())))


def test_planner_bounds_utf8_bytes_and_context_without_splitting_a_cue():
    from sillage.providers import take_batch, batch_byte_limit, initial_batch_size
    assert initial_batch_size(config('ollama', batch_size=100)) == 4
    assert initial_batch_size(config('deepseek', batch_size=100)) == 10
    assert initial_batch_size(config(batch_size=2)) == 2
    long = [{'id': str(i), 'text': '日本語' * 200} for i in range(10)]
    assert len(take_batch(long, 10, 1600)) == 1
    def handler(request):
        _, user = request_batch(request)
        assert len(json.dumps(user['context'], ensure_ascii=False).encode()) < batch_byte_limit(config()) + 100
        return httpx.Response(200, json=envelope())
    invoke(handler, context=long)


@pytest.mark.parametrize('kind', ['anthropic', 'gemini', 'ollama'])
def test_native_provider_interruption_never_splits(kind):
    sizes = []
    def handler(request):
        body = json.loads(request.content)
        content = (body['contents'][0]['parts'][0]['text'] if kind == 'gemini'
                   else body['input'] if kind == 'lmstudio'
                   else body['messages'][0]['content'] if kind == 'anthropic'
                   else body['messages'][1]['content'])
        sizes.append(len(json.loads(content)['segments']))
        data = envelope(kind)
        if kind == 'anthropic':
            data['stop_reason'] = 'pause_turn'
        elif kind == 'gemini':
            data['candidates'][0]['finishReason'] = 'OTHER'
        else:
            data['done_reason'] = 'unload'
        return httpx.Response(200, json=data)
    with pytest.raises(ProviderError, match='interrompu'):
        invoke(handler, settings=config(kind, retries=1), segments=cues())
    assert sizes == [4, 4]


def test_moved_boundary_tokens_are_recovered_before_worker_validation():
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        items = translated(batch)
        if len(batch) > 1:
            for item in items:
                item['text'] = 'Bonjour __SILLAGE_0000__Texte.__SILLAGE_0001__'
        return httpx.Response(200, json=envelope(text=output(items)))
    result = invoke(handler, settings=config(retries=1), segments=cues())
    assert result['batch_size'] == 1 and len(result['translations']) == 4
    assert all(text.startswith('__SILLAGE_0000__') for text in result['translations'].values())


@pytest.mark.parametrize('shape', ['map', 'bare-map', 'bare-list'])
def test_equivalent_explicit_id_json_shapes_do_not_require_paid_repairs(shape):
    items = translated(cues())
    mapping = {item['id']: item['text'] for item in items}
    payload = {'translations': mapping} if shape == 'map' else mapping if shape == 'bare-map' else items
    result = invoke(lambda request: httpx.Response(200, json=envelope(text=json.dumps(payload))), segments=cues())
    assert result['translations'] == mapping
    assert result['requests'] == 1


def test_only_invalid_cue_is_retried_without_lowering_the_whole_batch_to_one():
    calls = []
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        calls.append([cue['id'] for cue in batch])
        items = translated(batch)
        if len(calls) == 1:
            items[2]['text'] = ['Bonjour', 'fragment ajouté']
        return httpx.Response(200, json=envelope(text=output(items)))
    result = invoke(handler, settings=config(retries=1), segments=cues())
    assert calls == [['cue-0', 'cue-1', 'cue-2', 'cue-3'], ['cue-2']]
    assert result['batch_size'] == 4
    assert result['translations'] == {item['id']: item['text'] for item in translated(cues())}


def test_valid_descendants_remain_available_when_a_later_cue_exhausts_recovery():
    from sillage.providers import StructuredOutputError
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        good = [cue for cue in batch if cue['id'] != 'cue-2']
        return httpx.Response(200, json=envelope(text=output(translated(good))))
    with pytest.raises(StructuredOutputError) as error:
        invoke(handler, settings=config(retries=1), segments=cues())
    assert set(error.value.translations) == {'cue-0', 'cue-1', 'cue-3'}
    assert error.value.requests == 3


def test_duplicate_id_is_never_checkpointed_but_unique_siblings_are_retried_once():
    calls = []
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        calls.append([cue['id'] for cue in batch])
        items = translated(batch)
        if len(calls) == 1:
            items.append(items[0] | {'text': 'Conflicting duplicate'})
        return httpx.Response(200, json=envelope(text=output(items)))
    result = invoke(handler, settings=config(retries=1), segments=cues())
    assert calls == [['cue-0', 'cue-1', 'cue-2', 'cue-3'], ['cue-0']]
    assert result['translations']['cue-0'] == translated(cues(1))[0]['text']


def test_transient_json_error_repairs_same_size_before_splitting():
    sizes = []
    def handler(request):
        _, user = request_batch(request)
        batch = user['segments']
        sizes.append(len(batch))
        return httpx.Response(200, json=envelope(text='invalid JSON' if len(sizes) == 1 else output(translated(batch))))
    result = invoke(handler, settings=config(retries=2), segments=cues())
    assert sizes == [4, 4]
    assert not result['recovered']


def test_network_failure_after_valid_partial_response_carries_only_validated_cues():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ConnectError('TEST-ONLY-private-details', request=request)
        return httpx.Response(200, json=envelope(text=output(translated(cues()[:3]))))
    with pytest.raises(ProviderError, match='connexion') as error:
        invoke(handler, settings=config(retries=1), segments=cues())
    assert set(error.value.translations) == {'cue-0', 'cue-1', 'cue-2'}
    assert calls == 3
    assert 'TEST-ONLY-private-details' not in str(error.value)
