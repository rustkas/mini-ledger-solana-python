# tests/test_anti_replay.py
from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

main = importlib.import_module("app.main")

def _canon_msg(from_hex: str, to_hex: str, amount: int, recent_hash: str) -> bytes:
    return (
        "{"
        f"\"from\":\"{from_hex}\","
        f"\"to\":\"{to_hex}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent_hash}\""
        "}"
    ).encode("utf-8")

def test_duplicate_signature_rejected():
    """
    Одна и та же подпись (sig) не должна применяться дважды.
    Стратегия:
      - берём свежий recent_hash;
      - создаём ПОЛНОСТЬЮ одинаковую транзакцию дважды (тот же msg → та же sig);
      - первая проходит (200), вторая отклоняется (400).
    """
    app = main.build_app(role="leader")
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()

        assert c.post("/airdrop", json={"pubkey": frm, "amount": 10}).status_code == 200

        recent = c.get("/poh").json()["hash"]
        msg = _canon_msg(frm, to, 3, recent)
        sig = sk.sign(msg).signature.hex()

        # 1-я отправка — OK
        r1 = c.post("/transfer", json={
            "from": frm, "to": to, "amount": 3,
            "recent_hash": recent, "sig": sig
        })
        assert r1.status_code == 200, r1.text

        # 2-я отправка с ТОЙ ЖЕ подписью — должна быть отклонена
        r2 = c.post("/transfer", json={
            "from": frm, "to": to, "amount": 3,
            "recent_hash": recent, "sig": sig
        })
        assert r2.status_code == 400, "повторная подпись должна отклоняться (anti-replay)"
