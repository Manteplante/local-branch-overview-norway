"""A deliberately slow HTTP client: one request at a time, human-like pauses and breaks."""

import logging
import random
import time
from collections.abc import Callable
from importlib.metadata import version

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    f"local-branch-overview/{version('local-branch-overview')} "
    "(+https://github.com/Manteplante/local-branch-overview)"
)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class PoliteClient:
    """Fetches pages slowly.

    Before every request it waits a random `delay` (seconds). After every `break_every`
    requests (redrawn after each break) it takes a longer `break_length` "coffee break".
    Failed requests (429/5xx/connection errors) are retried with growing backoff, and a
    server's `Retry-After` is respected.
    """

    def __init__(
        self,
        *,
        delay: tuple[float, float] = (5, 15),
        break_every: tuple[int, int] = (15, 25),
        break_length: tuple[float, float] = (120, 300),
        retries: int = 3,
        backoff: float = 60,
        timeout: float = 30,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.delay = delay
        self.break_every = break_every
        self.break_length = break_length
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "nb,no"}
        )
        self.sleep = sleep
        self.rng = rng or random.Random()
        self._until_break = self.rng.randint(*self.break_every)

    def _pause(self) -> None:
        if self._until_break <= 0:
            seconds = self.rng.uniform(*self.break_length)
            log.info("Coffee break: %.0f s", seconds)
            self.sleep(seconds)
            self._until_break = self.rng.randint(*self.break_every)
        self.sleep(self.rng.uniform(*self.delay))
        self._until_break -= 1

    def get(self, url: str) -> str:
        """Return the page's HTML. Raises `requests.HTTPError` once retries are spent."""
        for attempt in range(self.retries + 1):
            self._pause()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.retries:
                    raise
                wait = self.backoff * (attempt + 1)
                log.warning("Connection problem for %s, retrying in %.0f s", url, wait)
                self.sleep(wait)
                continue

            if response.status_code in RETRY_STATUSES and attempt < self.retries:
                wait = self._retry_after(response) or self.backoff * (attempt + 1)
                log.warning(
                    "HTTP %s for %s, retrying in %.0f s",
                    response.status_code,
                    url,
                    wait,
                )
                self.sleep(wait)
                continue

            response.raise_for_status()
            # Without a charset header, requests assumes ISO-8859-1 for text/html.
            if "charset" not in response.headers.get("Content-Type", "").lower():
                response.encoding = "utf-8"
            return response.text
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        value = response.headers.get("Retry-After", "")
        return float(value) if value.isdigit() else None
