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
        service["ports"] = [{"target": 5775, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}]
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
            port = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["5775/tcp"][0]["HostPort"]
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
                docker("exec", "-d", name, "python", "/test-provider.py")
                time.sleep(0.2)
                response = client.post("/api/providers", json={"kind": "custom", "name": "Docker test only", "model": "deterministic", "base_url": "http://127.0.0.1:5777/v1", "target_language": "fr", "source_language": "en"})
                response.raise_for_status()
                provider = response.json()
                assert client.post(f"/api/providers/{provider['id']}/test").status_code == 200
                catalogue = client.post("/api/providers/models", json={"id": provider["id"], "kind": "custom", "base_url": provider["base_url"]})
                catalogue.raise_for_status()
                assert catalogue.json() == {"models": [{"id": "deterministic", "name": "Deterministic test model"}], "truncated": False}
                scan = client.post("/api/scan", json={"path": "/media", "recursive": True}).json()
                assert len(scan["episodes"]) == 3, scan
                selected = scan["episodes"][:2]
                request = {"provider_id": provider["id"], "items": [{"path": e["path"], "track_id": e["tracks"][0]["id"]} for e in selected]}
                response = client.post("/api/jobs", json=request)
                response.raise_for_status()
                ids = {j["id"] for j in response.json()}
                for _ in range(100):
                    jobs = [j for j in client.get("/api/jobs").json() if j["id"] in ids]
                    if all(j["status"] == "completed" for j in jobs):
                        break
                    if any(j["status"] == "error" for j in jobs):
                        raise AssertionError(jobs)
                    time.sleep(0.2)
                assert all(j["progress"] == 100 and j["output"] for j in jobs), jobs
                for job in jobs:
                    assert b"Bonjour" in client.get(f"/api/jobs/{job['id']}/download").content
                    preview = client.get(f"/api/jobs/{job['id']}/preview").json()
                    assert preview["cues"][0]["start"] == 500
                assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in media.rglob("*.mkv")} == original
                # Exercise Docker's declared healthcheck, not only the host HTTP route.
                assert docker("exec", name, "python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:5775/api/health').status == 200") == ""
                docker("exec", name, "python", "-c", "from sillage.sync import _estimate; import ffsubsync, webrtcvad, numpy")
                print("Docker smoke passed: compiled UI, model discovery, all tools, non-root UID, real MKV ASS/SRT pipeline, no source mutation, downloads and healthcheck.")
        finally:
            subprocess.run(["docker", *compose_args, "down", "--remove-orphans"], capture_output=True)

if __name__ == "__main__":
    main()
