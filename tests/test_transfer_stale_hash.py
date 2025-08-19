# tests/test_transfer_stale_hash.py
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

def test_stale_recent_hash_rejected():
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()
        assert c.post("/airdrop", json={"pubkey": frm, "amount": 10}).status_code == 200

        recent = c.get("/poh").json()["hash"]
        # «Старим» hash лишним вызовом /poh
        _ = c.get("/poh")

        sig = sk.sign(_canon(frm, to, 1, recent)).signature.hex()
        r = c.post("/transfer", json={"from": frm, "to": to, "amount": 1,
                                      "recent_hash": recent, "sig": sig})
        assert r.status_code == 400
        assert r.json()["detail"] == "stale recent_hash"
