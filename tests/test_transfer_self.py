# tests/test_transfer_self.py
from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def _canon(frm, to, amt, rh):
    return (
        "{"
        f"\"from\":\"{frm}\","
        f"\"to\":\"{to}\","
        f"\"amount\":{amt},"
        f"\"recent_hash\":\"{rh}\""
        "}"
    ).encode()

def test_transfer_to_self_is_noop():
    with TestClient(app) as c:
        sk = SigningKey.generate()
        pk = sk.verify_key.encode().hex()

        # Airdrop 50 на аккаунт
        assert c.post("/airdrop", json={"pubkey": pk, "amount": 50}).status_code == 200
        bal0 = c.get("/bank").json()
        assert bal0["balances"].get(pk) == 50
        assert bal0["total_supply"] == 50

        # Подписываем перевод "самому себе"
        recent = c.get("/poh").json()["hash"]
        sig = sk.sign(_canon(pk, pk, 25, recent)).signature.hex()
        r = c.post("/transfer", json={
            "from": pk, "to": pk, "amount": 25,
            "recent_hash": recent, "sig": sig
        })
        assert r.status_code == 200, r.text

        # Баланс и supply должны остаться прежними
        bal1 = c.get("/bank").json()
        assert bal1["balances"].get(pk) == 50
        assert bal1["total_supply"] == 50
