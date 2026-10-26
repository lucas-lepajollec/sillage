# Translation providers

Sillage calls the provider selected for a job. In **Paramètres → Ajouter un fournisseur**, choose the service, enter its API key (or the server URL for a local connection), then select a model from its live catalogue. Leaving the key field loads the catalogue; **Charger les modèles** also loads or refreshes it. A single returned model is selected automatically. Search appears for larger catalogues. Profile names are optional; Sillage generates one from the service and model. You can keep several independent cloud/local profiles and choose one before translating.

Languages default to English → French. Languages, glossary, API URL overrides and request limits remain in **Réglages avancés**. Existing profiles keep their saved configuration. Ollama and LM Studio use their native APIs; **Serveur compatible OpenAI** supports local or remote servers exposing Chat Completions and, when available, `/models`. Local services can omit the API key.

Catalogue discovery makes only model-list GET requests, never a generation request. It does not save an unfinished profile, discover workstation credentials or install local models. If the catalogue is empty/unavailable, use **Saisir un modèle manuellement**. Model IDs remain free-form; no bundled list limits the models you can configure. The catalogue does not prove your account's generation permissions or JSON/translation compatibility. After saving, **Tester la connexion** makes a small, real translation request and can incur the provider's usual charge.

| Kind | Default API base URL | Protocol |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | Chat Completions, JSON output |
| Anthropic | `https://api.anthropic.com/v1` | Messages, text blocks, native API-key header |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | `models/{model}:generateContent` |
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI compatible Chat Completions |
| OpenRouter | `https://openrouter.ai/api/v1` | OpenAI compatible Chat Completions |
| Ollama | `http://localhost:11434` | Native `/api/chat`, non-streaming JSON |
| Groq | `https://api.groq.com/openai/v1` | OpenAI compatible Chat Completions |
| Mistral | `https://api.mistral.ai/v1` | Chat Completions, text/chunk responses |
| xAI / Grok | `https://api.x.ai/v1` | OpenAI compatible Chat Completions |
| LM Studio | `http://localhost:1234/api/v1` | Native `/chat` and `/models` |
| vLLM | `http://localhost:8000/v1` | Chat Completions with template controls |
| llama.cpp | `http://localhost:8080/v1` | Chat Completions with template controls |
| Custom | Required | OpenAI compatible `/chat/completions` |

The base URL includes the API version prefix shown above. Do not put a key, URL username/password, query string or fragment in it. API keys travel in request headers. Custom, Ollama, LM Studio, vLLM and llama.cpp permit a blank key for servers without authentication. HTTP endpoints on the LAN are supported deliberately; HTTPS remains available for secured endpoints. Requests do not follow redirects and the default HTTP client ignores environment proxies, avoiding an unintended destination for subtitle text or credentials.

Discovery uses `/models` for compatible services, native `/api/tags` for Ollama, and the documented models endpoints for Gemini/Anthropic. It follows their pagination on the same endpoint with at most five pages, 2,000 normalized IDs/names and 4 MB per response, under a 30-second overall timeout. Text-generation capabilities are filtered where the service reports them. Some compatible catalogues also include models unsuitable for translation; use the connection test. A partial list is marked explicitly and manual entry remains available.

Saved keys are reused only on the server for the same provider kind and exact normalized endpoint. Changing that binding requires entering a key again; saving a changed binding without one clears its old key. Failed lookups expose fixed messages, not provider response bodies. Draft keys stay in form memory until it closes; they are not stored in browser storage or catalogue caches.

For Ollama on another machine, use that machine's reachable LAN address, such as `http://192.0.2.7:11434` (documentation address; replace it). The Ollama service must listen on its LAN interface and the host firewall must permit access from Sillage. Inside a container, `localhost` identifies that container. Sillage does not install a model or reconfigure the Ollama host. See the [Ollama network configuration guide](https://docs.ollama.com/faq).

Leave temperature empty to use the model's default; some reasoning models reject sampling parameters. Provider/model feature support varies: **Test connection** is the compatibility check. Unknown model IDs, unsupported parameters and authentication failures produce actionable, sanitized errors instead of silently switching models.

## Reasoning preference

Sillage requests **no reasoning whenever the API/model supports it**. A model with mandatory reasoning remains usable, with the lowest effort exposed by its documented API/capabilities and an explicit warning about time/tokens. No model ID is silently changed. Hiding a thinking trace is not treated as disabling reasoning.

