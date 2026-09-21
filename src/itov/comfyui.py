"""Read-only access to the documented ComfyUI metadata endpoints."""

from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from itov.config import validate_timeout, validate_url

MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class ComfyUIError(RuntimeError):
    """An endpoint was unreachable or returned invalid metadata."""


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

    def _get(self, endpoint: str) -> dict:
        request = Request(self.url + endpoint, headers={"Accept": "application/json"})
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
            error.close()
            raise ComfyUIError(f"{endpoint}: HTTP {error.code}") from error
        except (URLError, OSError, ValueError) as error:
            raise ComfyUIError(f"{endpoint}: {error}") from error

    def system_stats(self) -> dict:
        result = self._get("/system_stats")
        if not isinstance(result.get("system"), dict) or not isinstance(
            result.get("devices"), list
        ):
            raise ComfyUIError("/system_stats: expected system object and devices array")
        return result

    def object_info(self) -> dict:
        result = self._get("/object_info")
        if not result or any(not isinstance(value, dict) for value in result.values()):
            raise ComfyUIError("/object_info: expected a nonempty node registry")
        return result
