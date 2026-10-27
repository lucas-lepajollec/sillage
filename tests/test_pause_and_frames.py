"""Generated ASS frames and cooperative pause; no real model or media."""
import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import ASS
from sillage.app import create_app
from sillage.jobs import JobPaused, Worker
from sillage.providers import ProviderPaused, translate
from sillage.storage import Store
from sillage.subtitles import FRAME_WARNING, SubtitleDocument
from test_jobs import deterministic, environment
from test_providers import config, envelope, output
from test_text_slots import KINDS, payload


def frames(*, count=80, positioned=True, spacing=40, duration=40, distinct=True):
    header = ASS.split('Dialogue:')[0]
    lines = []
    for i in range(count):
        start = 500 + i * spacing if distinct else 500
        def stamp(ms):
            return f'0:00:{ms // 1000:02}.{ms % 1000 // 10:02}'
        tag = rf'{{\pos({100+i},120)\blur1}}' if positioned else ''
        lines.append(f'Dialogue: 0,{stamp(start)},{stamp(start+duration)},Sign,,0,0,0,,{tag}Station\n')
    return header + ''.join(lines)


def test_baked_animation_retains_all_source_events_but_never_requests_frames():
    text = frames() + ASS.split('[Events]')[1].split('Text\n')[1]
    doc = SubtitleDocument(text, 'ass')
    assert len(doc.cues) == 82 and len(doc.segments) == 2
    assert doc.stats == {'events': 82, 'translatable': 2, 'preserved': 80, 'frame_animation': 80}
    assert all(c.get('warning') == FRAME_WARNING for c in doc.cues[:80])
    assert doc.render({}) == text
    assert doc.resume_translations({'e000001': 'obsolete frame translation'}) == {}
    with pytest.raises(ValueError, match='inattendu'):
        doc.resume_translations({'e999999': 'unexpected'})
    result = {s['id']: s['text'].replace('Hello', 'Bonjour') for s in doc.segments}
    rendered = doc.render(result)
    assert rendered.startswith(frames())  # Frames, layer, position and times untouched.


@pytest.mark.parametrize('options', [
    {'positioned': False}, {'count': 15}, {'duration': 200},
    {'spacing': 1000, 'count': 20}, {'distinct': False},
])
def test_regular_repeats_static_layers_and_sparse_signs_remain_eligible(options):
    doc = SubtitleDocument(frames(**options), 'ass')
    assert len(doc.segments) == options.get('count', 80)
    assert 'frame_animation' not in doc.stats


