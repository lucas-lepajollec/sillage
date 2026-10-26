# Translation providers

Sillage calls the provider selected for a job. There is no production simulator and no bundled model catalogue: enter an exact model identifier available to your account or Ollama server. Configure the provider in the interface, save its key when needed, then use **Test connection**. This performs one small, real translation request and can incur the provider's usual charge. Sillage never searches the workstation for credentials.

| Kind | Default API base URL | Protocol |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | Chat Completions, JSON output |
| Anthropic | `https://api.anthropic.com/v1` | Messages, text blocks |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | `models/{model}:generateContent` |
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI compatible Chat Completions |
| OpenRouter | `https://openrouter.ai/api/v1` | OpenAI compatible Chat Completions |
| Ollama | `http://localhost:11434` | Native `/api/chat`, non-streaming JSON |
| Custom | Required | OpenAI compatible `/chat/completions` |

The base URL includes the API version prefix shown above. Do not put a key, URL username/password, query string or fragment in it. API keys travel in request headers. Custom and Ollama permit a blank key for servers without authentication. HTTP endpoints on the LAN are supported deliberately; HTTPS remains available for secured endpoints. Requests do not follow redirects and the default HTTP client ignores environment proxies, avoiding an unintended destination for subtitle text or credentials.

For Ollama on another machine, use that machine's reachable LAN address, such as `http://192.0.2.7:11434` (documentation address; replace it). The Ollama service must listen on its LAN interface and the host firewall must permit access from Sillage. Inside a container, `localhost` identifies that container. Sillage does not install a model or reconfigure the Ollama host. See the [Ollama network configuration guide](https://docs.ollama.com/faq).

Leave temperature empty to use the model's default; some reasoning models reject sampling parameters. Provider/model feature support varies: **Test connection** is the compatibility check. Unknown model IDs, unsupported parameters and authentication failures produce actionable, sanitized errors instead of silently switching models.

DeepSeek requests explicitly send `thinking: {"type": "disabled"}`, following the same translation choice as TraDoc. DeepSeek enables thinking by default; a large input context window does not prevent an explicit completion budget from being consumed before the JSON answer is complete. Enter the model identifier available to your account (currently `deepseek-flash` for the official Flash API); Sillage does not rewrite your configured model name. See [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) and [JSON output](https://api-docs.deepseek.com/guides/json_mode/).

## Batch contract and reliability

The worker sends only cue IDs and masked text, up to 20 surrounding context cues, the source/target languages and the glossary. Files, media paths and audio are never included by these adapters. Formatting placeholders such as `__SILLAGE_0000__` must survive in exactly the same order. Only the current batch's exact IDs are accepted; duplicate JSON fields, missing or extra IDs, empty/oversized text, new control characters and changed formatting are rejected before checkpointing. A JSON response alone does not establish a valid translation.

Settings allow batch size 1–100, concurrency 1–8, timeout 1–600 seconds and 0–5 additional whole-batch attempts. The worker owns batching, concurrency and checkpoints. The completion budget accounts for dialogue, IDs, JSON syntax and UTF-8 text, with a 2,048-token floor and an 8,192-token ceiling. A provider-reported output limit is never accepted, even if its JSON looks complete; retries increase the budget up to that ceiling.

Adapter retries cover timeouts, network failures, HTTP 408/409/425/429/5xx and invalid/incomplete output, with exponential backoff; numeric `Retry-After` is honored up to 30 seconds. Authentication failures, other client errors and redirects are immediate failures. Explicit content refusals are not retried. Cancellation propagates through async calls. Malformed output receives a structural repair instruction without echoing the previous response into a new prompt.

When retries are enabled and a multi-cue batch still fails structural validation or reaches its output limit, Sillage tries two smaller halves once each, preserving adjacent scene context. The combined batch reaches the worker only after both halves validate; no partial half is checkpointed. Recovery never splits a batch again and does not run for transport/authentication/rate-limit failures or explicit refusals. This adds at most two calls beyond the configured whole-batch attempts, so a batch has a maximum of `retries + 3` calls (eight at the highest setting). Setting retries to zero disables automatic recovery entirely.

Errors distinguish output truncation, protected formatting and malformed/incomplete structures without revealing response bodies. After a container update, use **Reprendre** on an existing failed job to retain validated checkpoints. Changing translation-affecting provider settings instead requires a new job to avoid mixing configurations. If a single cue still cannot fit or pass validation, the job stops safely for operator review.

Usage reports numeric token counts returned by the provider, including parseable failed translation attempts. Missing usage is recorded as zero, so counts do not prove billing totals. There is no price catalogue or cost estimate. Language plausibility checks flag substantial unchanged text and obvious English output when French was requested. They cannot certify language, meaning, terminology or subtitle reading quality; review the preview.

Keys stay in backend configuration and are omitted from public provider responses. These adapters do not log HTTP bodies, headers, keys or provider error bodies. Endpoint failures are mapped to fixed messages. Do not enable HTTP wire/debug logging in an installation handling private text.

## API references and implementation choice

Checked 2026-10-26 against [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Anthropic authentication](https://platform.claude.com/docs/en/manage-claude/authentication), [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation), [Gemini generateContent](https://ai.google.dev/api/generate-content), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion), and [Ollama chat](https://docs.ollama.com/api/chat). OpenAI's docs recommend Responses for new OpenAI-specific applications; Sillage uses Chat Completions to share a narrow text-only protocol with compatible servers.

The implementation uses small `httpx` adapters and local validation. [LiteLLM](https://docs.litellm.ai/docs/) offers a unified SDK, many providers, routing/fallback and a gateway. For this local application's seven explicit provider kinds, direct adapters keep endpoint behavior, secret handling and retry budgets visible, without adding a routing/model registry layer. Reconsider an SDK if provider breadth grows substantially. Neither choice replaces subtitle-specific validation.

Tests use an injected `httpx.AsyncClient` and `MockTransport`; no paid service, real credential or LAN model was contacted for automated validation. Live account permissions, model capability and LAN reachability remain installation checks.
