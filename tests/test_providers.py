"""Protocol and output-contract tests; all traffic uses httpx.MockTransport."""

import asyncio
import json

import httpx
import pytest

from sillage.providers import ProviderConfig, ProviderError, test_connection, translate


def run(coro):
    return asyncio.run(coro)


def config(kind="openai", **changes):
    return {"kind": kind, "model": "user-selected-model", "api_key": "synthetic-test-value",
            "retries": 0, **changes}


def output(items=None):
    return json.dumps({"translations": items if items is not None else [{"id": "a", "text": "Bonjour."}]})


def envelope(kind="openai", text=None):
    text = text if text is not None else output()
    if kind == "anthropic":
        return {"content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}
    if kind == "gemini":
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15}}
    if kind == "lmstudio":
        return {"output": [{"type": "message", "content": text}], "stats": {"input_tokens": 10, "total_output_tokens": 5}}
    if kind == "ollama":
        return {"done": True, "done_reason": "stop", "message": {"content": text},
                "prompt_eval_count": 10, "eval_count": 5}
    return {"choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def invoke(handler, *, settings=None, segments=None, context=None, glossary=""):
    def transport(request):
        if request.url.path.endswith("/api/show"):
            return httpx.Response(200, json={"thinking": {"values": [False, True]}})
        if request.method == "GET" and request.url.path.endswith("/models"):
            selected = settings or config()
            if selected['kind'] == 'lmstudio':
                return httpx.Response(200, json={'models': [{'key': selected['model'], 'type': 'llm',
                    'capabilities': {'reasoning': {'allowed_options': ['off', 'on']}}}]})
            return httpx.Response(200, json={"data": [{"id": selected["model"], "reasoning": {"mandatory": False}}]})
        return handler(request)
    async def perform():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await translate(settings or config(), segments or [{"id": "a", "text": "Hello."}],
                                   context or [], glossary, client=client)
    return run(perform())


@pytest.mark.parametrize("kind,path", [
    ("openai", "/v1/chat/completions"), ("deepseek", "/v1/chat/completions"),
    ("openrouter", "/api/v1/chat/completions"), ("custom", "/v1/chat/completions"),
    ("anthropic", "/v1/messages"), ("gemini", "/v1beta/models/user-selected-model:generateContent"),
    ("ollama", "/api/chat"), ("groq", "/openai/v1/chat/completions"),
    ("mistral", "/v1/chat/completions"), ("xai", "/v1/chat/completions"),
    ("lmstudio", "/api/v1/chat"), ("vllm", "/v1/chat/completions"), ("llamacpp", "/v1/chat/completions"),
])
def test_protocols_use_real_documented_endpoints(kind, path):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope(kind))
    settings = config(kind)
    if kind == "custom":
        settings["base_url"] = "http://192.0.2.5:8000/v1"
    if kind == "ollama":
        settings["base_url"] = "http://192.0.2.7:11434"
        settings["api_key"] = ""
    result = invoke(handler, settings=settings)
    assert result["translations"] == {"a": "Bonjour."}
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert bool(result["warnings"]) is (kind in {"custom", "gemini", "groq", "mistral", "xai", "vllm", "llamacpp"})
    request = requests[0]
    assert request.method == "POST" and request.url.path == path
    assert not request.url.query
    body = json.loads(request.content)
    assert "temperature" not in body
    assert body.get("thinking") == ({"type": "disabled"} if kind in {"deepseek", "anthropic"} else None)
    if kind == "gemini":
        assert request.headers["x-goog-api-key"] == "synthetic-test-value"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
    elif kind == "anthropic":
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["x-api-key"] == "synthetic-test-value"
        assert "authorization" not in request.headers
        assert body["max_tokens"] >= 256
    elif kind == "lmstudio":
        assert body["reasoning"] == "off" and body["store"] is False
        assert request.headers["authorization"] == "Bearer synthetic-test-value"
    elif kind == "ollama":
        assert "authorization" not in request.headers
        assert body["format"] == "json" and body["stream"] is False
    else:
        assert request.headers["authorization"] == "Bearer synthetic-test-value"
        assert body["model"] == "user-selected-model"
        assert ("response_format" in body) is (kind != "custom")


def test_only_text_context_and_explicit_glossary_reach_provider():
    def handler(request):
        body = json.loads(request.content)
        user = json.loads(body["messages"][1]["content"])
        assert user["context"] == [{"id": "z", "text": "Prior text", "translated": "Avant"}]
        assert user["segments"] == [{"id": "a", "text": "Hello."}]
        assert user["glossary"] == "starship = astronef"
        assert user["target_language"] == "French"
        assert "media-path" not in request.content.decode()
        assert "synthetic-test-value" not in request.content.decode()
        return httpx.Response(200, json=envelope())
    invoke(handler, context=[{"id": "z", "text": "Prior text", "translated": "Avant",
                             "path": "media-path", "api_key": "synthetic-test-value"}],
           glossary="starship = astronef")


