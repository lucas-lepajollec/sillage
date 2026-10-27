"""Failure-specific recovery, stable explicit fragments and durable partial work."""
import hashlib
import json

import httpx
import pytest

from conftest import ASS
from sillage.providers import ProviderError, fragment_plan
from sillage.subtitles import SubtitleDocument
from test_providers import config, envelope, invoke, output
from test_text_slots import KINDS, payload, translated


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def sleep(delay):
        pass
    monkeypatch.setattr('sillage.providers.asyncio.sleep', sleep)


@pytest.mark.parametrize('kind', KINDS)
def test_plain_cue_singleton_array_is_unambiguous_without_recovery(kind):
    settings = config(kind)
    if kind == 'custom':
        settings['base_url'] = 'http://127.0.0.1:19999/v1'
    result = invoke(lambda request: httpx.Response(200, json=envelope(kind, output([{'id': 'a', 'text': ['Bonjour.']}]))), settings=settings)
    assert result['translations'] == {'a': 'Bonjour.'}
    assert result['requests'] == 1 and not result['recovered']


@pytest.mark.parametrize('kind', KINDS)
def test_persistently_flattened_arrays_switch_to_explicit_fragment_strings(kind):
    doc = SubtitleDocument(ASS, 'ass')
    calls = []
    def handler(request):
        cues = payload(request, kind)['segments']
        calls.append(cues)
        items = []
        for cue in cues:
            text = translated(cue['text'])
            # The model always flattens arrays. Identical array retries cannot fix it.
            items.append(cue | {'text': ' '.join(text) if isinstance(text, list) else text})
        return httpx.Response(200, json=envelope(kind, output(items)))
    settings = config(kind, retries=1)
    if kind == 'custom':
        settings['base_url'] = 'http://127.0.0.1:19999/v1'
    result = invoke(handler, settings=settings, segments=doc.segments)
    assert len(calls) == 2 and result['requests'] == 2
    assert calls[1] == [{'id': 'e000001.s0000', 'text': 'Hello'}, {'id': 'e000001.s0001', 'text': 'world!'}, {'id': 'e000001.s0002', 'text': 'Goodbye.'}]
    assert result['batch_size'] == 2
    assert doc.render(result['translations']) == ASS.replace('Hello', 'Bonjour').replace('world', 'monde').replace('Goodbye', 'Au revoir').replace('Station', 'Gare')


def test_partial_fragments_survive_failure_and_resume_sends_only_the_missing_fragment():
    source = [{'id': 'e000001', 'text': 'Hello__SILLAGE_0000__world__SILLAGE_0001__Goodbye__SILLAGE_0002__Station'}]
    calls = []
    def broken(request):
        cues = payload(request)['segments']
        calls.append(cues)
        if len(calls) == 1:
            items = [{'id': 'e000001', 'text': ['Bonjour.']}]
        else:
            items = [cue | {'text': '' if cue['id'].endswith('s0003') else translated(cue['text'])} for cue in cues]
        return httpx.Response(200, json=envelope(text=output(items)))
    with pytest.raises(ProviderError) as failed:
        invoke(broken, settings=config(retries=1), segments=source)
    error = failed.value
    assert error.translations == {} and len(error.fragment_checkpoints) == 3
    assert error.fragment_retry_ids == ['e000001']
    assert error.failures['e000001.s0003'] == 'Empty translated text'
    calls.clear()
    def corrected(request):
        cues = payload(request)['segments']
        calls.append(cues)
        return httpx.Response(200, json=envelope(text=output([cue | {'text': translated(cue['text'])} for cue in cues])))
    result = invoke(corrected, settings=config(retries=1), segments=source,
                    fragment_checkpoints=error.fragment_checkpoints, fragment_retry_ids=error.fragment_retry_ids)
    assert calls == [[{'id': 'e000001.s0003', 'text': 'Station'}]]
    assert result['translations'] == {'e000001': 'Bonjour__SILLAGE_0000__monde__SILLAGE_0001__Au revoir__SILLAGE_0002__Gare'}
    assert len(result['fragment_checkpoints']) == 4 and result['requests'] == 1


@pytest.mark.parametrize('defect', ['source_hash', 'unknown_id', 'raw_markup', 'empty'])
def test_fragment_cache_is_source_bound_and_revalidated_before_any_request(defect):
    source = [{'id': 'e000001', 'text': 'Hello__SILLAGE_0000__world'}]
    wire, _ = fragment_plan(source)
    record = {'source_hash': hashlib.sha256(wire[0]['text'].encode()).hexdigest(), 'text': 'Bonjour'}
    key = wire[0]['id']
    if defect == 'source_hash':
        record['source_hash'] = 'wrong'
    elif defect == 'unknown_id':
        key = 'unexpected'
    else:
        record['text'] = '<i>Bonjour</i>' if defect == 'raw_markup' else ''
    def forbidden(request):
        pytest.fail('Invalid cache must never be sent to the provider')
    with pytest.raises(ProviderError):
        invoke(forbidden, segments=source, fragment_checkpoints={key: record})


def test_fully_cached_fragments_reconstruct_without_a_generation_call():
    source = [{'id': 'e000001', 'text': '__SILLAGE_0000__Hello__SILLAGE_0001__world'}]
    wire, _ = fragment_plan(source)
    records = {cue['id']: {'source_hash': hashlib.sha256(cue['text'].encode()).hexdigest(), 'text': translated(cue['text'])} for cue in wire}
    result = invoke(lambda request: pytest.fail('Already validated text must not be translated again'), segments=source, fragment_checkpoints=records)
    assert result['requests'] == 0 and result['translations'] == {'e000001': '__SILLAGE_0000__Bonjour__SILLAGE_0001__monde'}


