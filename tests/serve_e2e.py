"""Test-only real API fixture. Never imported by the production application.

Creates tiny MKVs and a deterministic HTTP provider, then runs Sillage against
that disposable library. Nothing is mounted from the user's media collection.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ASS, SRT  # noqa: E402
from sillage.app import create_app  # noqa: E402


class TestProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = json.dumps({"data": [{"id": "sillage-test-only", "name": "Modèle de test"},
                                   {"id": "sillage-alternate-test-only", "name": "Autre modèle de test"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        request = json.loads(payload["messages"][-1]["content"])
        results = []
        for segment in request["segments"]:
            text = segment["text"]
            for source, target in {"Hello": "Bonjour", "world": "monde", "Goodbye": "Au revoir", "Station": "Gare"}.items():
                text = text.replace(source, target)
            results.append({"id": segment["id"], "text": text})
        body = {"choices": [{"message": {"content": json.dumps({"translations": results}, ensure_ascii=False)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def create_library(root: Path):
    season = root / "Les voyageurs" / "Saison 01"
    season.mkdir(parents=True)
    for number, ass in [(1, True), (2, False), (3, True)]:
        subtitle = season / ("source.ass" if ass else "source.srt")
        subtitle.write_text(ASS if ass else SRT, encoding="utf-8")
        output = season / f"Les voyageurs — S01E0{number}.mkv"
        args = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=64x36:rate=2:duration=6",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-i", str(subtitle),
                "-map", "0:v", "-map", "1:a", "-map", "2:0", "-t", "6", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-c:s", "copy",
                "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English · Full dialogue", str(output)]
        subprocess.run(args, check=True, capture_output=True)
        subtitle.unlink()
        if number == 3:
            output.with_suffix(".fr.ass").write_text(ASS.replace("Hello", "Bonjour").replace("Goodbye", "Au revoir").replace("Station", "Gare"))
    return root


if __name__ == "__main__":
    work = Path(tempfile.mkdtemp(prefix="sillage-e2e-"))
    port = int(os.environ.get("E2E_PORT", "5776"))
    provider_port = int(os.environ.get("E2E_PROVIDER_PORT", "5777"))
    provider = ThreadingHTTPServer(("127.0.0.1", provider_port), TestProvider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    library = create_library(work / "Médiathèque de test")
    os.environ["FRONTEND_DIST"] = str(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    os.environ.pop("ACCESS_KEY", None)
    app = create_app(work / "config", [library])
    print(f"Test fixture ready: http://127.0.0.1:{port}; provider http://127.0.0.1:{provider_port}/v1", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    finally:
        provider.shutdown()
        if os.environ.get("E2E_KEEP_DATA") != "1":
            shutil.rmtree(work)
