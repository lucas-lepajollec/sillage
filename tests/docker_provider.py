"""Test-only deterministic HTTP endpoint used by docker_smoke.py."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        raw = json.dumps({"data": [{"id": "deterministic", "name": "Deterministic test model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        segments = json.loads(data["messages"][-1]["content"])["segments"]
        with open('/tmp/sillage-test-provider-requests.jsonl', 'a') as log:
            log.write(json.dumps({'model': data.get('model'), 'ids': [cue['id'] for cue in segments]}) + '\n')
        result = []
        for segment in segments:
            spans = segment['text'] if isinstance(segment['text'], list) else [segment['text']]
            if any('__SILLAGE_' in span for span in spans):
                raise AssertionError('Glyph-level effects must never reach the test provider')
            if data.get("model") == "partial-test" and segment["id"] == "e000002":
                continue
            if data.get('model') == 'fragment-test' and segment['id'] == 'e000001.s0002':
                continue
            translated = [span.replace("Hello", "Bonjour").replace("world", "monde").replace("Goodbye", "Au revoir").replace("Station", "Gare") for span in spans]
            text = translated if isinstance(segment['text'], list) else translated[0]
            if data.get('model') == 'fragment-test' and isinstance(text, list):
                text = ' '.join(text)  # Persistent array-flattening model.
            result.append({"id": segment["id"], "text": text})
        raw = json.dumps({"choices": [{"message": {"content": json.dumps({"translations": result})}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

HTTPServer(("127.0.0.1", 5777), Handler).serve_forever()
