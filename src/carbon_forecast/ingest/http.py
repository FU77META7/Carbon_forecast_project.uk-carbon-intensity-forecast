"""Minimal JSON-over-HTTP client: polite rate limit, retries, exponential backoff.

Standard library only; this is all the HTTP the project needs.
"""

import http.client
import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

USER_AGENT = "uk-carbon-intensity-forecast/0.1 (research project)"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    pass


class HttpClient:
    def __init__(
        self,
        min_interval_s: float = 0.5,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 120.0,
        timeout_s: float = 60.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.timeout_s = timeout_s
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self._last_request = float("-inf")
        self.requests_made = 0

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, safe=',')}"
        err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            retry_after = None
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
                )
                with self._opener(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:  # subclass of URLError, so caught first
                if e.code not in RETRYABLE_STATUS:
                    body = e.read()[:300].decode(errors="replace")
                    raise HttpError(f"HTTP {e.code} for {url}: {body}") from e
                retry_after = e.headers.get("Retry-After") if e.headers else None
                err = e
            except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
                err = e
            if attempt < self.max_retries:
                delay = self._backoff(attempt, retry_after)
                log.warning("attempt %d failed (%s); retrying in %.1fs", attempt + 1, err, delay)
                self._sleep(delay)
        raise HttpError(f"giving up on {url} after {self.max_retries + 1} attempts: {err}")

    def _wait_turn(self) -> None:
        wait = self._last_request + self.min_interval_s - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()
        self.requests_made += 1

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), self.backoff_cap_s)
        delay = self.backoff_base_s * 2**attempt
        return min(delay + random.uniform(0, delay / 2), self.backoff_cap_s)
