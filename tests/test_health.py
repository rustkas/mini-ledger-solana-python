from fastapi.testclient import TestClient
import importlib

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def test_health_ok():
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
