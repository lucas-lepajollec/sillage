import asyncio
import hashlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import create_burned_video
from sillage.app import create_app
from sillage.media import MediaLibrary
from sillage.ocr import OcrOptions, OcrService, command, geometry, observe, parse_tsv, srt_text
from sillage.storage import Store
from sillage.subtitles import SubtitleDocument
from test_jobs import deterministic, environment


@pytest.fixture
def burned(tmp_path):
    return create_burned_video(tmp_path / 'media')


@pytest.fixture
def ocr(burned, tmp_path):
    return OcrService(Store(tmp_path / 'config'), MediaLibrary([burned.parent]))


def test_ocr_options_are_bounded_and_geometry_not_filter_input():
    for options in [{'top': 90, 'bottom': 80}, {'left': 85, 'right': 90}, {'fps': 100}, {'threshold': 0}, {'mode': 'movie=/private'}, {'top': float('nan')}]:
        with pytest.raises(ValidationError):
            OcrOptions(**options)
    with pytest.raises(ValueError, match='Dimensions'):
        geometry({'video_width': 100000, 'video_height': 200}, OcrOptions())
    _, w, h = geometry({'video_width': 7680, 'video_height': 4320}, OcrOptions())
    assert w <= 1280 and h <= 720


def test_tsv_rejects_weak_and_invalid_words_and_preserves_lines():
    header = b'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tconf\ttext\n'
    raw = header + b'5\t1\t1\t1\t1\t1\t95\tHello\n5\t1\t1\t1\t1\t2\t90\tworld!\n5\t1\t1\t1\t2\t1\t90\tAgain.\n'
    assert parse_tsv(raw, 65)[0] == 'Hello world!\nAgain.'
    assert parse_tsv(raw.replace(b'95', b'0').replace(b'90', b'0'), 65)[0] == ''
    assert parse_tsv(raw.replace(b'95', b'nan').replace(b'90', b'inf'), 65)[0] == ''


def test_grouping_requires_stability_separates_gaps_and_never_injects_markup():
    state = {'cues': [], 'active': None}
    for text, at in [('Noise', 0), ('', 250), ('Hello <world>', 500), ('Hello <world>', 750), ('', 1000), ('Hello <world>', 1250), ('Hello <world>', 1500), ('', 1750)]:
        observe(state, text, 90, at, at+250)
    assert [(c['start'], c['end']) for c in state['cues']] == [(500, 1000), (1250, 1750)]
    assert '&lt;world&gt;' in srt_text(state['cues'])
    assert len(SubtitleDocument(srt_text(state['cues']), 'srt').cues) == 2


async def test_actual_burned_ocr_review_publish_and_translation(ocr, burned, tmp_path):
    original = hashlib.sha256(burned.read_bytes()).hexdigest()
    assert ocr.library.inspect(burned)['tracks'] == []
    preview = await ocr.snapshot(str(burned), OcrOptions(), 1)
    assert preview['image'].startswith('data:image/png;base64,') and 'Hello world' in preview['text']
    task = (await ocr.prepare([str(burned)], OcrOptions()))[0]
    await ocr.run(task['id'])
    result = ocr.store.ocr_task(task['id'])
    assert result['status'] == 'review', result
    assert [c['text'] for c in result['cues']] == ['Hello world!', 'Goodbye world!']
    assert [(c['start'], c['end']) for c in result['cues']] == [(500, 2000), (2500, 4500)]
    assert not list(burned.parent.glob('*.srt')) and not ocr.store.jobs()
    public = ocr.public(result, result=True)
    assert 'fingerprint' not in public and 'cues' not in public and 'Hello world!' in public['srt']
    published = await ocr.publish(task['id'], public['srt'])
    track = next(t for t in published['episode']['tracks'] if t['id'] == published['track_id'])
    assert track['ocr'] and track['language'] == 'en'
    store, worker, request = environment(burned, tmp_path / 'translation')
    request['items'][0]['track_id'] = published['track_id']
    job = (await worker.create(request))[0]
    with patch('sillage.jobs.providers.translate', side_effect=deterministic):
        await worker.process(job['id'])
    final = store.job(job['id'])
    assert final['status'] == 'review' and any('OCR' in warning for warning in final['warnings'])
    assert 'Bonjour monde!' in burned.with_suffix('.fr.srt').read_text()
    assert hashlib.sha256(burned.read_bytes()).hexdigest() == original
    with pytest.raises(ValueError):
        await ocr.publish(task['id'], public['srt'])


