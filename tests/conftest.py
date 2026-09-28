import json
import socket
from pathlib import Path

import pytest

from carbon_forecast.db import connect, init_raw_schema

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests run on fixtures only; any attempt to open a connection fails loudly."""

    def blocked(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def con():
    c = connect()
    init_raw_schema(c)
    yield c
    c.close()
