"""ComfyUI metadata and single-job protocol access with no implicit retries."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from itov.config import validate_timeout, validate_url

MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class ComfyUIError(RuntimeError):
    """An endpoint was unreachable or returned invalid metadata."""

    def __init__(self, message: str, *, status_code: int | None = None, details: object = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        _reject_constant(value)
    return number


def parse_json(value: str | bytes) -> object:
    return json.loads(
        value,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


class ComfyUIClient:
    def __init__(self, url: str, *, timeout: float = 3.0):
        self.url = validate_url(url)
        self.timeout = validate_timeout(timeout)
        # A local diagnostic must not send local traffic through a system proxy.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _json(self, endpoint: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.url + endpoint, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeds the 32 MiB metadata limit")
            result = parse_json(content)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except HTTPError as error:
            details = None
            try:
                details = parse_json(error.read(65536))
            except (ValueError, OSError):
                pass
            finally:
                error.close()
            raise ComfyUIError(
                f"{endpoint}: HTTP {error.code}", status_code=error.code, details=details
            ) from error
        except (URLError, OSError, ValueError) as error:
            raise ComfyUIError(f"{endpoint}: {error}") from error

    def system_stats(self) -> dict:
        result = self._json("/system_stats")
        if not isinstance(result.get("system"), dict) or not isinstance(
            result.get("devices"), list
        ):
            raise ComfyUIError("/system_stats: expected system object and devices array")
        return result

    def object_info(self) -> dict:
        result = self._json("/object_info")
        if not result or any(not isinstance(value, dict) for value in result.values()):
            raise ComfyUIError("/object_info: expected a nonempty node registry")
        return result

    def submit(self, graph: dict, client_id: str) -> dict:
        """Submit exactly once. A transport failure can leave acceptance unknown."""
        result = self._json(
            "/prompt",
            {"prompt": graph, "client_id": client_id, "extra_data": {"itov_request_id": client_id}},
        )
        if not isinstance(result.get("prompt_id"), str) or not result["prompt_id"]:
            raise ComfyUIError("/prompt: missing prompt_id; submission acceptance is unknown")
        return result

    def history(self, prompt_id: str) -> dict | None:
        result = self._json("/history/" + quote(prompt_id, safe=""))
        if prompt_id not in result:
            return None
        record = result[prompt_id]
        if not isinstance(record, dict) or not isinstance(record.get("status"), dict):
            raise ComfyUIError("/history: invalid execution record")
        return record

    def queue(self) -> dict:
        result = self._json("/queue")
        if any(not isinstance(result.get(key), list) for key in ("queue_running", "queue_pending")):
            raise ComfyUIError("/queue: invalid queue metadata")
        return result

    def find_submission(
        self, request_id: str, graph: dict, *, prompt_id: str | None = None
    ) -> str | None:
        """Recover positive acceptance evidence; absence never authorizes a retry."""
        queue = self.queue()
        history = self._json("/history?max_items=200")
        if prompt_id:
            record = self.history(prompt_id)
            if record is not None:
                history[prompt_id] = record
        entries = [*queue["queue_running"], *queue["queue_pending"]]
        for key, record in history.items():
            if not isinstance(record, dict) or not isinstance(record.get("prompt"), list):
                raise ComfyUIError("/history: missing submission provenance")
            item = record["prompt"]
            if len(item) < 4 or item[1] != key:
                raise ComfyUIError("/history: inconsistent prompt identity")
            entries.append(item)
        matches = set()
        encoded = json.dumps(graph, sort_keys=True, allow_nan=False)
        for item in entries:
            if not isinstance(item, list) or len(item) < 4 or not isinstance(item[3], dict):
                raise ComfyUIError("Invalid queue/history submission provenance")
            if item[3].get("itov_request_id") != request_id:
                continue
            if (
                not isinstance(item[1], str)
                or not item[1]
                or json.dumps(item[2], sort_keys=True, allow_nan=False) != encoded
            ):
                raise ComfyUIError(
                    "Submission owner matches but workflow or prompt identity differs"
                )
            matches.add(item[1])
        if len(matches) > 1:
            raise ComfyUIError("Multiple prompts claim this request; preserve and inspect")
        match = next(iter(matches), None)
        if prompt_id and match != prompt_id:
            raise ComfyUIError("Supplied prompt ID has no matching server ownership evidence")
        return match

    def download_output(self, descriptor: dict, destination: Path) -> dict:
        """Download one exact /view descriptor; preserve any differing existing file."""
        if destination.is_symlink():
            raise ComfyUIError(f"Refusing a redirected artifact destination: {destination}")
        query = urlencode({key: descriptor[key] for key in ("filename", "subfolder", "type")})
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        size = 0
        digest = hashlib.sha256()
        try:
            with self._opener.open(self.url + "/view?" + query, timeout=self.timeout) as response:
                expected_size = response.headers.get("Content-Length")
                if expected_size is not None:
                    try:
                        expected_size = int(expected_size)
                    except ValueError as error:
                        raise ComfyUIError("/view: invalid Content-Length") from error
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=".itov-", suffix=".partial", delete=False
                ) as target:
                    temporary = Path(target.name)
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 512 * 1024 * 1024:
                            raise ComfyUIError("/view: artifact exceeds the 512 MiB download limit")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            if expected_size is not None and size != expected_size:
                raise ComfyUIError("/view: incomplete artifact response")
            if size == 0:
                raise ComfyUIError("/view: returned an empty artifact")
            try:
                # Same-directory hard link publishes atomically without replacing another file.
                os.link(temporary, destination)
            except FileExistsError:
                with destination.open("rb") as source:
                    existing = hashlib.file_digest(source, "sha256").hexdigest()
                if existing != digest.hexdigest():
                    raise ComfyUIError(
                        f"Output already exists with different bytes: {destination}"
                    ) from None
            return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest()}
        except HTTPError as error:
            error.close()
            raise ComfyUIError(f"/view: HTTP {error.code}", status_code=error.code) from error
        except (OSError, URLError) as error:
            raise ComfyUIError(f"/view: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
