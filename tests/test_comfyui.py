import io
from urllib.error import URLError

import pytest

from itov.comfyui import ComfyUIClient, ComfyUIError


def test_readonly_metadata_client(http_server):
    url, _routes, requests = http_server
    client = ComfyUIClient(url)
    assert client.system_stats()["devices"][0]["type"] == "cuda"
    assert "LoadImage" in client.object_info()
    assert requests == [("GET", "/system_stats"), ("GET", "/object_info")]


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {"error": "unavailable"}),
        (200, b"not JSON"),
        (200, []),
        (200, {}),
        (200, {"LoadImage": []}),
    ],
)
def test_registry_failures_are_actionable(http_server, status, body):
    url, routes, _requests = http_server
    routes["/object_info"] = status, body
    with pytest.raises(ComfyUIError, match="/object_info"):
        ComfyUIClient(url).object_info()


def test_no_redirects_are_followed(http_server):
    url, routes, requests = http_server
    routes["/object_info"] = 302, {}
    with pytest.raises(ComfyUIError, match="HTTP 302"):
        ComfyUIClient(url).object_info()
    assert requests == [("GET", "/object_info")]


@pytest.mark.parametrize("body", [{"system": {}}, {"system": [], "devices": []}])
def test_bad_system_stats(http_server, body):
    url, routes, _requests = http_server
    routes["/system_stats"] = 200, body
    with pytest.raises(ComfyUIError, match="system object and devices array"):
        ComfyUIClient(url).system_stats()


@pytest.mark.parametrize("exception", [URLError("connection refused"), TimeoutError("timed out")])
def test_network_errors_include_endpoint(monkeypatch, exception):
    client = ComfyUIClient("http://127.0.0.1:8188")

    def fail(*_args, **_kwargs):
        raise exception

    monkeypatch.setattr(client._opener, "open", fail)
    with pytest.raises(ComfyUIError, match="/system_stats"):
        client.system_stats()


def test_oversized_metadata_is_rejected(monkeypatch):
    monkeypatch.setattr("itov.comfyui.MAX_RESPONSE_BYTES", 8)
    client = ComfyUIClient("http://127.0.0.1:8188")
    monkeypatch.setattr(client._opener, "open", lambda *_a, **_k: io.BytesIO(b"0123456789"))
    with pytest.raises(ComfyUIError, match="metadata limit"):
        client.object_info()


def test_truncated_download_is_not_published(tmp_path, monkeypatch):
    client = ComfyUIClient("http://127.0.0.1:8188")

    class TruncatedResponse(io.BytesIO):
        headers = {"Content-Length": "100"}

    monkeypatch.setattr(client._opener, "open", lambda *_a, **_k: TruncatedResponse(b"partial"))
    destination = tmp_path / "artifact.png"
    with pytest.raises(ComfyUIError, match="incomplete artifact"):
        client.download_output(
            {"filename": "test.png", "subfolder": "", "type": "output"}, destination
        )
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
