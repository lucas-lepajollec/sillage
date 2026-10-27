"""Local SQLite state. Provider keys are encrypted with a separate mode-0600 key."""
from __future__ import annotations
import json
import hashlib
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def provider_fingerprint(config: dict) -> str:
    data = {k: v for k, v in config.items() if k not in {"api_key", "has_key", "id", "name"}}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        key_path = folder / "secret.key"
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as key:
                key.write(Fernet.generate_key())
        os.chmod(key_path, 0o600)
        self.cipher = Fernet(key_path.read_bytes())
        self.path = folder / "sillage.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS providers (id TEXT PRIMARY KEY, data TEXT NOT NULL, secret TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoints (job TEXT NOT NULL, id TEXT NOT NULL, text TEXT NOT NULL,
                    PRIMARY KEY(job,id));
                CREATE TABLE IF NOT EXISTS fragment_checkpoints (job TEXT NOT NULL, id TEXT NOT NULL,
                    source_hash TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(job,id));
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def providers(self, secrets: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,data,secret FROM providers ORDER BY rowid").fetchall()
        results = []
        for pid, data, secret in rows:
            item = json.loads(data) | {"id": pid, "has_key": bool(secret)}
            if secrets:
                item["api_key"] = self.cipher.decrypt(secret.encode()).decode() if secret else ""
            results.append(item)
        return results

    def provider(self, pid: str, secrets: bool = False) -> dict:
        item = next((p for p in self.providers(secrets) if p["id"] == pid), None)
        if item is None:
            raise ValueError("Provider introuvable.")
        return item

    def save_provider(self, data: dict) -> dict:
        item = dict(data)
        pid = item.pop("id", None) or uuid.uuid4().hex
        secret = item.pop("api_key", None)
        item.pop("has_key", None)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT data,secret FROM providers WHERE id=?", (pid,)).fetchone()
            previous_secret = ""
            if previous:
                previous_data = json.loads(previous[0])
                # Capture the known old configuration before an edit. Legacy jobs
                # only have a hash; do not guess what their translation settings were.
                previous_config = previous_data | {"id": pid, "api_key": self.cipher.decrypt(previous[1].encode()).decode() if previous[1] else ""}
                previous_hash = provider_fingerprint(previous_config)
                snapshot = self.seal_config(previous_config)
                for jid, raw in db.execute("SELECT id,data FROM jobs").fetchall():
                    job = json.loads(raw)
                    if job.get("provider_id") == pid and not job.get("provider_snapshot") and job.get("config_fingerprint") == previous_hash:
                        job["provider_snapshot"] = snapshot
                        db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), jid))
                if all(previous_data.get(key) == item.get(key) for key in ("kind", "base_url")):
                    previous_secret = previous[1]
            encrypted = self.cipher.encrypt(secret.encode()).decode() if secret else previous_secret
            db.execute("INSERT OR REPLACE INTO providers VALUES(?,?,?)", (pid, json.dumps(item), encrypted))
        return self.provider(pid)

    def seal_config(self, config: dict) -> str:
        # Snapshots include credentials, so encrypt the entire payload. They never
        # enter public job responses and survive profile edits/deletion safely.
        clean = {k: v for k, v in config.items() if k != "has_key"}
        return self.cipher.encrypt(json.dumps(clean).encode()).decode()

    def open_config(self, snapshot: str) -> dict:
        try:
            return json.loads(self.cipher.decrypt(snapshot.encode()))
        except (InvalidToken, ValueError, TypeError, AttributeError):
            raise ValueError("Configuration enregistrée illisible. Adaptez le traitement depuis Traductions.") from None

    def reconfigure_jobs(self, changes: dict[str, dict], restart: bool):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            records = {jid: json.loads(raw) for jid, raw in db.execute("SELECT id,data FROM jobs").fetchall()}
            paths = set()
            for jid in changes:
                job = records.get(jid)
                if not job or job["status"] not in {"queued", "error", "interrupted", "cancelled"} or job.get("sync_pending"):
                    raise ValueError("Adaptez uniquement des traitements en attente ou arrêtés.")
                if job["path"] in paths or any(other["id"] not in changes and other["path"] == job["path"]
                    and (other["status"] in {"queued", "extracting", "translating", "validating", "syncing", "writing"} or other.get("sync_pending")) for other in records.values()):
                    raise ValueError("Un autre traitement est déjà actif pour cet épisode.")
                paths.add(job["path"])
            for jid, patch in changes.items():
                if restart:
                    db.execute("DELETE FROM checkpoints WHERE job=?", (jid,))
                    db.execute("DELETE FROM fragment_checkpoints WHERE job=?", (jid,))
                db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(records[jid] | patch), jid))

    def delete_provider(self, pid: str):
        if any(j["provider_id"] == pid and (j["status"] in {"queued", "extracting", "translating", "validating", "syncing", "writing"} or j.get("sync_pending")) for j in self.jobs()):
            raise ValueError("Ce provider est utilisé par un traitement actif.")
        with self.connect() as db:
            db.execute("DELETE FROM providers WHERE id=?", (pid,))

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM jobs ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def job(self, jid: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise ValueError("Traduction introuvable.")
        return json.loads(row[0])

    def put_job(self, job: dict) -> dict:
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (job["id"], json.dumps(job)))
        return job

    def patch(self, jid: str, **changes) -> dict:
        # Read+write on one SQLite transaction prevents cancellation/progress lost updates.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise ValueError("Traduction introuvable.")
            data = json.loads(row[0]) | changes
            db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(data), jid))
        return data

    def checkpoint(self, jid: str, translations: dict[str,str], fragments: dict[str,dict] | None = None,
                   evict: list[str] | None = None):
        with self.connect() as db:
            db.executemany('DELETE FROM fragment_checkpoints WHERE job=? AND id=?', [(jid, key) for key in (evict or [])])
            db.executemany("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", [(jid, k, v) for k,v in translations.items()])
            db.executemany("INSERT OR REPLACE INTO fragment_checkpoints VALUES(?,?,?,?)",
                           [(jid, key, value['source_hash'], value['text']) for key, value in (fragments or {}).items()])

    def fragments(self, jid: str) -> dict[str,dict[str,str]]:
        with self.connect() as db:
            return {key: {'source_hash': source_hash, 'text': text} for key, source_hash, text in
                    db.execute('SELECT id,source_hash,text FROM fragment_checkpoints WHERE job=?', (jid,))}

    def delete_jobs(self, ids: list[str]):
        # Recheck under the same write transaction as deletion: a concurrent
        # resume must either win and block deletion, or find a missing job.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for jid in ids:
                row = db.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
                if not row:
                    raise ValueError("Une traduction n’existe plus. Actualisez l’historique.")
                if json.loads(row[0])["status"] not in {"completed", "review", "error", "cancelled", "interrupted"}:
                    raise ValueError("Annulez les traitements actifs avant de les supprimer.")
            db.executemany("DELETE FROM checkpoints WHERE job=?", [(jid,) for jid in ids])
            db.executemany("DELETE FROM fragment_checkpoints WHERE job=?", [(jid,) for jid in ids])
            db.executemany("DELETE FROM jobs WHERE id=?", [(jid,) for jid in ids])

    def translations(self, jid: str) -> dict[str,str]:
        with self.connect() as db:
            return dict(db.execute("SELECT id,text FROM checkpoints WHERE job=?", (jid,)).fetchall())
