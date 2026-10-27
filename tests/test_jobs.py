import hashlib
from pathlib import Path
from subprocess import TimeoutExpired
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
    assert job["source_track"]["id"] == request["items"][0]["track_id"]
    assert preview["source_track"]["id"] == job["track_id"]
    assert preview["source_track_origin"] == "recorded"
    assert preview["stats"] == {"events": 2, "translatable": 2, "preserved": 0}
    assert "Bonjour" in preview["cues"][0]["translated"]
    assert "__SILLAGE_" not in preview["cues"][0]["translated"]


async def test_old_job_preview_labels_current_metadata_without_changing_checkpoints(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    job.pop("source_track")
    store.put_job(job)
    work = store.folder / "work" / job["id"]
    work.mkdir(parents=True)
    source, _ = worker.library.extract(video, job["track_id"], work)
    store.patch(job["id"], source_file=str(source))
    store.checkpoint(job["id"], {"e000001": "Bonjour !"})
    # Recorded source stays available even when the container no longer exists.
    current = worker.preview(job["id"])
    assert current["source_track_origin"] == "current"
    assert current["source_track"]["id"] == job["track_id"]
    for unavailable in [FileNotFoundError(), TimeoutExpired("ffprobe", 90)]:
        with patch.object(worker.library, "inspect", side_effect=unavailable):
            preview = worker.preview(job["id"])
        assert preview["source_track"] is None
        assert preview["source_track_origin"] == "unavailable"
        assert preview["cues"][0]["translated"] == "Bonjour !"
    assert store.translations(job["id"]) == {"e000001": "Bonjour !"}


async def test_recorded_source_metadata_is_stable_when_container_labels_change(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic):
        await worker.process(job["id"])
    snapshot = store.job(job["id"])["source_track"]
    with patch.object(worker.library, "inspect", side_effect=AssertionError("No live inspection for recorded metadata")):
        preview = worker.preview(job["id"])
    assert preview["source_track"] == snapshot
    assert preview["source_track_origin"] == "recorded"


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


async def test_profile_model_edit_does_not_change_a_queued_jobs_model_or_export_language(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.save_provider(store.provider(job["provider_id"]) | {"model": "different", "target_language": "de"})
    models = []
    async def adapter(config, *args):
        models.append((config["model"], config["target_language"]))
        return await deterministic(config, *args)
    with patch("sillage.jobs.providers.translate", side_effect=adapter):
        await worker.process(job["id"])
    assert models == [("test-only", "fr"), ("test-only", "fr")]
    assert store.job(job["id"])["output"].endswith(".fr.srt")


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
        assert len(store.translations(job['id'])) == 4  # Earlier valid cues survive the failing wave.
        assert store.job(job['id'])['adaptive_batch_size'] == 4
        assert store.job(job['id'])['usage']['total_tokens'] == 75
        store.patch(job['id'], status='error')
        fail = False
        calls.clear()
        reopened = Worker(Store(store.folder), worker.library)
        reopened.resume(job['id'])
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(job['id'])
        assert [len(batch) for batch in calls] == [4, 2, 1, 1, 2, 1, 1]
        assert all(batch[0] > 'e000004' for batch in calls)
        assert store.job(job['id'])['status'] == 'review'
        assert any('raisonnement' in w for w in store.job(job['id'])['warnings'])
        second = video.with_name('Another episode.mkv')
        shutil.copyfile(video, second)
        second_source = second.with_suffix('.en.srt')
        second_source.write_text(text)
        next_request = request | {'items': [{'path': str(second), 'track_id': f'external:{second_source.name}'}]}
        next_job = (await reopened.create(next_request))[0]
        calls.clear()
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(next_job['id'])
        assert [len(batch) for batch in calls] == [4, 4, 2, 1, 1, 2, 1, 1]
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
    assert store.job(job['id'])['adaptive_batch_size'] == 2


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


async def test_reasoning_warning_survives_resume_after_all_cues_were_checkpointed(video, tmp_path):
    from sillage.reasoning import MANDATORY
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    async def translate_with_warning(*args):
        result = await deterministic(*args)
        return result | {'warnings': [MANDATORY]}
    with patch('sillage.jobs.providers.translate', side_effect=translate_with_warning), patch.object(worker, 'finalize', side_effect=ValueError('interrupted before publication')):
        with pytest.raises(ValueError, match='interrupted before publication'):
            await worker.process(job['id'])
    store.patch(job['id'], status='error')
    worker.resume(job['id'])
    with patch('sillage.jobs.providers.translate', side_effect=AssertionError('Validated cues must not be billed again')):
        await worker.process(job['id'])
    result = store.job(job['id'])
    assert result['status'] == 'review' and result['output']
    assert result['warnings'].count(MANDATORY) == 1


async def test_delete_completed_job_keeps_media_and_exports(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    original = video.read_bytes()
    job = (await worker.create(request))[0]
    with patch("sillage.jobs.providers.translate", side_effect=deterministic):
        await worker.process(job["id"])
    finished = store.job(job["id"])
    exported = Path(finished["output"])
    content = exported.read_bytes()
    assert store.translations(job["id"])
    result = await worker.delete([job["id"]])
    assert result == {"deleted": [job["id"]], "warnings": []}
    assert not store.jobs() and not store.translations(job["id"])
    assert not (store.folder / "work" / job["id"]).exists()
    assert video.read_bytes() == original and exported.read_bytes() == content
    assert store.providers()


async def test_history_delete_is_atomic_when_one_job_active_or_missing(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    first = (await worker.create(request))[0]
    store.patch(first["id"], status="error")
    second = first | {"id": "a" * 32, "status": "queued"}
    store.put_job(second)
    store.checkpoint(first["id"], {"e000001": "Bonjour"})
    work = store.folder / "work" / first["id"]
    work.mkdir(parents=True)
    (work / "source.srt").write_text("preserved")
    for invalid in [second["id"], "b" * 32]:
        with pytest.raises(ValueError):
            await worker.delete([first["id"], invalid])
        assert len(store.jobs()) == 2 and store.translations(first["id"])
        assert (work / "source.srt").read_text() == "preserved"
    store.patch(first["id"], status="cancelled")
    worker.active = first["id"]
    with pytest.raises(ValueError, match="annulation"):
        await worker.delete([first["id"]])
    worker.active = None
    worker.inflight[first["id"]] = []
    with pytest.raises(ValueError, match="annulation"):
        await worker.delete([first["id"]])
    assert len(store.jobs()) == 2


@pytest.mark.parametrize("ids", [[], ["../media"], ["a" * 32] * 2, ["x" * 32], ["a" * 32] * 501])
async def test_history_delete_rejects_invalid_ids_before_work_access(video, tmp_path, ids):
    store, worker, _ = environment(video, tmp_path)
    with pytest.raises(ValueError, match="identifiants"):
        await worker.delete(ids)
    assert store.jobs() == []


async def test_history_delete_never_follows_work_symlinks_or_stored_paths(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    store.patch(job["id"], status="error", source_file=str(outside / "keep.txt"), output=str(outside / "keep.txt"))
    root = store.folder / "work"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        await worker.delete([job["id"]])
    assert store.job(job["id"])
    root.unlink()
    root.mkdir()
    (root / job["id"]).symlink_to(outside, target_is_directory=True)
    assert (await worker.delete([job["id"]]))["warnings"] == []
    assert not (root / job["id"]).is_symlink()
    assert (outside / "keep.txt").read_text() == "keep"


async def test_history_cleanup_failure_is_reported_after_atomic_sql_deletion(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.patch(job["id"], status="error")
    store.checkpoint(job["id"], {"e000001": "Bonjour"})
    work = store.folder / "work" / job["id"]
    work.mkdir(parents=True)
    with patch("sillage.jobs.shutil.rmtree", side_effect=PermissionError):
        result = await worker.delete([job["id"]])
    assert result["deleted"] == [job["id"]] and result["warnings"]
    assert not store.jobs() and not store.translations(job["id"])
    assert work.is_dir() and video.is_file()


async def test_history_delete_waits_for_sync_decision(video, tmp_path):
    import asyncio
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.patch(job["id"], status="review", sync_pending=True, sync_proposal={"offset_ms": 0})
    entered, release = asyncio.Event(), asyncio.Event()
    async def finalize(*args):
        entered.set()
        await release.wait()
        store.patch(job["id"], status="completed", sync_pending=False)
    with patch.object(worker, "finalize", side_effect=finalize):
        decision = asyncio.create_task(worker.decide_sync(job["id"], True))
        await asyncio.wait_for(entered.wait(), timeout=2)
        deletion = asyncio.create_task(worker.delete([job["id"]]))
        await asyncio.sleep(0)
        assert not deletion.done() and store.job(job["id"])
        release.set()
        await asyncio.wait_for(decision, timeout=2)
        assert (await asyncio.wait_for(deletion, timeout=2))["deleted"] == [job["id"]]


async def test_history_cleanup_keeps_descriptor_owned_after_request_cancellation(video, tmp_path):
    import asyncio
    import os
    import threading
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.patch(job["id"], status="error")
    work = store.folder / "work" / job["id"]
    work.mkdir(parents=True)
    (work / "source.srt").write_text("fixture")
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = worker._clean_work
    owned = []
    def cleanup(ids, fd):
        owned.append(fd)
        started.set()
        try:
            assert release.wait(timeout=2)
            os.fstat(fd)  # The HTTP coroutine must not close/reuse this FD.
            return original(ids, fd)
        finally:
            finished.set()
    with patch.object(worker, "_clean_work", side_effect=cleanup):
        deletion = asyncio.create_task(worker.delete([job["id"]]))
        assert await asyncio.to_thread(started.wait, 2)
        deletion.cancel()
        with pytest.raises(asyncio.CancelledError):
            await deletion
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert not work.exists() and not store.jobs()
    with pytest.raises(OSError):
        os.fstat(owned[0])


async def test_runtime_limits_apply_to_next_wave_without_losing_checkpoint(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    seen = []
    async def adapter(config, *args):
        seen.append((config['concurrency'], config['timeout'], config['retries']))
        store.save_provider(store.provider(job['provider_id']) | {'concurrency': 3, 'timeout': 240, 'retries': 4})
        return await deterministic(config, *args)
    with patch('sillage.jobs.providers.translate', side_effect=adapter):
        await worker.process(job['id'])
    assert seen == [(1, 120, 0), (3, 240, 4)]
    assert len(store.translations(job['id'])) == 2
    assert store.job(job['id'])['status'] == 'completed'


async def test_partial_failed_batch_and_completed_concurrent_sibling_are_saved(video, tmp_path):
    import asyncio
    from sillage.providers import StructuredOutputError
    store, worker, request = environment(video, tmp_path)
    store.save_provider(store.provider(request['provider_id']) | {'concurrency': 2})
    job = (await worker.create(request))[0]
    async def adapter(config, segments, *args):
        if segments[0]['id'] == 'e000001':
            error = StructuredOutputError('Synthetic bad cue', 1, {}, 1)
            raise error
        await asyncio.sleep(0.02)
        return await deterministic(config, segments, *args)
    with patch('sillage.jobs.providers.translate', side_effect=adapter), pytest.raises(StructuredOutputError):
        await worker.process(job['id'])
    assert set(store.translations(job['id'])) == {'e000002'}
    assert store.job(job['id'])['done'] == 1


async def test_reconfigure_keeps_checkpoints_and_can_recover_unknown_legacy_settings(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    # Reproduce a pre-snapshot job edited on an older application version.
    legacy = store.job(job['id'])
    legacy.pop('provider_snapshot')
    legacy['config_fingerprint'] = 'unknown-old-config'
    legacy['status'] = 'error'
    store.put_job(legacy)
    store.checkpoint(job['id'], {'e000001': 'Bonjour monde.'})
    with pytest.raises(ValueError, match='Adapter les paramètres'):
        worker.job_config(legacy)
    worker.reconfigure([job['id']], job['provider_id'])
    assert store.translations(job['id']) == {'e000001': 'Bonjour monde.'}
    assert store.job(job['id'])['status'] == 'queued'
    assert any('cohérence' in warning for warning in store.job(job['id'])['warnings'])
    seen = []
    async def adapter(config, batch, *args):
        seen.extend(cue['id'] for cue in batch)
        return await deterministic(config, batch, *args)
    with patch('sillage.jobs.providers.translate', side_effect=adapter):
        await worker.process(job['id'])
    assert seen == ['e000002']
    assert store.job(job['id'])['done'] == 2


async def test_profile_edits_freeze_matching_legacy_jobs_before_changing_meaning(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    legacy = dict(job)
    legacy.pop('provider_snapshot')
    store.put_job(legacy)
    store.save_provider(store.provider(job['provider_id']) | {'model': 'different'})
    assert worker.job_config(store.job(job['id']))['model'] == 'test-only'


async def test_language_change_requires_explicit_restart_and_never_deletes_other_jobs(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    store.checkpoint(job['id'], {'e000001': 'Bonjour.'})
    store.patch(job['id'], status='error')
    store.save_provider(store.provider(job['provider_id']) | {'target_language': 'de'})
    with pytest.raises(ValueError, match='langues'):
        worker.reconfigure([job['id']], job['provider_id'])
    assert store.translations(job['id'])
    worker.reconfigure([job['id']], job['provider_id'], restart=True)
    assert store.translations(job['id']) == {}
    assert store.job(job['id'])['done'] == 0
    assert worker.job_config(store.job(job['id']))['target_language'] == 'de'


async def test_reconfigure_group_is_atomic_and_refuses_actual_active_or_exported_jobs(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    job = (await worker.create(request))[0]
    before = store.job(job['id'])
    with pytest.raises(ValueError):
        worker.reconfigure([job['id'], 'missing'], job['provider_id'], restart=True)
    assert store.job(job['id']) == before
    worker.active = job['id']
    with pytest.raises(ValueError, match='Annulez'):
        worker.reconfigure([job['id']], job['provider_id'])
    worker.active = None
    video.with_suffix('.fr.srt').write_text('keep me')
    with pytest.raises(ValueError, match='existe déjà'):
        worker.reconfigure([job['id']], job['provider_id'], restart=True)
    assert store.job(job['id']) == before


async def test_valid_single_cues_grow_back_and_do_not_poison_the_next_episode(video, tmp_path):
    import shutil
    store, worker, request = environment(video, tmp_path, batch=20)
    source = video.with_suffix('.en.srt')
    source.write_text(''.join(f'{i}\n00:00:01,000 --> 00:00:02,000\nHello {i}\n\n' for i in range(1, 33)))
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    store.patch(job['id'], adaptive_batch_size=1, batch_policy={'version': 2, 'size': 1})
    sizes = []
    async def adapter(config, batch, *args):
        sizes.append(len(batch))
        return await deterministic(config, batch, *args)
    with patch('sillage.jobs.providers.translate', side_effect=adapter):
        await worker.process(job['id'])
    assert sizes[:3] == [1, 1, 1]
    assert max(sizes) > 4
    assert len(store.translations(job['id'])) == 32
    second = video.with_name('next.mkv')
    shutil.copyfile(video, second)
    second_source = second.with_suffix('.en.srt')
    shutil.copyfile(source, second_source)
    next_job = (await worker.create(request | {'items': [{'path': str(second), 'track_id': f'external:{second_source.name}'}]}))[0]
    sizes.clear()
    with patch('sillage.jobs.providers.translate', side_effect=adapter):
        await worker.process(next_job['id'])
    assert sizes[0] == 4


async def test_real_partial_json_failure_checkpoints_valid_cues_and_resume_requests_only_missing(video, tmp_path):
    import json
    import httpx
    from sillage import providers
    from test_providers import envelope, output
    store, worker, request = environment(video, tmp_path, batch=4)
    store.save_provider(store.provider(request['provider_id']) | {'retries': 1})
    job = (await worker.create(request))[0]
    broken = True
    calls = []
    def handler(http_request):
        batch = json.loads(json.loads(http_request.content)['messages'][1]['content'])['segments']
        calls.append([cue['id'] for cue in batch])
        valid = [cue for cue in batch if not broken or cue['id'] == 'e000001']
        return httpx.Response(200, json=envelope(text=output([cue | {'text': cue['text'].replace('Hello', 'Bonjour').replace('Goodbye', 'Au revoir')} for cue in valid])))
    original = providers.translate
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def adapter(config, *args):
            return await original(config, *args, client=client)
        with patch('sillage.jobs.providers.translate', side_effect=adapter), pytest.raises(providers.StructuredOutputError):
            await worker.process(job['id'])
        assert set(store.translations(job['id'])) == {'e000001'}
        assert store.job(job['id'])['done'] == 1
        store.patch(job['id'], status='error')
        store.save_provider(store.provider(job['provider_id']) | {'concurrency': 4, 'timeout': 180})
        broken = False
        calls.clear()
        reopened = Worker(Store(store.folder), worker.library)
        reopened.resume(job['id'])
        with patch('sillage.jobs.providers.translate', side_effect=adapter):
            await reopened.process(job['id'])
        assert calls == [['e000002']]
        assert store.job(job['id'])['done'] == store.job(job['id'])['total'] == 2


async def test_snapshot_key_never_follows_an_edited_endpoint_and_same_endpoint_rotation_is_used(video, tmp_path):
    store, worker, request = environment(video, tmp_path)
    initial = store.provider(request['provider_id'])
    store.save_provider(initial | {'api_key': 'TEST-ONLY-original-key'})
    job = (await worker.create(request))[0]
    store.save_provider(initial | {'api_key': 'TEST-ONLY-rotated-key'})
    assert worker.job_config(job)['api_key'] == 'TEST-ONLY-rotated-key'
    store.save_provider(initial | {'base_url': 'http://127.0.0.1:19998/v1', 'api_key': 'TEST-ONLY-other-endpoint'})
    effective = worker.job_config(job)
    assert effective['base_url'] == initial['base_url']
    assert effective['api_key'] == 'TEST-ONLY-original-key'


async def test_resume_old_all_checkpointed_ass_keeps_gradient_and_late_comment_without_new_paid_calls(video, tmp_path):
    from conftest import ASS
    from sillage.subtitles import _protect
    store, worker, request = environment(video, tmp_path)
    gradient = r'{\fad(120,120)\blur2}' + ''.join(r'{*\3c&H%06X&}' % (0x123400 + index) + char for index, char in enumerate('Fictional closing card'))
    gradient_line = 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,' + gradient + '\n'
    comment = 'Comment: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Fictional editor note\n'
    source = video.with_suffix('.en.ass')
    source.write_text(ASS + gradient_line + comment)
    before = source.read_bytes()
    request['items'][0]['track_id'] = f'external:{source.name}'
    job = (await worker.create(request))[0]
    doc = SubtitleDocument.load(source)
    valid = (await deterministic({}, doc.segments, []))['translations']
    legacy = valid | {doc.cues[-2]['id']: _protect(gradient)[0]}
    store.checkpoint(job['id'], legacy)
    store.patch(job['id'], status='error', done=len(legacy), total=len(legacy))
    reopened = Worker(Store(store.folder), worker.library)
    reopened.resume(job['id'])
    with patch('sillage.jobs.providers.translate') as provider:
        await reopened.process(job['id'])
    provider.assert_not_called()
    result = store.job(job['id'])
    assert result['status'] == 'review'
    assert result['done'] == result['total'] == len(valid)
    assert store.translations(job['id']) == legacy  # Never delete the old stored work.
    output = Path(result['output']).read_text()
    assert gradient_line in output and comment in output and 'Bonjour' in output
    assert source.read_bytes() == before
    preview = reopened.preview(job['id'])
    assert 'translated' not in preview['cues'][-2]
    assert any('lettre par lettre' in warning for warning in preview['warnings'])
    assert any('checkpoints archivés' in warning for warning in result['warnings'])
    assert preview['stats']['translatable'] == len(valid)