@pytest.mark.parametrize("invalid", [
    [], [{"id": "other", "text": "Bonjour"}], [{"id": "a", "text": ""}],
    [{"id": "a", "text": 4}], [{"id": "a", "text": "Bonjour", "note": "extra"}],
    [{"id": "a", "text": "x" * 1001}], [{"id": "a", "text": "Bon\njour"}],
    [{"id": "a", "text": "Bonjour"}, {"id": "a", "text": "duplicate"}],
])
def test_rejects_missing_stray_empty_oversized_and_duplicate_cues(invalid):
    with pytest.raises(ProviderError, match="JSON est lisible"):
        invoke(lambda req: httpx.Response(200, json=envelope(text=output(invalid))))


@pytest.mark.parametrize("text", [
    "not JSON", '```json\n{"translations":[]}\n```',
    '{"translations":[{"id":"a","id":"b","text":"Bonjour"}]}',
    '{"translations":[],"translations":[]}',
    '{"translations":[{"id":"a","text":"Bonjour"}],"extra":true}',
])
def test_rejects_malformed_or_duplicate_json_fields(text):
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, json=envelope(text=text)))


def test_exact_ids_are_preserved_even_if_provider_reorders_items():
    items = [{"id": "b", "text": "Au revoir."}, {"id": "a", "text": "Bonjour."}]
    result = invoke(lambda req: httpx.Response(200, json=envelope(text=output(items))),
                    segments=[{"id": "a", "text": "Hello."}, {"id": "b", "text": "Goodbye."}])
    assert result["translations"] == {"a": "Bonjour.", "b": "Au revoir."}


@pytest.mark.parametrize("text", [
    "__SILLAGE_0001__Salut.__SILLAGE_0000__", "__SILLAGE_0000__Salut.",
    "__SILLAGE_0000__<i>Salut</i>__SILLAGE_0001__",
    "__SILLAGE_0000__Salut.\\N__SILLAGE_0001__",
])
def test_formatting_placeholders_cannot_be_removed_reordered_or_replaced(text):
    source = "__SILLAGE_0000__Hello.__SILLAGE_0001__"
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": text}]))),
               segments=[{"id": "a", "text": source}])


def test_valid_masked_formatting_round_trip():
    source = "__SILLAGE_0000__Hello.__SILLAGE_0001__"
    translated = "__SILLAGE_0000__Bonjour.__SILLAGE_0001__"
    result = invoke(lambda req: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": translated}]))),
                    segments=[{"id": "a", "text": source}])
    assert result["translations"]["a"] == translated


def test_malformed_output_gets_bounded_repair_without_previous_body(monkeypatch):
    requests, waits = [], []
    async def sleep(delay):
        waits.append(delay)
    monkeypatch.setattr("sillage.providers.asyncio.sleep", sleep)
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json=envelope(text="untrusted bad output"))
        return httpx.Response(200, json=envelope())
    result = invoke(handler, settings=config(retries=1))
    assert len(requests) == 2 and waits == [0.5]
    assert "previous attempt failed" in requests[1]["messages"][0]["content"]
    assert "untrusted bad output" not in str(requests[1])
    assert result["usage"]["total_tokens"] == 30


@pytest.mark.parametrize("failure", ["timeout", "network", "rate-limit", "server"])
def test_transient_failures_retry_and_respect_backoff(failure, monkeypatch):
    attempts, waits = [], []
    async def sleep(delay):
        waits.append(delay)
    monkeypatch.setattr("sillage.providers.asyncio.sleep", sleep)
    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("potentially secret provider error", request=request)
            if failure == "network":
                raise httpx.ConnectError("potentially secret provider error", request=request)
            return httpx.Response(429 if failure == "rate-limit" else 503, headers={"Retry-After": "9999"})
        return httpx.Response(200, json=envelope())
    assert invoke(handler, settings=config(retries=1))["translations"] == {"a": "Bonjour."}
    assert len(attempts) == 2
    assert waits == ([30.0] if failure in {"rate-limit", "server"} else [0.5])


def test_retries_are_bounded_and_errors_do_not_echo_credentials_or_bodies(monkeypatch):
    attempts = []
    async def sleep(delay):
        pass
    monkeypatch.setattr("sillage.providers.asyncio.sleep", sleep)
    def handler(request):
        attempts.append(1)
        return httpx.Response(503, text="synthetic-test-value private subtitle text")
    with pytest.raises(ProviderError) as error:
        invoke(handler, settings=config(retries=2))
    assert len(attempts) == 3 and "HTTP 503" in str(error.value)
    assert "synthetic-test-value" not in str(error.value)
    assert "private subtitle" not in str(error.value)


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404])
def test_auth_invalid_settings_and_redirects_are_never_retried(status):
    attempts = []
    def handler(request):
        attempts.append(request.url)
        return httpx.Response(status, headers={"Location": "https://unintended.invalid"},
                              text="synthetic-test-value")
    with pytest.raises(ProviderError) as error:
        invoke(handler, settings=config(retries=5))
    assert len(attempts) == 1
    assert "synthetic-test-value" not in str(error.value)