def test_fragment_recovery_does_not_guess_ids_or_accept_refusals():
    source = [{'id': 'a', 'text': 'Hello__SILLAGE_0000__world'}]
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=envelope(text=output([{'id': 'a', 'text': ['Bonjour.']}])) )
        data = envelope()
        data['choices'][0]['message']['refusal'] = 'synthetic private response'
        return httpx.Response(200, json=data)
    with pytest.raises(ProviderError, match='refusé') as failure:
        invoke(handler, settings=config(retries=5), segments=source)
    assert len(calls) == 2 and failure.value.translations == {}
    assert 'synthetic private response' not in str(failure.value)


def test_failed_fallback_mode_is_remembered_even_without_a_valid_fragment():
    source = [{'id': 'a', 'text': 'Hello__SILLAGE_0000__world'}]
    calls = []
    def broken(request):
        cues = payload(request)['segments']
        calls.append(cues)
        items = [{'id': 'a', 'text': ['Bonjour.']}] if len(calls) == 1 else []
        return httpx.Response(200, json=envelope(text=output(items)))
    with pytest.raises(ProviderError) as failed:
        invoke(broken, settings=config(retries=1), segments=source)
    assert failed.value.fragment_checkpoints == {} and failed.value.fragment_retry_ids == ['a']
    calls.clear()
    def good(request):
        cues = payload(request)['segments']
        calls.append(cues)
        return httpx.Response(200, json=envelope(text=output([cue | {'text': translated(cue['text'])} for cue in cues])))
    result = invoke(good, settings=config(retries=0), segments=source, fragment_retry_ids=failed.value.fragment_retry_ids)
    assert len(calls) == 1 and all(isinstance(cue['text'], str) for cue in calls[0])
    assert result['translations'] == {'a': 'Bonjour__SILLAGE_0000__monde'}


def test_storage_upgrade_preserves_old_checkpoints_and_fragment_lifecycle(tmp_path):
    from sillage.storage import Store
    from sillage.app import public_job
    store = Store(tmp_path / 'config')
    store.put_job({'id': 'job', 'path': '/synthetic/video.mkv', 'status': 'error', 'fragment_retry_ids': ['a']})
    store.checkpoint('job', {'a': 'Bonjour'})
    with store.connect() as db:
        db.execute('DROP TABLE fragment_checkpoints')  # Exact pre-upgrade schema.
    reopened = Store(store.folder)
    assert reopened.translations('job') == {'a': 'Bonjour'} and reopened.fragments('job') == {}
    fragment = {'a.s0000': {'source_hash': hashlib.sha256(b'Hello').hexdigest(), 'text': 'synthetic private partial text'}}
    reopened.checkpoint('job', {}, fragment)
    assert reopened.fragments('job') == fragment
    assert 'synthetic private partial text' not in json.dumps(public_job(reopened.job('job')))
    assert 'fragment_retry_ids' not in public_job(reopened.job('job'))
    reopened.reconfigure_jobs({'job': {'status': 'queued', 'fragment_retry_ids': []}}, restart=True)
    assert not reopened.fragments('job') and not reopened.translations('job')
    reopened.patch('job', status='cancelled')
    reopened.checkpoint('job', {}, fragment)
    reopened.delete_jobs(['job'])
    assert not reopened.jobs() and not reopened.fragments('job')


async def test_fragment_only_progress_obeys_profile_language_and_restart_guards(video, tmp_path):
    from test_jobs import environment
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    record = {'e000001.s0000': {'source_hash': hashlib.sha256(b'Hello world!').hexdigest(), 'text': 'Bonjour le monde !'}}
    store.checkpoint(job['id'], {}, record)
    store.patch(job['id'], status='error', fragment_retry_ids=['e000001'])
    profile = store.provider(job['provider_id'])
    store.save_provider(profile | {'target_language': 'de'})
    with pytest.raises(ValueError, match='langues ont changé'):
        worker.reconfigure([job['id']], job['provider_id'])
    assert store.fragments(job['id']) == record
    worker.reconfigure([job['id']], job['provider_id'], restart=True)
    assert not store.fragments(job['id']) and not store.job(job['id'])['fragment_retry_ids']


def test_reconstructed_size_guard_evicts_only_the_bad_parent_fragments(tmp_path):
    from sillage.storage import Store
    source = [{'id': 'a', 'text': 'Hello__SILLAGE_0000__world__SILLAGE_0001__Goodbye'}]
    wire, _ = fragment_plan(source)
    records = {cue['id']: {'source_hash': hashlib.sha256(cue['text'].encode()).hexdigest(), 'text': 'x' * 400} for cue in wire}
    with pytest.raises(ProviderError, match='reconstituée') as failed:
        invoke(lambda request: pytest.fail('Cached spans require validation, not another call'), segments=source, fragment_checkpoints=records)
    assert failed.value.fragment_checkpoints == {} and set(failed.value.invalidated_fragments) == set(records)
    store = Store(tmp_path / 'config')
    store.checkpoint('job', {'valid': 'Bonjour'}, records | {'other.s0000': records[wire[0]['id']]})
    store.checkpoint('job', {}, failed.value.fragment_checkpoints, failed.value.invalidated_fragments)
    assert set(store.fragments('job')) == {'other.s0000'} and store.translations('job') == {'valid': 'Bonjour'}