async def test_pause_reopen_resume_only_remaining_frames_and_cancel_keeps_queue(ocr, burned):
    task = (await ocr.prepare([str(burned)], OcrOptions()))[0]
    real = ocr.recognize
    async def pause_after_frame(*args):
        result = await real(*args)
        if result[0]:
            await ocr.action(task['id'], 'pause')
        return result
    with patch.object(ocr, 'recognize', side_effect=pause_after_frame):
        await ocr.run(task['id'])
    saved = ocr.store.ocr_task(task['id'])
    assert saved['status'] == 'paused' and 0 < saved['index'] < saved['total']
    assert saved['active']['text'] == 'Hello world!' and saved['active']['samples'] == 1
    reopened = OcrService(Store(ocr.store.folder), ocr.library)
    await reopened.action(task['id'], 'resume')
    await reopened.run(task['id'])
    final = reopened.store.ocr_task(task['id'])
    assert final['status'] == 'review' and len(final['cues']) == 2
    other = create_burned_video(burned.parent / 'other')
    queued = (await reopened.prepare([str(other)], OcrOptions()))[0]
    entered = asyncio.Event()
    async def slow(*args):
        entered.set()
        await asyncio.sleep(60)
    with patch.object(reopened, 'recognize', side_effect=slow):
        running = asyncio.create_task(reopened.run(queued['id']))
        await entered.wait()
        await reopened.action(queued['id'], 'cancel')
        await asyncio.wait_for(running, 5)
    assert reopened.store.ocr_task(queued['id'])['status'] == 'cancelled'


async def test_blank_video_fails_without_publishing_and_source_change_is_refused(ocr, burned):
    blank = create_burned_video(burned.parent / 'blank', blank=True)
    task = (await ocr.prepare([str(blank)], OcrOptions()))[0]
    await ocr.run(task['id'])
    assert ocr.store.ocr_task(task['id'])['status'] == 'error'
    assert not list(blank.parent.glob('*.srt'))
    changed = (await ocr.prepare([str(burned)], OcrOptions()))[0]
    burned.touch()
    await ocr.run(changed['id'])
    assert 'changé' in ocr.store.ocr_task(changed['id'])['error']


async def test_group_creation_is_atomic_and_media_confinement_applies(ocr, burned, tmp_path):
    outside = create_burned_video(tmp_path / 'outside')
    for paths in [[str(burned), str(outside)], [str(burned), str(burned)]]:
        with pytest.raises(ValueError):
            await ocr.prepare(paths, OcrOptions())
        assert ocr.store.ocr_tasks() == []
    with pytest.raises(ValueError):
        await ocr.snapshot(str(outside), OcrOptions(), 1)
    with pytest.raises(ValueError):
        await ocr.snapshot(str(burned), OcrOptions(), 100)


async def test_review_validation_and_exclusive_source_output(ocr, burned):
    task = (await ocr.prepare([str(burned)], OcrOptions()))[0]
    with pytest.raises(ValueError, match='Terminez'):
        await ocr.publish(task['id'], 'bad')
    await ocr.run(task['id'])
    for content in ['', 'invalid', '1\n00:00:00,000 --> 00:00:10,000\nToo late\n']:
        with pytest.raises(ValueError):
            await ocr.publish(task['id'], content)
    sidecar = burned.with_suffix('.en.ocr.srt')
    sidecar.write_text('preserved')
    with pytest.raises(ValueError, match='existe'):
        await ocr.publish(task['id'], ocr.public(ocr.store.ocr_task(task['id']), result=True)['srt'])
    assert sidecar.read_text() == 'preserved'
    await ocr.action(task['id'], 'delete')
    assert sidecar.read_text() == 'preserved' and not ocr.store.ocr_tasks()