@pytest.mark.parametrize("kind", ["openai", "anthropic", "gemini", "deepseek", "openrouter", "groq", "mistral", "xai"])
def test_cloud_key_is_required_before_network(kind):
    def handler(request):
        pytest.fail("Network must not run without a configured key")
    with pytest.raises(ProviderError, match="clé API"):
        invoke(handler, settings=config(kind, api_key=""))


@pytest.mark.parametrize("changes", [
    {"kind": "fake"}, {"retries": 6}, {"batch_size": 0}, {"concurrency": 9},
    {"timeout": 601}, {"temperature": float("nan")}, {"model": ""},
    {"base_url": "file:///etc/passwd"}, {"base_url": "http://name:secret@example.test/v1"},
    {"base_url": "http://example.test/v1?key=secret"}, {"base_url": "http://example.test:99999/v1"},
])
def test_configuration_rejects_invalid_limits_urls_and_production_fake(changes):
    with pytest.raises(ProviderError, match="Configuration du fournisseur invalide"):
        invoke(lambda request: pytest.fail("No network for invalid config"), settings=config(**changes))


def test_public_configuration_hides_api_key_and_model_has_no_catalogue():
    settings = ProviderConfig.model_validate(config(model="any-user-entered-future-model"))
    assert "synthetic-test-value" not in repr(settings)
    assert "api_key" not in settings.public_dict()
    assert settings.public_dict()["has_key"] is True
    assert settings.public_dict()["model"] == "any-user-entered-future-model"


def test_connection_executes_one_tiny_structured_model_call():
    attempts = []
    def handler(request):
        attempts.append(request)
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert user["segments"] == [{"id": "connection-check", "text": ["Hello.", "Goodbye."]}]
        return httpx.Response(200, json=envelope(text=output([{"id": "connection-check", "text": ["Bonjour.", "Au revoir."]}])) )
    async def perform():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await test_connection(config(retries=5), client=client)
    assert run(perform()) == "Connexion et réponse structurée du modèle validées."
    assert len(attempts) == 1


def test_incomplete_generation_is_rejected_even_when_json_looks_complete():
    data = envelope()
    data["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, json=data))


def test_language_plausibility_warns_without_claiming_certainty():
    original = "This is a sufficiently long source sentence with words that must be translated into French."
    result = invoke(lambda req: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": original}]))),
                    segments=[{"id": "a", "text": original}])
    assert "langue cible" in result["warnings"][0]


def test_anthropic_accepts_normal_null_stop_details():
    data = envelope("anthropic")
    data["stop_details"] = None
    assert invoke(lambda req: httpx.Response(200, json=data), settings=config("anthropic"))["translations"] == {"a": "Bonjour."}


@pytest.mark.parametrize("text", ["Bonjour.\u0085", "Bonjour.\u2028", "Bonjour.\ud800", "{nouveau format} Bonjour."])
def test_rejects_unicode_controls_and_new_raw_formatting(text):
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": text}]))))


def test_unknown_lowercase_placeholder_is_rejected():
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": "Bonjour __SILLAGE_bad__"}]))))


def test_oversized_http_response_is_rejected(monkeypatch):
    monkeypatch.setattr("sillage.providers.MAX_RESPONSE_BYTES", 100)
    with pytest.raises(ProviderError):
        invoke(lambda req: httpx.Response(200, content=b"x" * 101))


def test_duplicate_source_ids_fail_before_network():
    with pytest.raises(ProviderError, match="identifiants uniques"):
        invoke(lambda req: pytest.fail("Invalid source must not reach provider"),
               segments=[{"id": "a", "text": "Hello"}, {"id": "a", "text": "Bye"}])


def test_cancellation_propagates_without_retry():
    attempts = []
    def handler(request):
        attempts.append(1)
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        invoke(handler, settings=config(retries=5))
    assert attempts == [1]


def test_connection_does_not_report_success_from_models_listing():
    async def perform():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"data": [{"id": "some-model"}]}))) as client:
            await test_connection(config(), client=client)
    with pytest.raises(ProviderError):
        run(perform())


def test_adjacent_inline_placeholders_do_not_swallow_translatable_text():
    source = "__SILLAGE_0000__Hello__SILLAGE_0001__ world!__SILLAGE_0002__Goodbye."
    translated = "__SILLAGE_0000__Bonjour__SILLAGE_0001__ monde!__SILLAGE_0002__Au revoir."
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope(text=output([{"id": "a", "text": translated}]))))) as client:
            result = await translate(config(), [{"id": "a", "text": source}], [], client=client)
            assert result["translations"] == {"a": translated}
    run(check())
