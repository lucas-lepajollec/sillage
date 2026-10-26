"""Reasoning preference on the wire, required-mode compatibility and safe diagnostics."""
import asyncio
import json

import httpx
import pytest

from test_providers import config, envelope, output
from sillage.providers import ProviderConfig, ProviderError, StructuredOutputError, test_connection, translate
from sillage.reasoning import MANDATORY, OBSERVED, UNVERIFIED, resolve_policy


async def call(kind, model, *, metadata=None, data=None, status=200, retries=0, segments=None, temperature=None):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith(('/models', '/api/show')):
            return httpx.Response(200, json=metadata or {})
        return httpx.Response(status, json=data or envelope(kind))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await translate(config(kind, model=model, retries=retries, temperature=temperature,
                                        **({'base_url': 'http://localhost:1234/v1'} if kind == 'custom' else {})),
                                 segments or [{'id': 'a', 'text': 'Hello.'}], client=client)
    return result, [json.loads(r.content) for r in requests if not r.url.path.endswith(('/models', '/api/show'))], requests


@pytest.mark.parametrize('kind,model,controls', [
    ('openai', 'gpt-5.5', {'reasoning_effort': 'none'}),
    ('openai', 'gpt-4.1', {}),
    ('anthropic', 'claude-sonnet-4-6', {'thinking': {'type': 'disabled'}}),
    ('anthropic', 'claude-sonnet-5-5', {'thinking': {'type': 'between_tools'}, 'output_config': {'effort': 'low'}}),
    ('deepseek', 'deepseek-flash', {'thinking': {'type': 'disabled'}}),
    ('groq', 'qwen/qwen3-32b', {'reasoning_effort': 'none'}),
    ('groq', 'llama-3.3-70b-versatile', {}),
    ('mistral', 'mistral-small-latest', {'reasoning_effort': 'none'}),
    ('xai', 'grok-4.3', {'reasoning_effort': 'none'}),
    ('vllm', 'Qwen3-8B', {'reasoning_effort': 'none', 'chat_template_kwargs': {'enable_thinking': False, 'thinking': False}}),
    ('llamacpp', 'Qwen3-8B', {'reasoning_effort': 'none', 'chat_template_kwargs': {'enable_thinking': False}}),
    ('custom', 'unknown', {'reasoning_effort': 'none'}),
])
async def test_preferred_off_controls_reach_the_generation(kind, model, controls):
    result, bodies, _ = await call(kind, model)
    assert result['translations'] == {'a': 'Bonjour.'}
    for field, value in controls.items():
        assert bodies[0][field] == value
    for forbidden in ('include_reasoning', 'reasoning_format', 'display'):
        assert forbidden not in bodies[0]  # Hiding a trace is not disabling reasoning.
    assert MANDATORY not in result['warnings']


@pytest.mark.parametrize('kind,model,key,value', [
    ('openai', 'gpt-5-mini', 'reasoning_effort', 'minimal'),
    ('openai', 'o3', 'reasoning_effort', 'low'),
    ('openai', 'gpt-6.1-sol', 'reasoning_effort', 'low'),
    ('anthropic', 'claude-opus-5-5', 'thinking', {'type': 'adaptive'}),
    ('groq', 'openai/gpt-oss-120b', 'reasoning_effort', 'low'),
    ('mistral', 'zai-glm-5-3', 'reasoning_effort', 'low'),
    ('xai', 'grok-4.7', 'reasoning_effort', 'low'),
    ('ollama', 'gpt-oss:20b', 'think', 'low'),
    ('vllm', 'openai/gpt-oss-20b', 'reasoning_effort', 'low'),
])
async def test_mandatory_reasoning_still_translates_and_warns(kind, model, key, value):
    result, bodies, _ = await call(kind, model, temperature=0.2)
    assert result['translations'] == {'a': 'Bonjour.'}
    assert MANDATORY in result['warnings']
    assert bodies[0][key] == value
    if kind in {'anthropic', 'openai'}:
        assert 'temperature' not in bodies[0]
        assert any('température' in w for w in result['warnings'])


@pytest.mark.parametrize('model,thinking,mandatory', [
    ('gemini-2.5-flash', {'thinkingBudget': 0}, False),
    ('gemini-2.5-pro', {'thinkingBudget': 128}, True),
    ('gemini-3-flash-preview', {'thinkingLevel': 'minimal'}, True),
    ('gemini-3.1-pro-preview', {'thinkingLevel': 'low'}, True),
    ('gemini-3.8-flash', {'thinkingLevel': 'low'}, True),
])
async def test_gemini_budget_zero_is_not_mistaken_for_minimal(model, thinking, mandatory):
    result, bodies, _ = await call('gemini', model)
    assert bodies[0]['generationConfig']['thinkingConfig'] == thinking
    assert (MANDATORY in result['warnings']) is mandatory


