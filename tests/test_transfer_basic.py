from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def _canon_msg(frm: str, to: str, amount: int, recent: str) -> bytes:
    return (
        "{"
        f"\"from\":\"{frm}\","
        f"\"to\":\"{to}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent}\""
        "}"
    ).encode()

def test_basic_transfer_updates_balances():
    with TestClient(app) as c:
        sk_from = SigningKey.generate()
        pk_from = sk_from.verify_key.encode().hex()
        pk_to   = SigningKey.generate().verify_key.encode().hex()

        # Airdrop отправителю
        assert c.post("/airdrop", json={"pubkey": pk_from, "amount": 100}).status_code == 200

        # Берём свежий PoH и подписываем
        recent = c.get("/poh").json()["hash"]
        msg = _canon_msg(pk_from, pk_to, 25, recent)
        sig = sk_from.sign(msg).signature.hex()

        # Подписанный перевод
        r = c.post("/transfer", json={
            "from": pk_from, "to": pk_to, "amount": 25,
            "recent_hash": recent, "sig": sig
        })
        assert r.status_code == 200, r.text

        bal = c.get("/bank").json()["balances"]
        assert bal.get(pk_from) == 75
        assert bal.get(pk_to) == 25
