import io
import json
import urllib.error

import pytest

from carbon_forecast.ingest.http import HttpClient, HttpError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(b"{}"))


class Opener:
    """Replays a script of exceptions / payloads and records requested URLs."""

    def __init__(self, script):
        self.script = list(script)
        self.urls = []

    def __call__(self, req, timeout):
        self.urls.append(req.full_url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(json.dumps(item).encode())


def _client(opener, sleeps, **kw):
    return HttpClient(min_interval_s=0, opener=opener, sleep=sleeps.append, **kw)


def test_retries_transient_errors_then_succeeds():
    opener = Opener([_http_error(503), urllib.error.URLError("reset"), {"ok": 1}])
    sleeps = []
    assert _client(opener, sleeps).get_json("http://x") == {"ok": 1}
    assert len(opener.urls) == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]  # exponential backoff


def test_honours_retry_after_on_429():
    opener = Opener([_http_error(429, {"Retry-After": "7"}), {"ok": 1}])
    sleeps = []
    _client(opener, sleeps).get_json("http://x")
    assert sleeps == [7.0]


def test_client_errors_are_not_retried():
    opener = Opener([_http_error(400), {"ok": 1}])
    with pytest.raises(HttpError, match="HTTP 400"):
        _client(opener, []).get_json("http://x")
    assert len(opener.urls) == 1


def test_gives_up_after_max_retries():
    opener = Opener([_http_error(502)] * 3)
    with pytest.raises(HttpError, match="after 3 attempts"):
        _client(opener, [], max_retries=2).get_json("http://x")


def test_rate_limit_spaces_requests():
    now = [100.0]
    sleeps = []
    client = HttpClient(
        min_interval_s=2.0,
        opener=Opener([{"a": 1}, {"b": 2}]),
        sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
        clock=lambda: now[0],
    )
    client.get_json("http://x")
    now[0] += 0.5
    client.get_json("http://x")
    assert sleeps == [1.5]


def test_params_are_encoded_with_literal_commas():
    opener = Opener([{"ok": 1}])
    _client(opener, []).get_json("http://x/api", {"hourly": "a,b", "lat": 51.5})
    assert opener.urls == ["http://x/api?hourly=a,b&lat=51.5"]


def test_real_network_is_blocked_in_tests():
    client = HttpClient(min_interval_s=0, max_retries=0, sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="network access is disabled"):
        client.get_json("https://api.carbonintensity.org.uk/intensity")
