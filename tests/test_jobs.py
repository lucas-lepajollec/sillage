import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from sillage.jobs import Worker
from sillage.media import MediaLibrary
from sillage.providers import ProviderConfig
from sillage.storage import Store
from sillage.subtitles import SubtitleDocument


async def deterministic(config, segments, context, glossary=""):
    translations = {}
    for segment in segments:
        text = segment["text"]
        for source, target in {"Hello": "Bonjour", "world": "monde", "Goodbye": "Au revoir", "Station": "Gare"}.items():
            text = text.replace(source, target)
        translations[segment["id"]] = text
    return {"translations": translations, "usage": {"input_tokens": 10, "output_tokens": 10}, "warnings": []}


def environment(video, tmp_path, batch=1):
    store = Store(tmp_path / "config")
    config = ProviderConfig(kind="custom", name="Test provider", model="test-only", base_url="http://127.0.0.1:19999/v1",
                            source_language="en", target_language="fr", batch_size=batch, retries=0).model_dump()
    provider = store.save_provider(config)
    library = MediaLibrary([video.parent])
    worker = Worker(store, library)
    track = library.inspect(video)["tracks"][0]["id"]
    request = {"items": [{"path": str(video), "track_id": track}], "provider_id": provider["id"], "sync_mode": "preserve", "offset_ms": 0}
    return store, worker, request


@pytest.mark.parametrize("ass", [False, True])
async def test_real_pipeline_preserves_mkv_and_timestamps(media_factory, tmp_path, ass):
    video = media_factory(ass=ass)
    store, worker, request = environment(video, tmp_path)
    mkv_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic):
        await worker.process(job["id"])
    result = store.job(job["id"])
    assert result["status"] == "completed", result
    assert result["progress"] == 100
    assert result["done"] == result["total"] == 2
    assert "Bonjour" in Path(result["output"]).read_text()
    source = SubtitleDocument.load(result["source_file"])
    output = SubtitleDocument.load(result["output"])
    assert [(c["start"], c["end"]) for c in source.cues] == [(c["start"], c["end"]) for c in output.cues]
    assert "audio non vérifié" in result["timing_status"]
    assert hashlib.sha256(video.read_bytes()).hexdigest() == mkv_hash
    preview = worker.preview(job["id"])
    assert "Bonjour" in preview["cues"][0]["translated"]
    assert "__SILLAGE_" not in preview["cues"][0]["translated"]


async def test_missing_llm_segment_is_never_published(video, tmp_path):
    store, worker, request = environment(video, tmp_path, batch=2)
    job = (await worker.create(request))[0]
    async def missing(*args):
        return {"translations": {}, "warnings": [], "usage": {}}
    with patch("sillage.jobs.providers.translate", side_effect=missing), pytest.raises(ValueError, match="incomplète"):
        await worker.process(job["id"])
    assert not video.with_suffix(".fr.srt").exists()