@pytest.mark.parametrize('values,control,mandatory', [
    ([False, True], False, False), ([False], False, False),
    (['low', 'medium', 'high'], 'low', True), ([True], True, True),
])
async def test_ollama_honors_show_capabilities(values, control, mandatory):
    result, bodies, requests = await call('ollama', 'local-custom-name', metadata={'thinking': {'values': values}})
    assert requests[0].url.path == '/api/show' and requests[0].method == 'POST'
    assert json.loads(requests[0].content) == {'model': 'local-custom-name'}
    assert bodies[0]['think'] == control
    assert (MANDATORY in result['warnings']) is mandatory


@pytest.mark.parametrize('options,expected,mandatory', [
    (['off', 'on'], 'off', False), (['low', 'high'], 'low', True), (['on'], 'on', True),
])
async def test_native_lmstudio_controls_and_final_text(options, expected, mandatory):
    meta = {'models': [{'type': 'llm', 'key': 'local', 'capabilities': {'reasoning': {'allowed_options': options}}}]}
    data = {'output': [{'type': 'message', 'content': output()}],
            'stats': {'input_tokens': 10, 'total_output_tokens': 5}}
    result, bodies, requests = await call('lmstudio', 'local', metadata=meta, data=data)
    assert requests[0].url.path == '/api/v1/models'
    assert requests[-1].url.path == '/api/v1/chat'
    assert bodies[0]['reasoning'] == expected and bodies[0]['store'] is False
    assert bodies[0]['integrations'] == []
    assert json.loads(bodies[0]['input'])['segments'] == [{'id': 'a', 'text': 'Hello.'}]
    assert result['usage'] == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
    assert (MANDATORY in result['warnings']) is mandatory


async def test_lmstudio_without_exposed_control_still_works_with_warning():
    meta = {'models': [{'type': 'llm', 'key': 'local', 'capabilities': {'vision': False}}]}
    result, bodies, _ = await call('lmstudio', 'local', metadata=meta,
                                  data={'output': [{'type': 'message', 'content': output()}]})
    assert 'reasoning' not in bodies[0]
    assert UNVERIFIED in result['warnings']


async def test_openrouter_mandatory_metadata_prevents_an_invalid_off_request():
    meta = {'data': [{'id': 'vendor/model', 'reasoning': {'mandatory': True, 'supported_efforts': ['high', 'low']}}]}
    result, bodies, _ = await call('openrouter', 'vendor/model', metadata=meta)
    assert bodies[0]['reasoning'] == {'enabled': True, 'effort': 'low'}
    assert bodies[0]['provider'] == {'require_parameters': True}
    assert MANDATORY in result['warnings']


async def test_openrouter_without_reasoning_omits_unsupported_controls():
    meta = {'data': [{'id': 'vendor/model', 'supported_parameters': ['temperature', 'max_tokens']}]}
    _, bodies, _ = await call('openrouter', 'vendor/model', metadata=meta)
    assert 'reasoning' not in bodies[0]


