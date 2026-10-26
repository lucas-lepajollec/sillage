"""Provider-specific preference for no reasoning, with explicit mandatory/unknown warnings.

Only controls and fixed diagnostics are retained. No thought text is recorded.
Capability probes never generate text and are bounded separately from generation retries.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

LOCAL_KINDS = frozenset({"ollama", "lmstudio", "vllm", "llamacpp", "custom"})
MANDATORY = ("Ce modèle impose le raisonnement : la traduction reste active. Sillage réduit son effort "
             "quand le service le permet. Le délai et les tokens consommés peuvent augmenter.")
UNVERIFIED = ("La désactivation du raisonnement ne peut pas être confirmée pour ce modèle. "
              "Sillage utilise le contrôle disponible ; vérifiez les réglages du serveur si nécessaire.")
OBSERVED = ("Le service a signalé du raisonnement malgré la désactivation demandée. La traduction "
            "reste active ; le délai et les tokens consommés peuvent augmenter.")
_CACHE: dict[tuple, tuple[float, 'ReasoningPolicy']] = {}


@dataclass
class ReasoningPolicy:
    controls: dict = field(default_factory=dict)
    status: str = "disabled"
    omit_temperature: bool = False

    @property
    def warnings(self) -> list[str]:
        return [MANDATORY] if self.status == "mandatory" else [UNVERIFIED] if self.status == "unverified" else []


def _lowest(values: Any, default: str = "low") -> str:
    if isinstance(values, list):
        for effort in ("minimal", "low", "medium", "high", "xhigh", "max", "on"):
            if effort in values:
                return effort
    return default


def policy_for(kind: str, model: str, metadata: dict | None = None) -> ReasoningPolicy:
    """Known protocol controls plus authoritative capabilities when exposed by the service.

    Model families select wire parameters, never rewrite the selected model ID. Unknown
    compatible servers receive a preferred-off request, with no universal guarantee.
    """
    name = model.lower().removeprefix("models/").rsplit("/", 1)[-1]
    meta = metadata if isinstance(metadata, dict) else {}
    def mandatory(controls, **kw):
        return ReasoningPolicy(controls, "mandatory", **kw)
    def unknown(controls):
        return ReasoningPolicy(controls, "unverified")
    fixed_reasoning = ("gpt-oss" in name or "deepseek-r1" in name or "qwq" in name)
    if kind == "deepseek":
        if "deepseek-r1" in name:
            return mandatory({})
        return ReasoningPolicy({"thinking": {"type": "disabled"}})
    if kind == "openai":
        if name.startswith("gpt-5-chat"):
            return ReasoningPolicy({}, "non_reasoning")
        if name.startswith(("gpt-5.2-pro", "gpt-5.4-pro")):
            return mandatory({"reasoning_effort": "medium"}, omit_temperature=True)
        if re.match(r"(?:o[134](?:-|$)|gpt-5(?:-|$))", name) and not re.match(r"gpt-5[.][1-9]", name):
            effort = "high" if "pro" in name else "minimal" if name.startswith("gpt-5") else "low"
            # Legacy o1-mini/o1-preview do not expose adjustable reasoning effort.
            controls = {} if name in {"o1-mini", "o1-preview"} else {"reasoning_effort": effort}
            return mandatory(controls, omit_temperature=True)
        if name.startswith(("gpt-6.1", "gpt-6-astra")):
            return mandatory({"reasoning_effort": "low"}, omit_temperature=True)
        if name.startswith(("gpt-4", "gpt-3.5", "chatgpt-4")):
            return ReasoningPolicy({}, "non_reasoning")
        return ReasoningPolicy({"reasoning_effort": "none"})
    if kind == "anthropic":
        if any(family in name for family in ("fable", "mythos", "opus-5-5", "opus-5.5")):
            return mandatory({"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
                             omit_temperature=True)
        if "sonnet-5-5" in name or "sonnet-5.5" in name:
            return ReasoningPolicy({"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}},
                                   omit_temperature=True)
        newer = bool(re.search(r"(?:opus|sonnet|haiku)[-.](?:[5-9]|4[-.][7-9])", name))
        controls = {"thinking": {"type": "disabled"}}
        if newer:
            controls["output_config"] = {"effort": "low"}
        return ReasoningPolicy(controls, omit_temperature=newer)
    if kind == "gemini":
        if name.startswith("gemini-2.5"):
            return (mandatory({"thinkingBudget": 128}) if "pro" in name
                    else ReasoningPolicy({"thinkingBudget": 0}))
        if re.match(r"gemini-[3-9]", name):
            effort = "low" if "pro" in name or name.startswith(("gemini-3.7", "gemini-3.8")) else "minimal"
            return mandatory({"thinkingLevel": effort})
        if name.startswith(("gemini-1.", "gemini-2.0")):
            return ReasoningPolicy({}, "non_reasoning")
        return unknown({"thinkingBudget": 0})
    if kind == "openrouter":
        reasoning = meta.get("reasoning")
        if isinstance(reasoning, dict) and reasoning.get("mandatory") is True:
            controls = {"enabled": True}
            if "supported_efforts" in reasoning and (reasoning.get("supported_efforts") is None or reasoning.get("supported_efforts")):
                controls["effort"] = _lowest(reasoning.get("supported_efforts"))
            return mandatory({"reasoning": controls, "provider": {"require_parameters": True}})
        if not isinstance(reasoning, dict) and "/" in model:
            vendor = model.split("/", 1)[0].lower()
            upstream = {"google": "gemini", "anthropic": "anthropic", "openai": "openai", "x-ai": "xai"}.get(vendor)
            known = policy_for(upstream, name) if upstream else None
            if known and known.status == "mandatory":
                return mandatory({"reasoning": {"enabled": True}, "provider": {"require_parameters": True}})
        supported = meta.get("supported_parameters")
        if isinstance(supported, list) and not any(p in supported for p in ("reasoning", "reasoning_effort")):
            return ReasoningPolicy({}, "non_reasoning")
        # Dynamic routers do not have one model's capabilities. Request off without
        # silently allowing a backend to ignore the routing parameter.
        controls = {"reasoning": {"enabled": False}, "provider": {"require_parameters": True}}
        return ReasoningPolicy(controls) if isinstance(reasoning, dict) else unknown(controls)
    if kind == "groq":
        if "gpt-oss" in name:
            return mandatory({"reasoning_effort": "low"})
        if name.startswith("qwen"):
            return ReasoningPolicy({"reasoning_effort": "none"})
        if name.startswith(("llama", "gemma", "mixtral")):
            return ReasoningPolicy({}, "non_reasoning")
        return unknown({"reasoning_effort": "none"})
    if kind == "mistral":
        if "magistral" in name:
            return mandatory({})
        if name.startswith("zai-glm"):
            return mandatory({"reasoning_effort": "low"})
        if name.startswith(("mistral-small-latest", "mistral-medium-3-5", "mistral-large-4")):
            return ReasoningPolicy({"reasoning_effort": "none"})
        if name.startswith(("mistral", "open-mistral", "open-mixtral", "ministral", "codestral", "pixtral")):
            return ReasoningPolicy({}, "non_reasoning")
        return unknown({"reasoning_effort": "none"})
    if kind == "xai":
        if name.startswith(("grok-4.5", "grok-4.6", "grok-4.7", "grok-3-mini")) or name in {"grok-4", "grok-4-0709"}:
            return mandatory({"reasoning_effort": "low"} if name != "grok-4" and name != "grok-4-0709" else {})
        if name.startswith("grok-4.3"):
            return ReasoningPolicy({"reasoning_effort": "none"})
        if "non-reasoning" in name or name.startswith("grok-3"):
            return ReasoningPolicy({}, "non_reasoning")
        return unknown({"reasoning_effort": "none"})
    if kind == "ollama":
        thinking = meta.get("thinking")
        values = thinking.get("values") if isinstance(thinking, dict) else None
        if isinstance(values, list) and any(value is False for value in values):
            return ReasoningPolicy({"think": False})
        if isinstance(values, list) and values:
            return mandatory({"think": _lowest(values, "on") if any(isinstance(v, str) for v in values) else True})
        if "gpt-oss" in name:
            return mandatory({"think": "low"})
        return unknown({"think": False})
    if kind == "lmstudio":
        capabilities = meta.get("capabilities")
        reasoning = capabilities.get("reasoning") if isinstance(capabilities, dict) else None
        values = reasoning.get("allowed_options") if isinstance(reasoning, dict) else None
        if isinstance(values, list) and "off" in values:
            return ReasoningPolicy({"reasoning": "off"})
        if isinstance(values, list) and values:
            return mandatory({"reasoning": _lowest(values, "on")})
        # Absence of an exposed setting is not proof of a non-thinking model.
        # Sending an unsupported setting is an error in the native API.
        return unknown({} if isinstance(capabilities, dict) else {"reasoning": "off"})
    if kind in {"vllm", "llamacpp", "custom"}:
        if fixed_reasoning:
            return mandatory({"reasoning_effort": "low"} if "gpt-oss" in name else {})
        controls: dict = {"reasoning_effort": "none"}
        if kind == "vllm":
            controls["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
        elif kind == "llamacpp":
            controls["chat_template_kwargs"] = {"enable_thinking": False}
        return unknown(controls)
    return unknown({})


async def resolve_policy(config: Any, client: httpx.AsyncClient, *, cache: bool = False) -> ReasoningPolicy:
    """At most one metadata read, <=4 MB and <=10s; failure never removes an off control."""
    if config.kind not in {"ollama", "lmstudio", "openrouter"}:
        return policy_for(config.kind, config.model)
    key = (config.kind, config.base_url, config.model, hashlib.sha256(config.api_key.encode()).digest())
    now = time.monotonic()
    if cache and key in _CACHE and _CACHE[key][0] > now:
        return _CACHE[key][1]
    meta = None
    headers = {"Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = "Bearer " + config.api_key
    base = config.base_url
    if config.kind == "ollama":
        base = base.removesuffix("/api/chat").removesuffix("/api")
        method, url, payload = "POST", base + "/api/show", {"model": config.model}
    else:
        method, url, payload = "GET", base.removesuffix("/chat/completions") + "/models", None
    try:
        async with asyncio.timeout(min(config.timeout, 10)):
            async with client.stream(method, url, headers=headers, json=payload,
                                     timeout=min(config.timeout, 10), follow_redirects=False) as response:
                if response.status_code == 200:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4_000_000:
                            raise ValueError
                        chunks.append(chunk)
                    data = json.loads(b"".join(chunks))
                    if isinstance(data, dict):
                        if config.kind == "ollama":
                            meta = data
                        else:
                            items = data.get("models" if config.kind == "lmstudio" else "data", [])
                            if isinstance(items, list):
                                meta = next((item for item in items[:2000] if isinstance(item, dict)
                                             and item.get("key" if config.kind == "lmstudio" else "id") == config.model), None)
    except (httpx.RequestError, TimeoutError, ValueError, TypeError):
        pass
    policy = policy_for(config.kind, config.model, meta)
    if cache and meta is not None:
        if len(_CACHE) >= 64:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (now + 60, policy)
    return policy


def reported_reasoning(data: dict, kind: str) -> bool:
    """Inspect presence/counts only, never retain or expose thought contents."""
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    if positive(usage.get("reasoning_tokens")) or positive(details.get("reasoning_tokens")):
        return True
    if kind == "anthropic":
        return any(p.get("type") in {"thinking", "redacted_thinking"} for p in data.get("content", []) if isinstance(p, dict))
    if kind == "gemini":
        return positive((data.get("usageMetadata") or {}).get("thoughtsTokenCount")) or any(
            p.get("thought") is True for c in data.get("candidates", [])
            for p in (c.get("content") or {}).get("parts", []) if isinstance(p, dict))
    if kind == "ollama":
        return bool((data.get("message") or {}).get("thinking"))
    if kind == "lmstudio":
        return positive((data.get("stats") or {}).get("reasoning_output_tokens")) or any(
            p.get("type") == "reasoning" for p in data.get("output", []) if isinstance(p, dict))
    if kind == "openai" and any(p.get("type") == "reasoning" for p in data.get("output", []) if isinstance(p, dict)):
        return True
    for choice in data.get("choices", []):
        message = choice.get("message") or {}
        if any(message.get(k) for k in ("reasoning", "reasoning_content", "reasoning_details")):
            return True
        if isinstance(message.get("content"), list) and any(
                p.get("type") in {"thinking", "reasoning"} for p in message["content"] if isinstance(p, dict)):
            return True
    return False
