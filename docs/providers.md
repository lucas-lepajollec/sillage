# Translation providers

Sillage calls the provider selected for a job. In **Paramètres → Ajouter un fournisseur**, choose the service, enter its API key (or the server URL for a local connection), then select a model from its live catalogue. Leaving the key field loads the catalogue; **Charger les modèles** also loads or refreshes it. A single returned model is selected automatically. Search appears for larger catalogues. Profile names are optional; Sillage generates one from the service and model. You can keep several independent cloud/local profiles and choose one before translating.

Languages default to English → French. Languages, glossary, API URL overrides and request limits remain in **Réglages avancés**. Existing profiles keep their saved configuration. Ollama uses its native API; **Serveur compatible OpenAI** supports local or remote servers exposing Chat Completions and, when available, `/models`. Local services can omit the API key.

Catalogue discovery makes only model-list GET requests, never a generation request. It does not save an unfinished profile, discover workstation credentials or install local models. If the catalogue is empty/unavailable, use **Saisir un modèle manuellement**. Model IDs remain free-form; no bundled list limits the models you can configure. The catalogue does not prove your account's generation permissions or JSON/translation compatibility. After saving, **Tester la connexion** makes a small, real translation request and can incur the provider's usual charge.

| Kind | Default API base URL | Protocol |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | Chat Completions, JSON output |
| Anthropic | `https://api.anthropic.com/v1` | Messages, text blocks, native API-key header |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | `models/{model}:generateContent` |
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI compatible Chat Completions |
| OpenRouter | `https://openrouter.ai/api/v1` | OpenAI compatible Chat Completions |
| Ollama | `http://localhost:11434` | Native `/api/chat`, non-streaming JSON |
| Custom | Required | OpenAI compatible `/chat/completions` |

The base URL includes the API version prefix shown above. Do not put a key, URL username/password, query string or fragment in it. API keys travel in request headers. Custom and Ollama permit a blank key for servers without authentication. HTTP endpoints on the LAN are supported deliberately; HTTPS remains available for secured endpoints. Requests do not follow redirects and the default HTTP client ignores environment proxies, avoiding an unintended destination for subtitle text or credentials.

Discovery uses `/models` for compatible services, native `/api/tags` for Ollama, and the documented models endpoints for Gemini/Anthropic. It follows their pagination on the same endpoint with at most five pages, 2,000 normalized IDs/names and 4 MB per response, under a 30-second overall timeout. Text-generation capabilities are filtered where the service reports them. Some compatible catalogues also include models unsuitable for translation; use the connection test. A partial list is marked explicitly and manual entry remains available.

Saved keys are reused only on the server for the same provider kind and exact normalized endpoint. Changing that binding requires entering a key again; saving a changed binding without one clears its old key. Failed lookups expose fixed messages, not provider response bodies. Draft keys stay in form memory until it closes; they are not stored in browser storage or catalogue caches.

For Ollama on another machine, use that machine's reachable LAN address, such as `http://192.0.2.7:11434` (documentation address; replace it). The Ollama service must listen on its LAN interface and the host firewall must permit access from Sillage. Inside a container, `localhost` identifies that container. Sillage does not install a model or reconfigure the Ollama host. See the [Ollama network configuration guide](https://docs.ollama.com/faq).

Leave temperature empty to use the model's default; some reasoning models reject sampling parameters. Provider/model feature support varies: **Test connection** is the compatibility check. Unknown model IDs, unsupported parameters and authentication failures produce actionable, sanitized errors instead of silently switching models.

