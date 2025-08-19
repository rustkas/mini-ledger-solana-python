# tests/conftest.py
import importlib
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def app():
    main = importlib.import_module("app.main")
    return main.build_app(role="leader")

@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c

@pytest.fixture()
def canon_msg():
    def _canon(frm: str, to: str, amount: int, recent: str) -> bytes:
        return (
            "{"
            f"\"from\":\"{frm}\","
            f"\"to\":\"{to}\","
            f"\"amount\":{amount},"
            f"\"recent_hash\":\"{recent}\""
            "}"
        ).encode("utf-8")
    return _canon
