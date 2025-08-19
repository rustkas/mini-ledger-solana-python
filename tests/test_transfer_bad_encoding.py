# tests/test_transfer_bad_encoding.py
from fastapi.testclient import TestClient
import importlib

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def test_bad_hex_in_fields():
    with TestClient(app) as c:
        # from: не hex
        r = c.post("/transfer", json={"from":"nothex", "to":"aa"*32, "amount":1,
                                      "recent_hash":"0"*64, "sig":"0"*128})
        assert r.status_code == 400
        # sig: не hex
        r = c.post("/transfer", json={"from":"aa"*32, "to":"bb"*32, "amount":1,
                                      "recent_hash":"0"*64, "sig":"zzzz"})
        assert r.status_code == 400