DeepSeek requests explicitly send `thinking: {"type": "disabled"}`, following the same translation choice as TraDoc. DeepSeek enables thinking by default; a large input context window does not prevent an explicit completion budget from being consumed before the JSON answer is complete. Enter the model identifier available to your account (currently `deepseek-flash` for the official Flash API); Sillage does not rewrite your configured model name. See [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) and [JSON output](https://api-docs.deepseek.com/guides/json_mode/).

## Batch contract and reliability

The worker sends only cue IDs and masked text, source/target languages, glossary and bounded scene context. Files, media paths and audio are never included. Exact IDs, duplicate-free JSON, non-empty text and protected formatting remain mandatory. A complete Markdown JSON fence is unwrapped; surrounding prose, extra fields, duplicate/missing IDs and changed tokens remain invalid.

The configured batch size (1–100) is a **ceiling**. Starting size is at most **4** cues for Ollama/compatible endpoints and **10** for named cloud services, further limited to about 1,600/4,000 serialized UTF-8 bytes. A single oversized cue is kept whole and validated, never cut into invented cues. Scene context is independently bounded to the same byte ceilings (up to 20 cues), keeping complete cues; the explicit glossary is not silently truncated. These are conservative defaults, not detected model context limits. A compatible cloud endpoint uses the conservative compatible-service default too.

When structural JSON/formatting validation fails, enabled recovery progressively halves the batch down to one cue. Truncation first gets one retry with more output room, then smaller batches if necessary. A parent batch reaches SQLite only after **all** descendants validate. Each original batch and all its retries/descendants share at most `min(64, (retries + 1) × (2 × cue_count − 1))` HTTP attempts. Retries 0 disables splitting/retries. A persistently invalid single cue or an exhausted budget stops safely with stable cue IDs; earlier validated batches remain resumable.

The worker uses recovered smaller sizes on the next wave and remembers them in job metadata across resumes/restarts and the latest 20 jobs of the **same profile and exact configuration fingerprint**. Different models/profiles/settings do not inherit that ceiling. This conservative ceiling does not automatically increase; changing the saved profile settings resets its empirical history for new jobs. Existing job fingerprint checks still prevent mixing different provider settings in a resumed translation. The job footer shows the current adaptive ceiling. Settings retain concurrency 1–8, timeout 1–600 seconds and retries 0–5.

Network/timeouts/HTTP 408/409/425/429/5xx retry with backoff; numeric Retry-After is capped at 30 seconds. These failures, auth/client errors, explicit refusals and provider interruptions never trigger structural splitting. Cancellation propagates. Repair prompts never echo a previous raw provider response. The output budget includes IDs/JSON/UTF-8 with a 2,048-token floor and 8,192 ceiling; reported output truncation is never accepted.

Use **Reprendre** after updating to keep validated checkpoints. Operational learning adds only job metadata; no database migration or profile edit is required. If timing validation fails before translation, changing/retrying the model will not repair the source. Zero-duration events are kept byte-for-byte in the decoded document, excluded from translation and marked for review; genuinely reversed timestamps remain refused with event/line/time diagnostics. Sillage never guesses or rewrites source timings to hide corruption.

Usage reports numeric token counts returned by the provider, including parseable failed translation attempts. Missing usage is recorded as zero, so counts do not prove billing totals. There is no price catalogue or cost estimate. Language plausibility checks flag substantial unchanged text and obvious English output when French was requested. They cannot certify language, meaning, terminology or subtitle reading quality; review the preview.

Keys stay in backend configuration and are omitted from public provider responses. These adapters do not log HTTP bodies, headers, keys or provider error bodies. Endpoint failures are mapped to fixed messages. Do not enable HTTP wire/debug logging in an installation handling private text.

## API references and implementation choice

Checked 2026-10-26 against [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Anthropic authentication](https://platform.claude.com/docs/en/manage-claude/authentication), [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation), [Gemini generateContent](https://ai.google.dev/api/generate-content), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion), and [Ollama chat](https://docs.ollama.com/api/chat). OpenAI's docs recommend Responses for new OpenAI-specific applications; Sillage uses Chat Completions to share a narrow text-only protocol with compatible servers.

The implementation uses small `httpx` adapters and local validation. [LiteLLM](https://docs.litellm.ai/docs/) offers a unified SDK, many providers, routing/fallback and a gateway. For this local application's seven explicit provider kinds, direct adapters keep endpoint behavior, secret handling and retry budgets visible, without adding a routing/model registry layer. Reconsider an SDK if provider breadth grows substantially. Neither choice replaces subtitle-specific validation.

Tests use an injected `httpx.AsyncClient` and `MockTransport`; no paid service, real credential or LAN model was contacted for automated validation. Live account permissions, model capability and LAN reachability remain installation checks.