| Service | Preferred control and exceptions |
| --- | --- |
| OpenAI | `reasoning_effort: "none"` on supporting models; omit it on known non-reasoning families. Original GPT-5 and o-series reasoning models use their minimum supported effort; GPT-6.1/GPT-6 Astra use low, with warnings. Known Responses-only Pro families use `/responses`, `reasoning.effort` and `store: false`. |
| Anthropic | `thinking.type: "disabled"`; Sonnet 5.5 uses `between_tools` with no tools, disabling upfront thinking. Known always-thinking families use adaptive/low with a warning. Unsupported custom temperature is omitted with a warning. |
| Gemini | 2.5 Flash/Flash-Lite use `thinkingBudget: 0`; 2.5 Pro uses its minimum 128 budget with a warning. 3.x thinking models use minimal or low, **still with a mandatory-reasoning warning**. Older non-thinking families omit the setting. |
| DeepSeek | `thinking: {"type": "disabled"}` on hybrid models, including Flash; fixed R1 reasoning models warn. The configured model name is preserved. |
| OpenRouter | `reasoning.enabled: false` and `provider.require_parameters: true`, so a route cannot silently ignore the control. Mandatory capability metadata enables the lowest listed effort and warns. Known upstream mandatory families also warn when metadata is absent. |
| Groq | Qwen uses `reasoning_effort: "none"`; GPT-OSS requires low and warns. Non-thinking Llama/Gemma/Mixtral families omit it. |
| Mistral | Adjustable modern families use `reasoning_effort: "none"`; fixed Magistral/GLM reasoning families stay active and warn. Text chunks are extracted separately from thinking chunks. |
| xAI / Grok | Grok 4.3 uses `reasoning_effort: "none"`; known mandatory families such as 4.5–4.7 use low and warn. |
| Ollama | Native `think: false` when `/api/show` permits it. If thinking only allows levels, use the lowest supported value and warn. Unknown capabilities still request false with an uncertainty warning. |
| LM Studio | Native `reasoning: "off"` when allowed; otherwise use the lowest allowed setting and warn. When no setting is exposed, omit the unsupported control and warn that disabling cannot be confirmed. Requests disable storage and integrations. |
| vLLM / llama.cpp | `reasoning_effort: "none"` plus documented chat-template flags. Known thinking-only models remain usable with warnings. Server templates still control actual behavior, so disabling cannot be certified from a model name. |
| Compatible server | Request `reasoning_effort: "none"`; known thinking-only families warn. Unknown server capabilities produce an uncertainty warning. |

Controls are based on the API snapshot checked on **2026-10-26**, not a universal model catalogue. New models, aliases, proxies and server templates may differ. An unsupported request returns a sanitized error: Sillage does **not** remove an off control and retry blindly after HTTP 400. Select the dedicated service when available, check its endpoint/model and run **Tester la connexion**. This genuine translation test includes reasoning warnings in its result.

Before translating with Ollama, LM Studio or OpenRouter, Sillage may make one non-generating capability read: `/api/show` (POST, model only) or `/models` (GET). Each read has a 10-second overall limit, 4 MB response limit, no redirects and at most 2,000 inspected catalogue entries. Successful capability choices may be cached on the backend for 60 seconds, at most 64 entries, isolated by service, endpoint, model and a key hash. No thought contents or raw metadata are retained. Catalogue browsing itself still makes only model-list GETs.

Provider-reported thinking blocks or positive reasoning-token counters generate a warning if they contradict the requested off mode. Thought contents are neither stored in checkpoints nor exposed in diagnostics. Absence of a trace is not proof that no internal reasoning occurred. Warnings survive retries, structural failures and resumes, even when all translations were already checkpointed. Successful output with warnings is exported normally and marked **Vérification requise**; validation of IDs, formatting and timing is unchanged.

A large input context does not prevent reasoning from exhausting an output budget before the JSON answer finishes. DeepSeek's controls follow the same translation preference as TraDoc; see [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) and [JSON output](https://api-docs.deepseek.com/guides/json_mode/).

## Batch contract and reliability

The worker sends only cue IDs and masked text, source/target languages, glossary and bounded scene context. Files, media paths and audio are never included. Exact IDs, duplicate-free JSON, non-empty text and protected formatting remain mandatory. A complete Markdown JSON fence is unwrapped; surrounding prose, extra fields, duplicate/missing IDs and changed tokens remain invalid.