async def test_resume_old_frame_checkpoints_reuses_dialogue_without_new_call(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    sidecar = video.with_suffix('.en.ass')
    text = frames() + 'Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,Hello world!\n'
    sidecar.write_text(text)
    request['items'][0]['track_id'] = f'external:{sidecar.name}'
    job = (await worker.create(request))[0]
    store.checkpoint(job['id'], {f'e{i:06}': 'obsolete frame' for i in range(1,81)} | {'e000081': 'Bonjour monde !'})
    store.patch(job['id'], total=81, done=81, progress=85)
    with patch('sillage.jobs.providers.translate', side_effect=AssertionError('No paid call')):
        await worker.process(job['id'])
    result = store.job(job['id'])
    assert result['status'] == 'review' and result['done'] == result['total'] == 1
    assert len(store.translations(job['id'])) == 81  # Archived rows are retained.
    assert Path(result['output']).read_text() == text.replace('Hello world!', 'Bonjour monde !')
    assert sidecar.read_text() == text
    assert worker.preview(job['id'])['stats']['frame_animation'] == 80


async def test_pause_drains_concurrent_results_stops_next_wave_and_survives_reopen(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    store.save_provider(store.provider(request['provider_id']) | {'concurrency': 2})
    sidecar = video.with_suffix('.en.srt')
    sidecar.write_text(''.join(f'{i}\n00:00:00,500 --> 00:00:02,000\nHello world!\n\n' for i in range(1,5)))
    request['items'][0]['track_id'] = f'external:{sidecar.name}'
    job = (await worker.create(request))[0]
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def waiting(config, batch, *args, **kwargs):
        calls.extend(s['id'] for s in batch)
        if len(calls) == 2:
            entered.set()
        await release.wait()
        return await deterministic(config, batch, *args)
    worker.active = job['id']
    with patch('sillage.jobs.providers.translate', side_effect=waiting):
        task = asyncio.create_task(worker.process(job['id']))
        await asyncio.wait_for(entered.wait(), 5)
        paused = worker.pause_many([job['id']])[0]
        assert paused['status'] == 'pausing' and not task.done()
        with pytest.raises(ValueError, match='repris'):
            worker.resume(job['id'])
        with pytest.raises(ValueError):
            await worker.delete([job['id']])
        release.set()
        with pytest.raises(JobPaused):
            await asyncio.wait_for(task, 5)
    worker.active = None
    assert store.job(job['id'])['status'] == 'paused'
    assert len(calls) == len(store.translations(job['id'])) == 2
    assert not video.with_suffix('.fr.srt').exists()
    reopened = Worker(Store(store.folder), worker.library)
    await reopened.start()
    try:
        await asyncio.sleep(.4)
        assert store.job(job['id'])['status'] == 'paused'
    finally:
        await reopened.stop()
    async def remaining(config, batch, *args, **kwargs):
        assert not {s['id'] for s in batch}.intersection(calls)
        return await deterministic(config, batch, *args)
    reopened.resume(job['id'])
    with patch('sillage.jobs.providers.translate', side_effect=remaining):
        await reopened.process(job['id'])
    assert store.job(job['id'])['done'] == 4


@pytest.mark.parametrize('kind', KINDS)
async def test_pause_prevents_repairs_and_retains_valid_siblings_on_all_adapters(kind):
    paused, posts = False, []
    def handler(req):
        nonlocal paused
        if req.method != 'POST' or req.url.path == '/api/show':
            return httpx.Response(404)
        cues = payload(req, kind)['segments']
        posts.append(cues)
        paused = True  # User pauses while the first HTTP request is in flight.
        return httpx.Response(200, json=envelope(kind, output([{'id': cues[0]['id'], 'text': 'Bonjour.'}])))
    settings = config(kind, retries=3)
    if kind == 'custom':
        settings['base_url'] = 'http://127.0.0.1:19999/v1'
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderPaused) as caught:
            await translate(settings, [{'id': 'a', 'text': 'Hello'}, {'id': 'b', 'text': 'Goodbye'}],
                            client=client, should_pause=lambda: paused)
    assert len(posts) == 1
    assert caught.value.translations == {'a': 'Bonjour.'}
    assert caught.value.usage['input_tokens'] == 10


async def test_pause_before_export_refuses_write_and_preserves_complete_checkpoints(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    extract = worker.library.extract
    calls = 0
    def pausing_extract(*args):
        nonlocal calls
        result = extract(*args)
        calls += 1
        if calls == 2:
            worker.pause_many([job['id']])
        return result
    worker.active = job['id']
    with patch.object(worker.library, 'extract', side_effect=pausing_extract), patch('sillage.jobs.providers.translate', side_effect=deterministic):
        with pytest.raises(JobPaused):
            await worker.process(job['id'])
    worker.active = None
    assert store.job(job['id'])['status'] == 'paused'
    assert len(store.translations(job['id'])) == 2
    assert not video.with_suffix('.fr.srt').exists()
    worker.resume(job['id'])
    with patch('sillage.jobs.providers.translate', side_effect=AssertionError('Already translated')):
        await worker.process(job['id'])
    assert store.job(job['id'])['status'] == 'completed'


def test_pause_api_selection_is_atomic_and_profile_edits_keep_pause(video, tmp_path):
    app = create_app(tmp_path / 'config', [video.parent], run_worker=False)
    with TestClient(app) as client:
        provider = client.post('/api/providers', json={'kind': 'custom', 'model': 'test', 'base_url': 'http://127.0.0.1:19999/v1'}).json()
        track = app.state.library.inspect(video)['tracks'][0]['id']
        request = {'provider_id': provider['id'], 'items': [{'path': str(video), 'track_id': track}]}
        job = client.post('/api/jobs', json=request).json()[0]
        assert client.post('/api/jobs/pause', json={'ids': [job['id'], 'missing']}).status_code == 400
        assert app.state.store.job(job['id'])['status'] == 'queued'
        paused = client.post(f"/api/jobs/{job['id']}/pause", json={})
        assert paused.json()['status'] == 'paused' and 'pause_requested' not in paused.text
        assert client.post('/api/jobs', json=request).status_code == 400  # No duplicate paused episode.
        changed = client.post('/api/jobs/reconfigure', json={'ids': [job['id']], 'provider_id': provider['id']})
        assert changed.status_code == 200 and changed.json()[0]['status'] == 'paused'
        assert client.delete('/api/providers/' + provider['id']).status_code == 400
        resumed = client.post(f"/api/jobs/{job['id']}/resume", json={})
        assert resumed.json()['status'] == 'queued'
        app.state.store.patch(job['id'], status='writing')
        assert client.post(f"/api/jobs/{job['id']}/pause", json={}).status_code == 400
        app.state.store.patch(job['id'], status='pausing', pause_requested=True)
    reopened = Worker(Store(app.state.store.folder), app.state.library)
    async def restart():
        await reopened.start()
        try:
            assert reopened.store.job(job['id'])['status'] == 'paused'
        finally:
            await reopened.stop()
    asyncio.run(restart())
    with TestClient(app) as client:
        assert client.post('/api/jobs/delete', json={'ids': [job['id']]}).status_code == 200


async def test_queue_skips_paused_jobs_and_stopping_keeps_requested_pause(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    entered = asyncio.Event()
    async def waiting(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    await worker.start()
    try:
        job = (await worker.create(request))[0]
        worker.pause_many([job['id']])
        await asyncio.sleep(.4)
        assert store.job(job['id'])['status'] == 'paused'
        with patch('sillage.jobs.providers.translate', side_effect=waiting):
            worker.resume(job['id'])
            await asyncio.wait_for(entered.wait(), 5)
            worker.pause_many([job['id']])
            await worker.stop()
        assert store.job(job['id'])['status'] == 'paused'
    finally:
        if not worker.stopping:
            await worker.stop()


async def test_pause_retains_source_bound_fragments_before_missing_fragment_repair():
    paused, posts = False, []
    def handler(req):
        nonlocal paused
        cues = payload(req)['segments']
        posts.append([cue['id'] for cue in cues])
        if len(posts) == 1:
            answer = [{'id': 'a', 'text': ['wrong span count']}]
        else:
            paused = True
            answer = [{'id': cues[0]['id'], 'text': 'Bonjour'}]
        return httpx.Response(200, json=envelope(text=output(answer)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderPaused) as caught:
            await translate(config(retries=3), [{'id': 'a', 'text': 'Hello__SILLAGE_0000__world'}],
                            client=client, should_pause=lambda: paused)
    assert len(posts) == 2
    assert caught.value.translations == {}
    assert caught.value.fragment_retry_ids == ['a']
    assert list(caught.value.fragment_checkpoints) == ['a.s0000']
    assert caught.value.fragment_checkpoints['a.s0000']['text'] == 'Bonjour'