@pytest.mark.parametrize('failure', ['redirect', 'oversized', 'timeout', 'malformed'])
async def test_metadata_failure_is_bounded_and_does_not_silently_enable_reasoning(failure):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == '/api/show':
            if failure == 'timeout':
                raise httpx.ReadTimeout('private secret', request=request)
            if failure == 'redirect':
                return httpx.Response(302, headers={'Location': 'http://unintended.invalid'})
            return httpx.Response(200, content=b'x' * (4_000_001 if failure == 'oversized' else 20))
        assert json.loads(request.content)['think'] is False
        return httpx.Response(200, json=envelope('ollama'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await translate(config('ollama'), [{'id': 'a', 'text': 'Hello.'}], client=client)
    assert len(requests) == 2 and all(r.url.host == 'localhost' for r in requests)
    assert result['warnings'] == [UNVERIFIED]
    assert 'private secret' not in str(result)


@pytest.mark.parametrize('kind', ['openai', 'anthropic', 'gemini', 'ollama', 'mistral', 'lmstudio'])
async def test_reasoning_is_detected_without_leaking_its_text(kind):
    data = envelope(kind)
    secret = 'PRIVATE-THOUGHT-MUST-NOT-LEAVE-ADAPTER'
    if kind == 'anthropic':
        data['content'].insert(0, {'type': 'thinking', 'thinking': secret})
    elif kind == 'gemini':
        data['usageMetadata']['thoughtsTokenCount'] = 12
    elif kind == 'ollama':
        data['message']['thinking'] = secret
    elif kind == 'lmstudio':
        data = {'output': [{'type': 'reasoning', 'content': secret}, {'type': 'message', 'content': output()}]}
    elif kind == 'mistral':
        data['choices'][0]['message']['content'] = [{'type': 'thinking', 'thinking': [secret]}, {'type': 'text', 'text': output()}]
    else:
        data['usage']['completion_tokens_details'] = {'reasoning_tokens': 5}
    result, _, _ = await call(kind, 'user-selected-model', data=data)
    assert result['translations'] == {'a': 'Bonjour.'}
    assert OBSERVED in result['warnings'] and secret not in str(result)


async def test_off_rejection_is_not_retried_by_removing_the_off_flag():
    with pytest.raises(ProviderError, match='Aucun paramètre de désactivation'):
        await call('custom', 'unknown', status=400, retries=5)


async def test_mandatory_warning_survives_structural_failure():
    with pytest.raises(StructuredOutputError) as exc:
        await call('groq', 'openai/gpt-oss-20b', data=envelope(text='invalid'))
    assert exc.value.warnings == [MANDATORY]


async def test_connection_reports_mandatory_reasoning_instead_of_blocking():
    def handler(request):
        assert json.loads(request.content)['reasoning_effort'] == 'low'
        return httpx.Response(200, json=envelope(text=output([{'id': 'connection-check', 'text': 'Bonjour.'}])))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        message = await test_connection(config('xai', model='grok-4.7'), client=client)
    assert MANDATORY in message and 'validées' in message


async def test_pro_models_use_responses_and_preserve_required_reasoning():
    data = {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': []},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': output()}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 5}}
    result, bodies, requests = await call('openai', 'gpt-5.4-pro', data=data)
    assert requests[-1].url.path == '/v1/responses'
    assert bodies[0]['reasoning'] == {'effort': 'medium'} and bodies[0]['store'] is False
    assert result['translations'] == {'a': 'Bonjour.'} and MANDATORY in result['warnings']


async def test_metadata_cancellation_propagates():
    def handler(request):
        raise asyncio.CancelledError
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(asyncio.CancelledError):
            await resolve_policy(ProviderConfig.model_validate(config('ollama')), client)


async def test_capability_cache_is_short_lived_and_isolated_by_secret_endpoint_and_model(monkeypatch):
    from sillage import reasoning
    monkeypatch.setattr(reasoning, '_CACHE', {})
    now = [100.0]
    monkeypatch.setattr(reasoning.time, 'monotonic', lambda: now[0])
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'thinking': {'values': [False, True]}})
    settings = ProviderConfig.model_validate(config('ollama'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await resolve_policy(settings, client, cache=True)
        await resolve_policy(settings, client, cache=True)
        assert len(calls) == 1
        for change in ({'model': 'other'}, {'api_key': 'another-synthetic-key'}, {'base_url': 'http://localhost:11435'}):
            await resolve_policy(settings.model_copy(update=change), client, cache=True)
        assert len(calls) == 4
        now[0] += 61
        await resolve_policy(settings, client, cache=True)
        assert len(calls) == 5
    assert 'synthetic' not in repr(reasoning._CACHE)


@pytest.mark.parametrize('kind', ['lmstudio', 'openai'])
async def test_native_output_limit_never_accepts_valid_looking_json(kind):
    data = ({'output': [{'type': 'message', 'content': output()}], 'stats': {'total_output_tokens': 2048}}
            if kind == 'lmstudio' else {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output()}]}]})
    with pytest.raises(StructuredOutputError, match='limite de sortie'):
        await call(kind, 'gpt-5.4-pro' if kind == 'openai' else 'local', data=data)


async def test_openrouter_required_model_without_effort_selector_stays_usable():
    result, bodies, _ = await call('openrouter', 'vendor/model', metadata={'data': [
        {'id': 'vendor/model', 'reasoning': {'mandatory': True}}]})
    assert bodies[0]['reasoning'] == {'enabled': True} and MANDATORY in result['warnings']


async def test_observed_reasoning_warning_survives_a_failed_attempt(monkeypatch):
    async def sleep(delay):
        pass
    monkeypatch.setattr('sillage.providers.asyncio.sleep', sleep)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            data = envelope(text='invalid')
            data['choices'][0]['message']['reasoning_content'] = 'PRIVATE-THOUGHT'
            return httpx.Response(200, json=data)
        return httpx.Response(200, json=envelope())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await translate(config(retries=1), [{'id': 'a', 'text': 'Hello.'}], client=client)
    assert OBSERVED in result['warnings'] and 'PRIVATE-THOUGHT' not in str(result)
    assert all(body['reasoning_effort'] == 'none' for body in calls)