async def test_interruption_resumes_without_retranslating_validated_batch(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    calls = []
    async def interrupted(config, segments, context, glossary):
        calls.append(segments[0]["id"])
        if len(calls) == 2:
            raise ValueError("Test interruption")
        return await deterministic(config, segments, context, glossary)
    with patch("sillage.jobs.providers.translate", side_effect=interrupted), pytest.raises(ValueError):
        await worker.process(job["id"])
    assert len(store.translations(job["id"])) == 1
    store.patch(job["id"], status="interrupted")
    reopened = Worker(Store(store.folder), worker.library)
    reopened.resume(job["id"])
    with patch("sillage.jobs.providers.translate", side_effect=deterministic) as provider:
        await reopened.process(job["id"])
        assert provider.call_count == 1
        assert provider.call_args.args[1][0]["id"] != calls[0]
    assert store.job(job["id"])["status"] == "completed"


async def test_cancel_between_batches_keeps_checkpoint(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    async def cancelling(*args):
        result = await deterministic(*args)
        worker.cancel(job["id"])
        return result
    with patch("sillage.jobs.providers.translate", side_effect=cancelling), pytest.raises(ValueError, match="annulé"):
        await worker.process(job["id"])
    assert len(store.translations(job["id"])) == 1
    assert not video.with_suffix(".fr.srt").exists()


async def test_restart_marks_inflight_interrupted(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.patch(job["id"], status="translating")
    await worker.start()
    try:
        assert store.job(job["id"])["status"] == "interrupted"
    finally:
        await worker.stop()


async def test_manual_offset_is_explicit_and_measurable(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    request |= {"sync_mode": "offset", "offset_ms": 100}
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic):
        await worker.process(job["id"])
    result = store.job(job["id"])
    assert result["applied_offset_ms"] == 100
    assert SubtitleDocument.load(result["output"]).cues[0]["start"] == 600
    assert "explicite" in result["timing_status"]


async def test_negative_or_out_of_video_offset_is_refused(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    request |= {"sync_mode": "offset", "offset_ms": -1000}
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic), pytest.raises(ValueError, match="Timings invalides"):
        await worker.process(job["id"])
    assert not video.with_suffix(".fr.srt").exists()


async def test_auto_sync_requires_acceptance_and_reject_keeps_source(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    request["sync_mode"] = "auto"
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic), patch("sillage.jobs.propose_sync", return_value={"offset_ms": 200, "confidence": 0.8, "warnings": []}):
        await worker.process(job["id"])
    assert store.job(job["id"])["sync_pending"]
    assert not video.with_suffix(".fr.srt").exists()
    assert worker.preview(job["id"])["cues"][0]["proposed_start"] == 700
    await worker.decide_sync(job["id"], False)
    assert SubtitleDocument.load(store.job(job["id"])["output"]).cues[0]["start"] == 500


async def test_auto_sync_acceptance_applies_proposed_offset(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    request["sync_mode"] = "auto"
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic), patch("sillage.jobs.propose_sync", return_value={"offset_ms": 200, "confidence": 0.8, "warnings": []}):
        await worker.process(job["id"])
    await worker.decide_sync(job["id"], True)
    assert SubtitleDocument.load(store.job(job["id"])["output"]).cues[0]["start"] == 700


async def test_uncertain_sync_can_only_keep_source(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    request["sync_mode"] = "auto"
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic), patch("sillage.jobs.propose_sync", side_effect=ValueError("incertaine")):
        await worker.process(job["id"])
    with pytest.raises(ValueError, match="incertaine"):
        await worker.decide_sync(job["id"], True)
    await worker.decide_sync(job["id"], False)
    assert store.job(job["id"])["status"] == "review"


async def test_existing_french_output_and_duplicate_jobs_refused(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    with pytest.raises(ValueError, match="actif"):
        await worker.create(request)
    worker.cancel(job["id"])
    output = video.with_suffix(".fr.srt")
    output.write_text("keep")
    with pytest.raises(ValueError, match="existe déjà"):
        await worker.create(request)
    assert output.read_text() == "keep"


async def test_changed_config_cannot_mix_checkpoints(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.save_provider(store.provider(job["provider_id"]) | {"model": "different"})
    with pytest.raises(ValueError, match="configuration"):
        await worker.process(job["id"])


async def test_protected_ass_events_produce_review_warning(media_factory, tmp_path):
    video = media_factory(ass=True)
    source = video.with_suffix(".en.ass")
    from conftest import ASS
    source.write_text(ASS + r"Dialogue: 0,0:00:04.60,0:00:05.50,Default,,0,0,0,,{\k30}Hello" + "\n")
    store, worker, request = environment(video, tmp_path)
    request["items"][0]["track_id"] = f"external:{source.name}"
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic):
        await worker.process(job["id"])
    result = store.job(job["id"])
    assert result["status"] == "review" and result["warnings"]
    assert r"{\k30}Hello" in Path(result["output"]).read_text()


async def test_queued_job_can_be_cancelled_without_processing(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    worker.cancel(job["id"])
    assert store.job(job["id"])["status"] == "cancelled"
    worker.resume(job["id"])
    assert store.job(job["id"])["status"] == "queued"


async def test_configured_batch_concurrency_is_bounded(video, tmp_path):
    import asyncio
    store, worker, request = environment(video, tmp_path)
    provider = store.provider(request["provider_id"])
    store.save_provider(provider | {"concurrency": 2})
    job = (await worker.create(request))[0]
    active, maximum = 0, 0
    async def simultaneous(*args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        result = await deterministic(*args)
        active -= 1
        return result
    with patch("sillage.jobs.providers.translate", side_effect=simultaneous):
        await worker.process(job["id"])
    assert maximum == 2
    assert store.job(job["id"])["status"] == "completed"


async def test_simultaneous_requests_reserve_episode_once(video, tmp_path):
    import asyncio
    store, worker, request = environment(video, tmp_path)
    results = await asyncio.gather(worker.create(request), worker.create(request), return_exceptions=True)
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len(store.jobs()) == 1


async def test_adaptive_feedback_changes_next_wave_and_survives_resume_and_next_episode(video, tmp_path):
    import json
    import shutil
    import httpx
    from sillage import providers
    from test_providers import envelope, output
    store, worker, request = environment(video, tmp_path, batch=20)
    profile = store.provider(request['provider_id'])
    store.save_provider(profile | {'retries': 1})
    source = video.with_suffix('.en.srt')
    text = ''.join(f'{i}\n00:00:00,{i*100:03} --> 00:00:00,{i*100+50:03}\nHello {i}\n\n' for i in range(1, 9))
    source.write_text(text)
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    calls, fail = [], True
    original_translate = providers.translate
    def handler(http_request):
        nonlocal fail
        batch = json.loads(json.loads(http_request.content)['messages'][1]['content'])['segments']
        calls.append([cue['id'] for cue in batch])
        good = not fail or batch[0]['id'] <= 'e000004'
        if len(batch) > 1 and batch[0]['id'] > 'e000004':
            good = False
        items = [{'id': cue['id'], 'text': cue['text'].replace('Hello', 'Bonjour')} for cue in batch] if good else []
        return httpx.Response(200, json=envelope(text=output(items)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def adapter(config, batch, context, glossary):
            return await original_translate(config, batch, context, glossary, client=client)
        with patch('sillage.jobs.providers.translate', side_effect=adapter), pytest.raises(providers.StructuredOutputError):
            await worker.process(job['id'])
        assert len(store.translations(job['id'])) == 4  # Failed descendants never checkpointed.
        assert store.job(job['id'])['adaptive_batch_size'] == 1
        assert store.job(job['id'])['usage']['total_tokens'] == 75
        store.patch(job['id'], status='error')
        fail = False
        calls.clear()
        reopened = Worker(Store(store.folder), worker.library)
        reopened.resume(job['id'])
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(job['id'])
        assert [len(batch) for batch in calls] == [1]*4
        assert all(batch[0] > 'e000004' for batch in calls)
        assert store.job(job['id'])['status'] == 'completed'
        second = video.with_name('Another episode.mkv')
        shutil.copyfile(video, second)
        second_source = second.with_suffix('.en.srt')
        second_source.write_text(text)
        next_request = request | {'items': [{'path': str(second), 'track_id': f'external:{second_source.name}'}]}
        next_job = (await reopened.create(next_request))[0]
        calls.clear()
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(next_job['id'])
        assert [len(batch) for batch in calls] == [1]*8
        # A different model must never inherit the previous model's measured ceiling.
        store.save_provider(store.provider(request['provider_id']) | {'model': 'different-model'})
        third = video.with_name('Third episode.mkv')
        shutil.copyfile(video, third)
        third_source = third.with_suffix('.en.srt')
        third_source.write_text(text)
        third_request = request | {'items': [{'path': str(third), 'track_id': f'external:{third_source.name}'}]}
        third_job = (await reopened.create(third_request))[0]
        calls.clear()
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(third_job['id'])
        assert len(calls[0]) == 4


async def test_zero_duration_external_ass_no_longer_blocks_real_pipeline(media_factory, tmp_path):
    from conftest import ASS
    video = media_factory(ass=True)
    source = video.with_suffix('.en.ass')
    line = 'Dialogue: 0,0:00:10.00,0:00:10.00,Default,,0,0,0,,Invisible source marker\n'
    source.write_text(ASS + line)
    before = source.read_bytes()
    store, worker, request = environment(video, tmp_path)
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    with patch('sillage.jobs.providers.translate', side_effect=deterministic):
        await worker.process(job['id'])
    result = store.job(job['id'])
    assert result['status'] == 'review' and any('Durée nulle' in warning for warning in result['warnings'])
    assert line in Path(result['output']).read_text()
    assert source.read_bytes() == before
    assert result['done'] == result['total'] == 2


async def test_recovered_size_is_used_by_next_wave_without_restarting(video, tmp_path):
    store, worker, request = environment(video, tmp_path, batch=20)
    source = video.with_suffix('.en.srt')
    source.write_text(''.join(f'{i}\n00:00:00,{i*100:03} --> 00:00:00,{i*100+50:03}\nHello {i}\n\n' for i in range(1, 9)))
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    sizes = []
    async def recovered(*args):
        sizes.append(len(args[1]))
        return (await deterministic(*args)) | {'recovered': len(args[1]) > 1, 'batch_size': 1}
    with patch('sillage.jobs.providers.translate', side_effect=recovered):
        await worker.process(job['id'])
    assert sizes == [4, 1, 1, 1, 1]
    assert store.job(job['id'])['adaptive_batch_size'] == 1


async def test_reversed_source_timings_are_reported_before_any_model_call(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    source = video.with_suffix('.en.srt')
    source.write_text('1\n00:00:03,000 --> 00:00:02,000\nHello\n')
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    with patch('sillage.jobs.providers.translate') as provider, pytest.raises(ValueError, match='piste source'):
        await worker.process(job['id'])
    provider.assert_not_called()
    assert not video.with_suffix('.fr.srt').exists()


async def test_user_cancellation_stops_inflight_recovery_and_queue_continues(video, tmp_path):
    import asyncio
    import shutil
    store, worker, request = environment(video, tmp_path)
    other = video.with_name('Next queued episode.mkv')
    shutil.copyfile(video, other)
    track = worker.library.inspect(other)['tracks'][0]['id']
    entered = asyncio.Event()
    calls = 0
    async def waiting(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await asyncio.Event().wait()
        return await deterministic(*args)
    with patch('sillage.jobs.providers.translate', side_effect=waiting):
        await worker.start()
        try:
            first = (await worker.create(request))[0]
            second = (await worker.create(request | {'items': [{'path': str(other), 'track_id': track}]}))[0]
            await asyncio.wait_for(entered.wait(), timeout=3)
            await asyncio.to_thread(worker.cancel, first['id'])
            for _ in range(300):
                if store.job(second['id'])['status'] == 'completed':
                    break
                await asyncio.sleep(.01)
            assert store.job(first['id'])['status'] == 'cancelled'
            assert store.translations(first['id']) == {}
            assert store.job(second['id'])['status'] == 'completed'
        finally:
            await worker.stop()
