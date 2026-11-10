import random

import pytest
import requests

from local_branch_overview.scraper.client import USER_AGENT, PoliteClient


class FakeResponse:
    def __init__(
        self, status: int = 200, text: str = "ok", headers: dict | None = None
    ) -> None:
        self.status_code = status
        self.text = text
        self.headers = {"Content-Type": "text/html; charset=utf-8"} | (headers or {})
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.headers: dict = {}
        self.urls: list[str] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.urls.append(url)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_client(responses: list, **kwargs) -> tuple[PoliteClient, list[float]]:
    sleeps: list[float] = []
    client = PoliteClient(
        session=FakeSession(responses),
        sleep=sleeps.append,
        rng=random.Random(0),
        **kwargs,
    )
    return client, sleeps


def test_pauses_before_every_request_and_sets_user_agent() -> None:
    client, sleeps = make_client(
        [FakeResponse()] * 3, delay=(5, 15), break_every=(100, 100)
    )

    for _ in range(3):
        assert client.get("https://example.org/") == "ok"

    assert len(sleeps) == 3
    assert all(5 <= s <= 15 for s in sleeps)
    assert client.session.headers["User-Agent"] == USER_AGENT


def test_coffee_break_after_n_requests() -> None:
    client, sleeps = make_client(
        [FakeResponse()] * 5, delay=(1, 1), break_every=(2, 2), break_length=(200, 200)
    )

    for _ in range(5):
        client.get("https://example.org/")

    assert sleeps == [1, 1, 200, 1, 1, 200, 1]


def test_retries_on_503_with_retry_after() -> None:
    client, sleeps = make_client(
        [FakeResponse(503, headers={"Retry-After": "42"}), FakeResponse(text="fine")],
        delay=(1, 1),
        break_every=(100, 100),
    )

    assert client.get("https://example.org/") == "fine"
    assert sleeps == [1, 42, 1]


def test_retries_connection_errors_with_backoff_then_gives_up() -> None:
    client, sleeps = make_client(
        [requests.ConnectionError()] * 3,
        delay=(1, 1),
        break_every=(100, 100),
        retries=2,
        backoff=10,
    )

    with pytest.raises(requests.ConnectionError):
        client.get("https://example.org/")
    assert sleeps == [1, 10, 1, 20, 1]


def test_raises_on_404_without_retry() -> None:
    client, _ = make_client([FakeResponse(404)], delay=(1, 1), break_every=(100, 100))

    with pytest.raises(requests.HTTPError):
        client.get("https://example.org/")
    assert len(client.session.urls) == 1


def test_defaults_to_utf8_without_charset() -> None:
    response = FakeResponse(headers={"Content-Type": "text/html"})
    response.encoding = "ISO-8859-1"
    client, _ = make_client([response], delay=(1, 1), break_every=(100, 100))

    client.get("https://example.org/")

    assert response.encoding == "utf-8"
