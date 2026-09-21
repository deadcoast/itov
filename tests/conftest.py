from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def graph():
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "itov/preflight"},
        },
    }


@pytest.fixture
def registry():
    return {
        "LoadImage": {
            "input": {"required": {"image": [["example.png"]]}},
            "output": ["IMAGE", "MASK"],
            "output_node": False,
        },
        "SaveImage": {
            "input": {
                "required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]},
            },
            "output": [],
            "output_node": True,
        },
    }


@pytest.fixture
def http_server(registry):
    routes = {
        "/system_stats": (
            200,
            {
                "system": {"python_version": "fixture", "pytorch_version": "fixture"},
                "devices": [{"name": "fixture GPU", "type": "cuda"}],
            },
        ),
        "/object_info": (200, registry),
    }
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path))
            code, body = routes.get(self.path, (404, {"error": "missing"}))
            if callable(body):
                body = body()
            self.respond(code, body)

        def respond(self, code, body):
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            requests.append(("POST", self.path))
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            routes.setdefault("_posted", []).append(payload)
            code, body = routes.get("POST " + self.path, (405, {"error": "unsupported"}))
            if callable(body):
                body = body(payload)
            self.respond(code, body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", routes, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
