import json
from pathlib import Path

import pytest

from carbon_forecast.db import connect, init_raw_schema

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def con():
    c = connect()
    init_raw_schema(c)
    yield c
    c.close()
