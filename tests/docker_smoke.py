"""Exercise canonical Compose with a selected image and disposable media only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import time
import uuid
import httpx

from serve_e2e import create_library


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def main():
    name = "sillage-smoke-" + uuid.uuid4().hex[:8]
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="sillage-docker-smoke-") as work:
        work = Path(work)
        media = create_library(work / "media")
        original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in media.rglob("*.mkv")}
        config = work / "config"
        config.mkdir()
        shutil.copyfile(root / "tests" / "docker_provider.py", work / "test-provider.py")
        # Resolve the shipped Compose first; change only fixture inputs, image
        # and the ephemeral loopback port. Runtime options keep their real values.
        resolved = json.loads(docker("compose", "-f", str(root / "docker-compose.yml"), "config", "--format", "json"))
        service = resolved["services"]["sillage"]
        service["image"] = os.environ.get("SILLAGE_TEST_IMAGE", "sillage:local")
        service["environment"] |= {"PUID": str(os.getuid()), "PGID": str(os.getgid())}
        service["ports"] = [{"target": 2511, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}]
        service["volumes"] = [f"{media}:/media:rw,Z", f"{config}:/config:rw,Z", f"{work / 'test-provider.py'}:/test-provider.py:ro,Z"]
        resolved.pop("name", None)
        for network in resolved.get("networks", {}).values():
            network.pop("name", None)
        compose = work / "compose.json"
        compose.write_text(json.dumps(resolved))
        compose_args = ["compose", "-p", name, "-f", str(compose)]
        try:
            docker(*compose_args, "up", "-d", "--pull", "never")
            container_id = docker(*compose_args, "ps", "-q", "sillage")
            name = container_id
            port = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["2511/tcp"][0]["HostPort"]
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=20, trust_env=False) as client:
                for _ in range(80):
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.25)
                else:
                    raise AssertionError("Container did not become ready: " + docker("logs", name))
                health = client.get("/api/health").json()
                assert all(health["tools"].values()), health
                assert "Sillage" in client.get("/").text
                worker_uid = docker("exec", name, "python", "-c", "from pathlib import Path; print(next(p.joinpath('status').read_text().split('Uid:')[1].split()[0] for p in Path('/proc').iterdir() if p.name.isdigit() and p.name != '1' and p.joinpath('cmdline').exists() and b'sillage.app:create_app' in p.joinpath('cmdline').read_bytes().split(bytes([0]))))")
                assert worker_uid == str(os.getuid()), worker_uid
                docker("exec", "-d", name, "sh", "-c", "exec python /test-provider.py >/tmp/sillage-test-provider.log 2>&1")
                response = client.post("/api/providers", json={"kind": "custom", "name": "Docker test only", "model": "deterministic", "base_url": "http://127.0.0.1:5777/v1", "target_language": "fr", "source_language": "en"})
                response.raise_for_status()
                provider = response.json()
                for _ in range(50):
                    catalogue = client.post("/api/providers/models", json={"id": provider["id"], "kind": "custom", "base_url": provider["base_url"]})
                    if catalogue.status_code == 200:
                        break
                    time.sleep(0.2)
                else:
                    fixture_log = docker("exec", name, "cat", "/tmp/sillage-test-provider.log")
                    raise AssertionError(f"Test-only provider did not become ready: {catalogue.text}; {fixture_log[:1000]}")
                catalogue.raise_for_status()
                assert catalogue.json() == {"models": [{"id": "deterministic", "name": "Deterministic test model"}], "truncated": False}
                connection = client.post(f"/api/providers/{provider['id']}/test")
                assert connection.status_code == 200, connection.text
                scan = client.post("/api/scan", json={"path": "/media", "recursive": True}).json()
                assert len(scan["episodes"]) == 3, scan
                selected = scan["episodes"][:2]
                request = {"provider_id": provider["id"], "items": [{"path": e["path"], "track_id": e["tracks"][0]["id"]} for e in selected]}
                response = client.post("/api/jobs", json=request)
                response.raise_for_status()
                ids = {j["id"] for j in response.json()}
                for _ in range(100):
                    jobs = [j for j in client.get("/api/jobs").json() if j["id"] in ids]
                    if all(j["status"] in {"completed", "review"} for j in jobs):
                        break
                    if any(j["status"] == "error" for j in jobs):
                        raise AssertionError(jobs)
                    time.sleep(0.2)
                assert all(j["progress"] == 100 and j["output"] for j in jobs), jobs
                for job in jobs:
                    assert job["status"] == "review" and any("raisonnement" in w for w in job["warnings"])
                    assert b"Bonjour" in client.get(f"/api/jobs/{job['id']}/download").content
                    preview = client.get(f"/api/jobs/{job['id']}/preview").json()
                    assert preview["cues"][0]["start"] == 500
                previous = client.get("/api/jobs").json()
                inspected = client.post(f"/api/jobs/{jobs[0]['id']}/reanalyze", json={})
                inspected.raise_for_status()
                assert inspected.json()["path"] == jobs[0]["path"]
                assert client.get("/api/jobs").json() == previous
                deletion = client.post("/api/jobs/delete", json={"ids": [jobs[0]["id"]]})
                deletion.raise_for_status()
                assert deletion.json() == {"deleted": [jobs[0]["id"]], "warnings": []}
                assert len(client.get("/api/jobs").json()) == 1
                docker("exec", name, "python", "-c", "from pathlib import Path; import sys; assert Path(sys.argv[1]).is_file()", jobs[0]["output"])
                # Pause real HTTP calls, save both in-flight replies, then resume
                # only the remaining generated cues through the public API.
                pause_video = next(media.rglob("*.mkv")).with_name("Pause fixture.mkv")
                shutil.copyfile(next(media.rglob("*.mkv")), pause_video)
                original[pause_video.name] = hashlib.sha256(pause_video.read_bytes()).hexdigest()
                pause_source = pause_video.with_suffix('.en.srt')
                pause_source.write_text(''.join(f'{i}\n00:00:00,500 --> 00:00:02,000\nHello world!\n\n' for i in range(1,5)))
                pause_hash = hashlib.sha256(pause_source.read_bytes()).hexdigest()
                pause_profile = client.post('/api/providers', json=provider | {'id': None, 'name': 'Pause test', 'model': 'pause-test', 'batch_size': 1, 'concurrency': 2}).json()
                pause_path = '/media/' + pause_video.relative_to(media).as_posix()
                response = client.post('/api/jobs', json={'provider_id': pause_profile['id'], 'items': [{'path': pause_path, 'track_id': 'external:' + pause_source.name}]})
                response.raise_for_status()
                pause_id = response.json()[0]['id']
                for _ in range(100):
                    state = next(j for j in client.get('/api/jobs').json() if j['id'] == pause_id)
                    if state['status'] == 'translating':
                        break
                    time.sleep(.02)
                for _ in range(30):
                    started = int(docker('exec', name, 'python', '-c', "import json; from pathlib import Path; print(sum(r['model'] == 'pause-test' for r in map(json.loads, Path('/tmp/sillage-test-provider-requests.jsonl').read_text().splitlines())))"))
                    if started:
                        break
                    time.sleep(.02)
                assert started
                response = client.post(f'/api/jobs/{pause_id}/pause', json={})
                response.raise_for_status()
                assert response.json()['status'] == 'pausing'
                for _ in range(100):
                    state = next(j for j in client.get('/api/jobs').json() if j['id'] == pause_id)
                    if state['status'] == 'paused':
                        break
                    time.sleep(.05)
                assert state['status'] == 'paused' and state['done'] == 2 and not state['output'], state
                before_resume = state['done']
                response = client.post(f'/api/jobs/{pause_id}/resume', json={})
                response.raise_for_status()
                for _ in range(100):
                    state = next(j for j in client.get('/api/jobs').json() if j['id'] == pause_id)
                    if state['status'] in {'completed', 'review', 'error'}:
                        break
                    time.sleep(.1)
                assert state['done'] == state['total'] == 4 and state['output'], state
                assert hashlib.sha256(pause_source.read_bytes()).hexdigest() == pause_hash
                calls = json.loads(docker('exec', name, 'python', '-c', "import json; from pathlib import Path; print(json.dumps([r['ids'] for r in map(json.loads, Path('/tmp/sillage-test-provider-requests.jsonl').read_text().splitlines()) if r['model'] == 'pause-test']))"))
                assert sorted(cue for batch in calls for cue in batch) == [f'e{i:06}' for i in range(1,5)], (before_resume, calls)
                # Real partial JSON failure, profile edit and in-place adoption.
                # Generated copy only: no operator media or provider is involved.
                recovery_source = next(media.rglob("*.mkv"))
                recovery_video = recovery_source.with_name("Recovery fixture.mkv")
                shutil.copyfile(recovery_source, recovery_video)
                original[recovery_video.name] = hashlib.sha256(recovery_video.read_bytes()).hexdigest()
                # Old fansub failure: per-letter typography and a late editor
                # comment must stay exact and must never reach the provider.
                from conftest import ASS
                gradient = ''.join(r'{*\3c&H%06X&}' % (0x123400 + i) + char for i, char in enumerate('Fictional closing card'))
                glyph_line = 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,' + gradient + '\n'
                comment = 'Comment: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Fictional editor note\n'
                sidecar = recovery_video.with_suffix('.en.ass')
                frame_lines = ''.join(f'Dialogue: 0,0:00:01.{i*4:02},0:00:01.{i*4+4:02},Sign,,0,0,0,,{{\\pos({100+i},120)\\blur1}}Station\n' for i in range(20))
                sidecar.write_text(ASS + glyph_line + comment + frame_lines)
                sidecar_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()
                broken = client.post("/api/providers", json=provider | {"id": None, "model": "fragment-test", "retries": 1, "batch_size": 4}).json()
                path = "/media/" + recovery_video.relative_to(media).as_posix()
                job_response = client.post("/api/jobs", json={"provider_id": broken["id"], "items": [{"path": path, "track_id": "external:" + sidecar.name}]})
                job_response.raise_for_status()
                recovery_id = job_response.json()[0]["id"]
                for _ in range(100):
                    recovery_job = next(j for j in client.get("/api/jobs").json() if j["id"] == recovery_id)
                    if recovery_job["status"] == "error":
                        break
                    time.sleep(0.2)
                assert recovery_job["status"] == "error" and recovery_job["done"] > 0, recovery_job
                assert recovery_job["done"] < recovery_job["total"]
                assert recovery_job['source_stats']['frame_animation'] == 20
                assert recovery_job['total'] == 2
                assert recovery_job['diagnostics']['fragment_fallback'] == 1
                assert 'fragment_retry_ids' not in recovery_job and 'fragment_checkpoints' not in recovery_job
                before_calls = int(docker('exec', name, 'python', '-c', "from pathlib import Path; print(len(Path('/tmp/sillage-test-provider-requests.jsonl').read_text().splitlines()))"))
                edited = client.post("/api/providers", json=broken | {"model": "deterministic", "concurrency": 2, "timeout": 180})
                edited.raise_for_status()
                assert next(j for j in client.get("/api/jobs").json() if j["id"] == recovery_id)["translation_profile"]["model"] == "fragment-test"
                adopted = client.post("/api/jobs/reconfigure", json={"ids": [recovery_id], "provider_id": broken["id"]})
                adopted.raise_for_status()
                assert "provider_snapshot" not in adopted.text
                for _ in range(100):
                    recovered_job = next(j for j in client.get("/api/jobs").json() if j["id"] == recovery_id)
                    if recovered_job["status"] in {"completed", "review", "error"}:
                        break
                    time.sleep(0.2)
                assert recovered_job["status"] == "review" and recovered_job["done"] == recovered_job["total"], recovered_job
                assert recovered_job["translation_profile"]["model"] == "deterministic"
                remaining_calls = json.loads(docker('exec', name, 'python', '-c',
                    "import json,sys; from pathlib import Path; print(json.dumps([json.loads(line) for line in Path('/tmp/sillage-test-provider-requests.jsonl').read_text().splitlines()][int(sys.argv[1]):]))", str(before_calls)))
                assert remaining_calls == [{'model': 'deterministic', 'ids': ['e000001.s0002']}], remaining_calls
                recovered_content = client.get(f"/api/jobs/{recovery_id}/download").text
                assert 'Bonjour' in recovered_content and glyph_line in recovered_content and comment in recovered_content and frame_lines in recovered_content
                assert recovered_job['total'] == 2  # Only normal dialogue is translated.
                assert any('lettre par lettre' in warning for warning in recovered_job['warnings'])
                assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == sidecar_hash
                assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in media.rglob("*.mkv")} == original
                # Exercise Docker's declared healthcheck, not only the host HTTP route.
                assert docker("exec", name, "python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:2511/api/health').status == 200") == ""
                docker("exec", name, "python", "-c", "from sillage.sync import _estimate; import ffsubsync, webrtcvad, numpy")
                print("Docker smoke passed: compiled UI, model discovery, all tools, non-root UID, real MKV ASS/SRT pipeline, read-only reanalysis, history cleanup preserving exports, cooperative HTTP pause/resume, persistent array failures/partial fragment checkpoints/one-missing-span recovery, preserved frame/glyph effects and late comments, source hashes, downloads and healthcheck.")
        finally:
            subprocess.run(["docker", *compose_args, "down", "--remove-orphans"], capture_output=True)

if __name__ == "__main__":
    main()
