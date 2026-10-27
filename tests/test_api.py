from fastapi.testclient import TestClient
from sillage.app import create_app


def test_api_health_browse_scan_preview_and_no_side_effect(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/config").json() == {"auth_required": False}
        assert client.get("/api/browse").json()["path"] == str(video.parent)
        scan = client.post("/api/scan", json={"path": str(video.parent), "recursive": True}).json()
        episode = scan["episodes"][0]
        preview = client.post("/api/preview", json={"path": str(video), "track_id": episode["tracks"][0]["id"]})
        assert preview.status_code == 200
        assert "Hello world" in preview.json()["cues"][0]["text"]
        assert "audio non vérifié" in preview.json()["timing_status"]
        assert preview.json()["source_track"]["id"] == episode["tracks"][0]["id"]
        assert preview.json()["stats"] == {"events": 2, "translatable": 2, "preserved": 0}
        assert not video.with_suffix(".fr.srt").exists()


def test_external_track_preview_counts_protected_events_without_provider(video, tmp_path):
    from conftest import ASS
    sidecar = video.with_suffix(".en.ass")
    sidecar.write_text(ASS.replace(",0,0,0,,", ",0,0,0,custom,", 1))
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    with TestClient(app) as client:
        response = client.post("/api/preview", json={"path": str(video), "track_id": f"external:{sidecar.name}"})
        assert response.status_code == 200
        data = response.json()
        assert data["source_track"]["external"]
        assert "path" not in data["source_track"]
        assert data["stats"] == {"events": 2, "translatable": 1, "preserved": 1}
        assert len(data["warnings"]) == 1
        assert not app.state.store.jobs()


def test_auth_and_origin_host_guards(video, tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESS_KEY", "TEST-ONLY-access-key")
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/config").json()["auth_required"]
        assert client.get("/api/providers").status_code == 401
        assert client.get("/api/providers", headers={"X-Access-Key": "wrong"}).status_code == 401
        assert client.get("/api/providers", headers={"X-Access-Key": "TEST-ONLY-access-key"}).status_code == 200
        assert client.post("/api/scan", json={}, headers={"Origin": "https://evil.example", "X-Access-Key": "TEST-ONLY-access-key"}).status_code == 403
        assert client.get("/api/config", headers={"Host": "attacker.example"}).status_code == 400


def test_provider_secret_never_returned_even_for_invalid_request(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    secret = "TEST-ONLY-synthetic-key-value"
    with TestClient(app) as client:
        valid = {"kind": "custom", "model": "test", "base_url": "http://127.0.0.1:19999/v1", "api_key": secret}
        response = client.post("/api/providers", json=valid)
        assert response.status_code == 200
        assert secret not in response.text
        assert response.json()["has_key"]
        assert secret not in client.get("/api/providers").text
        invalid = valid | {"base_url": "https://endpoint.example?api_key=" + secret}
        response = client.post("/api/providers", json=invalid)
        assert response.status_code == 422
        assert secret not in response.text
        assert secret not in client.post("/api/providers", json=valid | {"temperature": secret}).text
        assert secret not in app.state.store.path.read_bytes().decode("utf-8", errors="ignore")


def test_paths_are_validated_at_all_entry_points(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    with TestClient(app) as client:
        for method, url, params in [("get", "/api/browse", {"path": str(outside)}),
                                    ("post", "/api/scan", {"path": str(outside)}),
                                    ("post", "/api/preview", {"path": str(outside), "track_id": "embedded:2"})]:
            response = getattr(client, method)(url, **({"params": params} if method == "get" else {"json": params}))
            assert response.status_code == 400
        provider = client.post("/api/providers", json={"kind": "custom", "model": "test", "base_url": "http://127.0.0.1:19999/v1"}).json()
        request = {"provider_id": provider["id"], "items": [{"path": str(outside), "track_id": "embedded:2"}]}
        assert client.post("/api/jobs", json=request).status_code == 400
        assert not app.state.store.jobs()


def test_download_only_published_safe_output(video, tmp_path):
    app = create_app(tmp_path / "config", [video.parent], run_worker=False)
    app.state.store.put_job({"id": "test", "path": str(video), "output": None})
    with TestClient(app) as client:
        assert client.get("/api/jobs/test/download").status_code == 404
        outside = tmp_path / "outside.srt"
        outside.write_text("private fixture")
        app.state.store.patch("test", output=str(outside))
        assert client.get("/api/jobs/test/download").status_code == 400


def test_unknown_api_route_does_not_serve_spa(video, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Sillage fixture</h1>")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    with TestClient(create_app(tmp_path / "config", [video.parent], run_worker=False)) as client:
        assert client.get("/settings").status_code == 200
        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/").headers["x-content-type-options"] == "nosniff"
