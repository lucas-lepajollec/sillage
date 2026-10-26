"""Catalogue protocol/privacy tests. No cloud credentials or real network."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from sillage.app import create_app
from sillage.models import discover_models
from sillage.providers import ProviderConfig, ProviderError


def settings(kind="deepseek", **changes):
    return ProviderConfig(kind=kind, model="unused", api_key="TEST-ONLY-catalogue-key", **changes)


def invoke(handler, config=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await discover_models(config or settings(), client=client)
    return asyncio.run(run())


@pytest.mark.parametrize("kind,path", [
    ("openai", "/v1/models"), ("deepseek", "/v1/models"), ("openrouter", "/api/v1/models"),
    ("anthropic", "/v1/models"), ("gemini", "/v1beta/models"),
    ("ollama", "/api/tags"), ("custom", "/v1/models"),
])
def test_provider_catalogues_use_get_and_native_auth(kind, path):
    def handler(request):
        assert request.method == "GET" and request.url.path == path
        assert "TEST-ONLY-catalogue-key" not in str(request.url)
        if kind == "anthropic":
            assert request.headers["x-api-key"] == "TEST-ONLY-catalogue-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "authorization" not in request.headers
        elif kind == "gemini":
            assert request.headers["x-goog-api-key"] == "TEST-ONLY-catalogue-key"
        else:
            assert request.headers["authorization"] == "Bearer TEST-ONLY-catalogue-key"
        if kind == "gemini":
            data = {"models": [{"name": "models/text-model", "displayName": "Text model", "supportedGenerationMethods": ["generateContent"]}]}
        elif kind == "ollama":
            data = {"models": [{"name": "local-model:latest"}]}
        else:
            data = {"data": [{"id": "text-model", "name": "Text model"}]}
        return httpx.Response(200, json=data)
    config = settings(kind, **({"base_url": "http://127.0.0.1:1234/v1"} if kind == "custom" else {}))
    result = invoke(handler, config)
    assert len(result["models"]) == 1 and not result["truncated"]
    assert "TEST-ONLY-catalogue-key" not in str(result)


@pytest.mark.parametrize("kind", ["ollama", "custom"])
def test_local_catalogues_work_without_an_api_key(kind):
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"models": []} if kind == "ollama" else {"data": []})
    config = ProviderConfig(kind=kind, base_url="http://127.0.0.1:1234", model="unused")
    assert invoke(handler, config) == {"models": [], "truncated": False}


def test_gemini_paginates_and_excludes_non_generation_models():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"models": [
                {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/one", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "next-page"})
        assert request.url.params["pageToken"] == "next-page"
        return httpx.Response(200, json={"models": [{"name": "models/two", "supportedGenerationMethods": ["generateContent"]}]})
    assert [m["id"] for m in invoke(handler, settings("gemini"))["models"]] == ["one", "two"]
    assert len(calls) == 2


def test_anthropic_paginates_on_the_same_endpoint():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [{"id": "one", "display_name": "First"}], "has_more": True, "last_id": "one"})
        assert request.url.params["after_id"] == "one"
        return httpx.Response(200, json={"data": [{"id": "two"}], "has_more": False})
    result = invoke(handler, settings("anthropic"))
    assert [m["id"] for m in result["models"]] == ["one", "two"]
    assert result["models"][0]["name"] == "First"


def test_catalogue_is_deduplicated_filtered_and_does_not_echo_a_key():
    data = {"data": [
        {"id": "valid", "name": "Nice name", "description": "ignored private metadata"},
        {"id": "valid", "name": "Nice name"}, {"id": "bad id"},
        {"id": "TEST-ONLY-catalogue-key"},
        {"id": "valid-two", "name": "TEST-ONLY-catalogue-key"},
        {"id": "image", "architecture": {"output_modalities": ["image"]}},
    ]}
    result = invoke(lambda request: httpx.Response(200, json=data), settings("openrouter"))
    assert result["models"] == [{"id": "valid", "name": "Nice name"}, {"id": "valid-two", "name": "valid-two"}]
    assert "private metadata" not in str(result)


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
def test_catalogue_errors_never_follow_redirects_or_echo_private_details(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://another-service.invalid"}, text="TEST-ONLY-catalogue-key private response")
    with pytest.raises(ProviderError) as error:
        invoke(handler)
    assert len(calls) == 1 and "TEST-ONLY" not in str(error.value) and "private response" not in str(error.value)


@pytest.mark.parametrize("data", [{"models": []}, {"data": "invalid"}, []])
def test_invalid_catalogue_shapes_fail_safely(data):
    with pytest.raises(ProviderError, match="illisible"):
        invoke(lambda request: httpx.Response(200, json=data))


def test_catalogue_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr("sillage.models.MAX_CATALOG_BYTES", 10)
    with pytest.raises(ProviderError, match="volumineuse"):
        invoke(lambda request: httpx.Response(200, content=b"x" * 11))


def test_catalogue_size_and_pagination_are_bounded(monkeypatch):
    monkeypatch.setattr("sillage.models.MAX_MODELS", 1)
    result = invoke(lambda request: httpx.Response(200, json={"data": [{"id": "one"}, {"id": "two"}]}))
    assert result["truncated"] and len(result["models"]) == 1
    monkeypatch.setattr("sillage.models.MAX_PAGES", 1)
    result = invoke(lambda request: httpx.Response(200, json={"models": [], "nextPageToken": "more"}), settings("gemini"))
    assert result["truncated"]


def test_catalogue_without_a_required_key_never_contacts_a_service():
    config = ProviderConfig(kind="deepseek", model="unused")
    with pytest.raises(ProviderError, match="clé API"):
        invoke(lambda request: pytest.fail("No request without key"), config)


def test_saved_key_can_list_models_without_returning_or_resaving_it(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    secret = "TEST-ONLY-saved-catalogue-key"
    with TestClient(app) as client:
        provider = client.post("/api/providers", json={"kind": "deepseek", "model": "old-model", "api_key": secret}).json()
        mock = AsyncMock(return_value={"models": [{"id": "new-model", "name": "New model"}], "truncated": False})
        with patch("sillage.app.discover_models", mock):
            response = client.post("/api/providers/models", json={"id": provider["id"], "kind": "deepseek", "base_url": provider["base_url"]})
        assert response.status_code == 200 and secret not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert mock.call_args.args[0].api_key == secret
        assert app.state.store.provider(provider["id"])["model"] == "old-model"
        assert len(app.state.store.providers()) == 1


def test_saved_key_is_never_reused_for_a_changed_service_or_endpoint(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    with TestClient(app) as client:
        provider = client.post("/api/providers", json={"kind": "deepseek", "model": "old-model", "api_key": "TEST-ONLY-saved-key"}).json()
        for changes in ({"base_url": "https://other-service.invalid/v1"}, {"kind": "openai"}):
            with patch("sillage.app.discover_models", AsyncMock()) as mock:
                response = client.post("/api/providers/models", json={"id": provider["id"], "kind": "deepseek", "base_url": provider["base_url"], **changes})
            assert response.status_code == 400 and not mock.called
        changed = client.post("/api/providers", json=provider | {"base_url": "https://other-service.invalid/v1", "api_key": ""})
        assert changed.status_code == 200 and not changed.json()["has_key"]


def test_catalogue_invalid_requests_never_echo_secrets(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    secret = "TEST-ONLY-secret-input"
    with TestClient(app) as client:
        for body in ({"kind": "unknown", "api_key": secret},
                     {"kind": "deepseek", "api_key": secret, "base_url": "https://service.invalid?key=" + secret},
                     {"kind": "deepseek", "api_key": secret, "unknown": secret}):
            response = client.post("/api/providers/models", json=body)
            assert response.status_code in {400, 422} and secret not in response.text
