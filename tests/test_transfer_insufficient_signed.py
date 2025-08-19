# tests/test_transfer_insufficient_signed.py
from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def _canon(frm, to, amt, rh): 
    return ("{"
            f"\"from\":\"{frm}\","
            f"\"to\":\"{to}\","
            f"\"amount\":{amt},"
            f"\"recent_hash\":\"{rh}\""
            "}").encode()

def test_insufficient_funds_signed_no_side_effects():
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()
        assert c.post("/airdrop", json={"pubkey": frm, "amount": 5}).status_code == 200

        recent = c.get("/poh").json()["hash"]
        sig = sk.sign(_canon(frm, to, 10, recent)).signature.hex()  # сумма больше баланса
        r = c.post("/transfer", json={"from": frm, "to": to, "amount": 10,
                                      "recent_hash": recent, "sig": sig})
        assert r.status_code == 400
        bal = c.get("/bank").json()
        assert bal["balances"].get(frm) == 5
        assert bal["balances"].get(to, 0) == 0
        assert bal["total_supply"] == 5