async def test_subprocess_output_is_bounded_and_errors_sanitized():
    import sys
    with pytest.raises(ValueError, match='volumineuse'):
        await command([sys.executable, '-c', 'print("x" * 10000)'], limit=100)
    with pytest.raises(ValueError) as error:
        await command([sys.executable, '-c', 'import sys; print("private subtitle", file=sys.stderr); sys.exit(1)'])
    assert 'private subtitle' not in str(error.value)
    with pytest.raises(ValueError, match='Délai'):
        await asyncio.wait_for(command([sys.executable, '-c', 'import time; time.sleep(60)'], timeout=1), 4)


async def test_worker_queue_survives_active_ocr_cancellation_and_recovers_restart(ocr, burned):
    from sillage.jobs import Worker
    other = create_burned_video(burned.parent / 'next')
    tasks = await ocr.prepare([str(burned), str(other)], OcrOptions())
    worker = Worker(ocr.store, ocr.library)
    entered = asyncio.Event()
    real = worker.ocr.recognize
    async def recognize(*args):
        if worker.ocr.active == tasks[0]['id']:
            entered.set()
            await asyncio.sleep(60)
        return await real(*args)
    with patch.object(worker.ocr, 'recognize', side_effect=recognize):
        await worker.start()
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await worker.ocr.action(tasks[0]['id'], 'cancel')
            async def done():
                while ocr.store.ocr_task(tasks[1]['id'])['status'] not in {'review', 'error'}:
                    await asyncio.sleep(.05)
            await asyncio.wait_for(done(), 10)
            assert ocr.store.ocr_task(tasks[1]['id'])['status'] == 'review'
        finally:
            await worker.stop()
    assert ocr.store.ocr_task(tasks[0]['id'])['status'] == 'cancelled'
    ocr.store.ocr_patch(tasks[0]['id'], status='running')
    ocr.recover()
    assert ocr.store.ocr_task(tasks[0]['id'])['status'] == 'interrupted'


async def test_source_change_before_publish_refuses_and_exact_write_intent_recovers(ocr, burned):
    task = (await ocr.prepare([str(burned)], OcrOptions()))[0]
    await ocr.run(task['id'])
    result = ocr.public(ocr.store.ocr_task(task['id']), result=True)['srt']
    output = burned.with_suffix('.en.ocr.srt')
    digest = hashlib.sha256(result.encode()).hexdigest()
    output.write_text(result)
    with pytest.raises(ValueError, match='existe'):
        await ocr.publish(task['id'], result)
    ocr.store.ocr_patch(task['id'], write_hash=digest)
    published = await ocr.publish(task['id'], result)
    assert published['track_id'] == 'external:' + output.name and output.read_text() == result
    ocr.store.ocr_patch(task['id'], status='review')
    burned.touch()
    with pytest.raises(ValueError, match='changé'):
        await ocr.publish(task['id'], result)


def test_ocr_api_guards_review_and_lists_no_private_state(burned, tmp_path):
    import json
    app = create_app(tmp_path / 'config', [burned.parent], run_worker=False)
    with TestClient(app) as client:
        response = client.post('/api/ocr/tasks', json={'paths': [str(burned)]})
        assert response.status_code == 200
        task = response.json()[0]
        assert 'fingerprint' not in task and 'cues' not in task
        assert client.post(f"/api/ocr/tasks/{task['id']}/publish", json={'content': 'bad', 'reviewed': False}).status_code == 400
        assert client.post('/api/ocr/snapshot', content=json.dumps({'path': str(burned), 'at': float('inf')}), headers={'Content-Type': 'application/json'}).status_code == 422
        assert client.post(f"/api/ocr/tasks/{task['id']}/delete", json={}).status_code == 400
        assert client.post(f"/api/ocr/tasks/{task['id']}/pause", json={}).json()['status'] == 'paused'
        assert len(client.get('/api/ocr/tasks').json()) == 1
