"""On-demand model discovery. Only normalized IDs/names leave this adapter."""
from __future__ import annotations

import asyncio
import re
import unicodedata

import httpx

from .providers import ProviderConfig, ProviderError, _json
from .reasoning import LOCAL_KINDS, policy_for

MAX_CATALOG_BYTES = 4_000_000
MAX_MODELS = 2000
MAX_PAGES = 5
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}\Z")


def _endpoint(config: ProviderConfig) -> tuple[str, dict, dict]:
    headers = {"Accept": "application/json"}
    params: dict[str, str | int] = {}
    if config.kind not in LOCAL_KINDS and not config.api_key:
        raise ProviderError("Ajoutez votre clé API pour charger les modèles de ce fournisseur.")
    if config.kind == "gemini":
        headers["x-goog-api-key"] = config.api_key
        url = config.base_url + "/models"
        params["pageSize"] = 1000
    elif config.kind == "anthropic":
        headers.update({"x-api-key": config.api_key, "anthropic-version": "2023-06-01"})
        url = config.base_url.removesuffix("/messages") + "/models"
        params["limit"] = 100
    elif config.kind == "ollama":
        base = config.base_url.removesuffix("/api/chat").removesuffix("/api")
        url = base + "/api/tags"
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
    else:
        url = config.base_url.removesuffix("/chat/completions") + "/models"
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
    return url, headers, params


def _model(item: dict, config: ProviderConfig) -> dict[str, str] | None:
    if config.kind == "gemini":
        if "generateContent" not in item.get("supportedGenerationMethods", []):
            return None
        identifier = item.get("name", "")
        identifier = identifier.removeprefix("models/") if isinstance(identifier, str) else ""
        name = item.get("displayName")
    elif config.kind == "ollama":
        identifier, name = item.get("name", item.get("model")), item.get("name")
    elif config.kind == "lmstudio":
        if item.get("type") != "llm":
            return None
        identifier, name = item.get("key"), item.get("display_name")
    else:
        identifier, name = item.get("id"), item.get("display_name", item.get("name"))
        modalities = item.get("output_modalities")
        if config.kind == "openrouter":
            architecture = item.get("architecture")
            modalities = architecture.get("output_modalities") if isinstance(architecture, dict) else None
        if isinstance(modalities, list) and "text" not in modalities:
            return None
    if (not isinstance(identifier, str) or not MODEL_ID.fullmatch(identifier) or "://" in identifier
            or (config.api_key and config.api_key in identifier)):
        return None
    if (not isinstance(name, str) or not name.strip() or len(name) > 200
            or any(unicodedata.category(ch).startswith("C") for ch in name)
            or (config.api_key and config.api_key in name)):
        name = identifier
    result = {"id": identifier, "name": name.strip()}
    policy = policy_for(config.kind, identifier, item)
    if policy.status == "mandatory":
        result["reasoning"] = "mandatory"
        result["warning"] = policy.warnings[0]
    return result


async def discover_models(config: ProviderConfig, *, client: httpx.AsyncClient | None = None) -> dict:
    """Read the selected service's catalogue without making a generation call."""
    url, headers, params = _endpoint(config)
    owned = client is None
    http = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
    models: dict[str, dict[str, str]] = {}
    cursors: set[str] = set()
    truncated = False
    try:
        async with asyncio.timeout(30):
            for page in range(MAX_PAGES):
                async with http.stream("GET", url, headers=headers, params=params,
                                       timeout=min(config.timeout, 15), follow_redirects=False) as response:
                    if response.status_code in {401, 403}:
                        raise ProviderError("Clé API refusée pour la liste des modèles. Vérifiez la clé et ses autorisations.")
                    if response.status_code in {404, 405, 501}:
                        raise ProviderError("Ce service ne propose pas de liste de modèles à cette adresse. Vérifiez l’URL ou saisissez un modèle manuellement.")
                    if response.status_code == 429 or response.status_code >= 500:
                        raise ProviderError("La liste des modèles est temporairement indisponible. Réessayez dans un instant.")
                    if not 200 <= response.status_code < 300:
                        raise ProviderError("Impossible de charger les modèles. Vérifiez le fournisseur et l’URL de son API.")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_CATALOG_BYTES:
                            raise ProviderError("La liste du service est trop volumineuse. Saisissez le modèle manuellement.")
                        chunks.append(chunk)
                    data = _json(b"".join(chunks))
                if not isinstance(data, dict):
                    raise ValueError
                items = data.get("models" if config.kind in {"gemini", "ollama", "lmstudio"} else "data")
                if not isinstance(items, list):
                    raise ValueError
                for item in items:
                    model = _model(item, config) if isinstance(item, dict) else None
                    if model:
                        if len(models) >= MAX_MODELS and model["id"] not in models:
                            truncated = True
                            break
                        models[model["id"]] = model
                cursor = None
                if config.kind == "gemini":
                    cursor = data.get("nextPageToken")
                    cursor_key = "pageToken"
                elif config.kind == "anthropic" and data.get("has_more"):
                    cursor = data.get("last_id")
                    cursor_key = "after_id"
                    if not cursor:
                        raise ValueError
                if not cursor or truncated:
                    break
                if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in cursors:
                    raise ValueError
                cursors.add(cursor)
                params[cursor_key] = cursor
                if page == MAX_PAGES - 1:
                    truncated = True
        return {"models": sorted(models.values(), key=lambda item: item["id"].casefold()), "truncated": truncated}
    except ProviderError:
        raise
    except (httpx.TimeoutException, TimeoutError):
        raise ProviderError("Le service met trop de temps à envoyer ses modèles. Réessayez ou saisissez un modèle manuellement.") from None
    except httpx.RequestError:
        raise ProviderError("Le service est injoignable. Vérifiez l’URL et l’accès réseau depuis Sillage.") from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProviderError("Le service a renvoyé une liste de modèles illisible. Vous pouvez saisir le modèle manuellement.") from None
    finally:
        if owned:
            await http.aclose()
