from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


@pytest.fixture
def main_html() -> str:
    return fixture_html("main")


@pytest.fixture
def agder_html() -> str:
    return fixture_html("agder")


@pytest.fixture
def arendal_html() -> str:
    return fixture_html("arendal")
