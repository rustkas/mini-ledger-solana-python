from fastapi.testclient import TestClient
import importlib

# tests/test_invariants.py
from nacl.signing import SigningKey


# Берём фабрику приложений, чтобы на каждый тест было свежее состояние
main = importlib.import_module("app.main")
app = main.build_app(role="leader")


def test_total_supply_matches_sum():
    with TestClient(app) as c:
        a = "aa" * 32
        assert c.post("/airdrop", json={"pubkey": a, "amount": 3}).status_code == 200
        body = c.get("/bank").json()
        assert body["total_supply"] == sum(body["balances"].values())

def test_transfer_does_not_tick_poh():
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()
        c.post("/airdrop", json={"pubkey": frm, "amount": 1})

        recent = c.get("/poh").json()["hash"]
        mid    = c.get("/poh").json()["height"]  # зафиксировали текущую высоту

        msg = ("{"
            f"\"from\":\"{frm}\",\"to\":\"{to}\",\"amount\":1,"
            f"\"recent_hash\":\"{recent}\""
            "}").encode()
        sig = sk.sign(msg).signature.hex()

        # transfer не должен тикать PoH
        c.post("/transfer", json={"from": frm, "to": to, "amount": 1,
                                    "recent_hash": recent, "sig": sig})
        after = c.get("/poh").json()["height"]
        assert after == mid + 1  # тик только из-за нашего финального /poh


def test_total_supply_matches_sum():
    with TestClient(app) as c:
        a = "aa"*32
        assert c.post("/airdrop", json={"pubkey": a, "amount": 3}).status_code == 200
        body = c.get("/bank").json()
        assert body["total_supply"] == sum(body["balances"].values())