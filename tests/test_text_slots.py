"""Visible-text wire contract: synthetic subtitles, no real model or media."""
import json
import re

import httpx
import pytest

from conftest import ASS
from test_providers import config, envelope, invoke, output
from sillage.providers import ProviderError
from sillage.subtitles import SubtitleDocument


KINDS = ['openai', 'deepseek', 'anthropic', 'gemini', 'ollama', 'openrouter',
         'custom', 'groq', 'mistral', 'xai', 'lmstudio', 'vllm', 'llamacpp']


def payload(request, kind='openai'):
    body = json.loads(request.content)
    content = (body['contents'][0]['parts'][0]['text'] if kind == 'gemini'
               else body['input'] if kind == 'lmstudio'
               else body['messages'][0]['content'] if kind == 'anthropic'
               else body['messages'][1]['content'])
    return json.loads(content)


def translated(text):
    # This simulated translator deliberately cannot reproduce technical tokens.
    if isinstance(text, list):
        return [translated(part) for part in text]
    return re.sub(r'__SILLAGE_.*?__', '', text).replace('Hello', 'Bonjour').replace('world', 'monde').replace('Goodbye', 'Au revoir').replace('Station', 'Gare')


@pytest.mark.parametrize('kind', KINDS)
def test_model_that_drops_all_markers_translates_formatted_cues_in_one_request(kind):
    doc = SubtitleDocument(ASS, 'ass')
    calls = []
    def handler(request):
        user = payload(request, kind)
        calls.append(user)
        assert [cue['text'] for cue in user['segments']] == [['Hello', 'world!', 'Goodbye.'], ['Station']]
        assert '__SILLAGE_' not in json.dumps(user['segments'])
        return httpx.Response(200, json=envelope(kind, output([
            cue | {'text': translated(cue['text'])} for cue in user['segments']])))
    settings = config(kind)
    if kind == 'custom':
        settings['base_url'] = 'http://127.0.0.1:19999/v1'
    result = invoke(handler, settings=settings, segments=doc.segments)
    doc.validate_translations(result['translations'], require_all=True)
    assert doc.render(result['translations']) == ASS.replace('Hello', 'Bonjour').replace('world', 'monde').replace('Goodbye', 'Au revoir').replace('Station', 'Gare')
    assert len(calls) == result['requests'] == 1
    assert result['batch_size'] == 2 and not result['recovered']
    assert result['diagnostics'] == {}


@pytest.mark.parametrize('bad', [[], ['Bonjour'], ['Bonjour', 'monde', 'ajout'],
                                ['Bonjour', ''], ['Bonjour', None], ['Bonjour', ['monde']],
                                ['Bonjour', '<i>monde</i>'], ['Bonjour', 'monde\n!'],
                                ['Bonjour', '__SILLAGE_0000__monde'], ['Bonjour', '__SILLAGE_broken']])
def test_wrong_slot_counts_types_and_injected_markup_are_never_rendered(bad):
    source = [{'id': 'a', 'text': 'Hello __SILLAGE_0000__world!'}]
    with pytest.raises(ProviderError) as failure:
        invoke(lambda request: httpx.Response(200, json=envelope(text=output([{'id': 'a', 'text': bad}]))), segments=source)
    assert failure.value.translations == {}
    assert sum(failure.value.diagnostics.values()) > 0
    assert 'Hello' not in str(failure.value) and 'world' not in str(failure.value)


def test_partial_array_failure_retries_only_bad_cue_with_specific_instruction():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        cues = payload(request)['segments']
        items = [cue | {'text': translated(cue['text'])} for cue in cues]
        if len(calls) == 1:
            items[1]['text'] = ['Bonjour']
        else:
            assert 'Text slot count changed' in calls[-1]['messages'][0]['content']
        return httpx.Response(200, json=envelope(text=output(items)))
    source = [{'id': name, 'text': 'Hello __SILLAGE_0000__world!'} for name in ['a', 'b', 'c']]
    result = invoke(handler, settings=config(retries=1), segments=source)
    assert result['translations'] == {name: 'Bonjour __SILLAGE_0000__monde!' for name in ['a', 'b', 'c']}
    assert [len(json.loads(call['messages'][1]['content'])['segments']) for call in calls] == [3, 2]
    assert result['batch_size'] == 3 and result['diagnostics'] == {'slot_count': 1, 'fragment_fallback': 1}


def test_srt_line_endings_entities_and_literal_punctuation_are_restored_exactly():
    original = '1\r\n00:00:00,500 --> 00:00:02,000\r\n<i>Hello</i>  &amp;  world!\r\nGoodbye.\r\n\r\n'
    doc = SubtitleDocument(original, 'srt')
    result = invoke(lambda request: httpx.Response(200, json=envelope(text=output([
        cue | {'text': translated(cue['text'])} for cue in payload(request)['segments']]))), segments=doc.segments)
    assert doc.render(result['translations']) == original.replace('Hello', 'Bonjour').replace('world', 'monde').replace('Goodbye', 'Au revoir')


def test_only_a_single_span_can_be_safely_unwrapped():
    source = [{'id': 'a', 'text': '__SILLAGE_0000__Hello.__SILLAGE_0001__'}]
    result = invoke(lambda request: httpx.Response(200, json=envelope()), segments=source)
    assert result['translations'] == {'a': '__SILLAGE_0000__Bonjour.__SILLAGE_0001__'}
    source[0]['text'] = 'Hello __SILLAGE_0000__world!'
    with pytest.raises(ProviderError):
        invoke(lambda request: httpx.Response(200, json=envelope()), segments=source)


def test_malformed_json_has_safe_diagnostic_and_specific_repair():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json=envelope(text='{"translations":'))
        assert 'Invalid JSON syntax' in calls[-1]['messages'][0]['content']
        return httpx.Response(200, json=envelope())
    result = invoke(handler, settings=config(retries=1))
    assert result['diagnostics'] == {'malformed_json': 1}
    assert result['translations'] == {'a': 'Bonjour.'}


def test_connection_refuses_a_model_that_merges_explicit_fragments_without_paid_repairs():
    import asyncio
    from sillage.providers import test_connection
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope(text=output([{'id': 'connection-check', 'text': 'Bonjour, au revoir.'}])))
    async def perform():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await test_connection(config(retries=5), client=client)
    with pytest.raises(ProviderError):
        asyncio.run(perform())
    assert len(calls) == 1