The configured batch size (1–100) is a **ceiling**. Starting size is at most **4** cues for local/compatible endpoints and **10** for named cloud services, further limited to about 1,600/4,000 serialized UTF-8 bytes. A single oversized cue is kept whole and validated, never cut into invented cues. Scene context is independently bounded to the same byte ceilings (up to 20 cues), keeping complete cues; the explicit glossary is not silently truncated. These are conservative defaults, not detected model context limits. A compatible cloud endpoint uses the conservative compatible-service default too.

When structural JSON/formatting validation fails, enabled recovery progressively halves the batch down to one cue. Truncation first gets one retry with more output room, then smaller batches if necessary. A parent batch reaches SQLite only after **all** descendants validate. Each original batch and all its retries/descendants share at most `min(64, (retries + 1) × (2 × cue_count − 1))` HTTP attempts. Retries 0 disables splitting/retries. A persistently invalid single cue or an exhausted budget stops safely with stable cue IDs; earlier validated batches remain resumable.

The worker uses recovered smaller sizes on the next wave and remembers them in job metadata across resumes/restarts and the latest 20 jobs of the **same profile and exact configuration fingerprint**. Different models/profiles/settings do not inherit that ceiling. This conservative ceiling does not automatically increase; changing the saved profile settings resets its empirical history for new jobs. Existing job fingerprint checks still prevent mixing different provider settings in a resumed translation. The job footer shows the current adaptive ceiling. Settings retain concurrency 1–8, timeout 1–600 seconds and retries 0–5.

Network/timeouts/HTTP 408/409/425/429/5xx retry with backoff; numeric Retry-After is capped at 30 seconds. These failures, auth/client errors, explicit refusals and provider interruptions never trigger structural splitting. Cancellation propagates. Repair prompts never echo a previous raw provider response. The output budget includes IDs/JSON/UTF-8 with a 2,048-token floor and 8,192 ceiling; reported output truncation is never accepted.

Use **Reprendre** after updating to keep validated checkpoints. Operational learning adds only job metadata; no database migration or profile edit is required. If timing validation fails before translation, changing/retrying the model will not repair the source. Zero-duration events are kept byte-for-byte in the decoded document, excluded from translation and marked for review; genuinely reversed timestamps remain refused with event/line/time diagnostics. Sillage never guesses or rewrites source timings to hide corruption.

Usage reports numeric token counts returned by the provider, including parseable failed translation attempts. Missing usage is recorded as zero, so counts do not prove billing totals. There is no price catalogue or cost estimate. Language plausibility checks flag substantial unchanged text and obvious English output when French was requested. They cannot certify language, meaning, terminology or subtitle reading quality; review the preview.

Keys stay in backend configuration and are omitted from public provider responses. These adapters do not log HTTP bodies, headers, keys or provider error bodies. Endpoint failures are mapped to fixed messages. Do not enable HTTP wire/debug logging in an installation handling private text.

## API references and implementation choice

Checked 2026-10-26 against [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Anthropic authentication](https://platform.claude.com/docs/en/manage-claude/authentication), [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation), [Gemini generateContent](https://ai.google.dev/api/generate-content), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion), and [Ollama chat](https://docs.ollama.com/api/chat). OpenAI's docs recommend Responses for new OpenAI-specific applications; Sillage uses Chat Completions to share a narrow text-only protocol with compatible servers.

The implementation uses small `httpx` adapters and local validation. [LiteLLM](https://docs.litellm.ai/docs/) offers a unified SDK, many providers, routing/fallback and a gateway. For this local application's thirteen explicit provider kinds, direct adapters keep endpoint behavior, secret handling and retry budgets visible, without adding a routing/model registry layer. Reconsider an SDK if provider breadth grows substantially. Neither choice replaces subtitle-specific validation.

Tests use an injected `httpx.AsyncClient` and `MockTransport`; no paid service, real credential or LAN model was contacted for automated validation. Live account permissions, model capability and LAN reachability remain installation checks.

Reasoning and added-service references: [OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning), [GPT-5.4 Pro](https://developers.openai.com/api/docs/models/gpt-5.4-pro), [Anthropic thinking compatibility](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting), [Gemini thinking controls](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [OpenRouter reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens), [OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection), [Ollama thinking](https://docs.ollama.com/capabilities/thinking), [Groq reasoning](https://console.groq.com/docs/reasoning), [Mistral reasoning](https://docs.mistral.ai/studio/conversations/reasoning), [xAI reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning), [LM Studio chat](https://lmstudio.ai/docs/developer/rest/chat), [LM Studio model capabilities](https://lmstudio.ai/docs/developer/rest/list), [vLLM reasoning outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/) and [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
