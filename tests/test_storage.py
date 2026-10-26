import json
import stat
import pytest
from sillage.storage import Store


def test_secrets_are_encrypted_and_redacted(tmp_path):
    store = Store(tmp_path / "config")
    result = store.save_provider({"name": "Test", "model": "local", "api_key": "TEST-ONLY-private-fixture"})
    assert result["has_key"] and "api_key" not in result
    assert b"TEST-ONLY-private-fixture" not in store.path.read_bytes()
    assert "TEST-ONLY-private-fixture" not in json.dumps(store.providers())
    assert store.provider(result["id"], True)["api_key"] == "TEST-ONLY-private-fixture"
    assert stat.S_IMODE((store.folder / "secret.key").stat().st_mode) == 0o600
    assert stat.S_IMODE(store.folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    store.save_provider(result | {"name": "Edited", "api_key": ""})
    assert store.provider(result["id"], True)["api_key"] == "TEST-ONLY-private-fixture"


def test_checkpoints_survive_reopening(tmp_path):
    store = Store(tmp_path)
    store.checkpoint("job", {"e1": "Bonjour"})
    reopened = Store(tmp_path)
    assert reopened.translations("job") == {"e1": "Bonjour"}


def test_patch_preserves_other_fields(tmp_path):
    store = Store(tmp_path)
    store.put_job({"id": "job", "status": "queued", "progress": 0})
    store.patch("job", progress=30)
    store.patch("job", cancel_requested=True)
    assert store.job("job")["progress"] == 30
    assert store.job("job")["cancel_requested"]


def test_provider_in_use_cannot_be_deleted(tmp_path):
    store = Store(tmp_path)
    provider = store.save_provider({"name": "Test"})
    store.put_job({"id": "job", "provider_id": provider["id"], "status": "translating"})
    with pytest.raises(ValueError):
        store.delete_provider(provider["id"])
    assert store.provider(provider["id"])
