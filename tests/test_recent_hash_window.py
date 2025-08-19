# tests/test_recent_hash_window.py
from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

main = importlib.import_module("app.main")


def _canon_msg(from_hex: str, to_hex: str, amount: int, recent_hash: str) -> bytes:
    # Каноничный JSON без пробелов и в фиксированном порядке ключей
    return (
        "{"
        f"\"from\":\"{from_hex}\","
        f"\"to\":\"{to_hex}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent_hash}\""
        "}"
    ).encode("utf-8")


def test_transfer_accepts_hash_within_window():
    """
    Должно принимать НЕ текущий, а один из недавних PoH-хэшей (внутри окна K).
    Стратегия:
      - протикаем PoH несколько раз и накапливаем хэши;
      - берём предпоследний (а не самый свежий) recent_hash;
      - подписываем и отправляем перевод → ожидаем 200.
    """
    app = main.build_app(role="leader")
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()

        assert c.post("/airdrop", json={"pubkey": frm, "amount": 5}).status_code == 200

        # Набираем несколько хэшей; 5 << K (K по умолчанию 32), так что chosen точно «в окне»
        hashes = [c.get("/poh").json()["hash"] for _ in range(5)]
        chosen = hashes[-2]  # не самый свежий, но ещё в окне

        msg = _canon_msg(frm, to, 1, chosen)
        sig = sk.sign(msg).signature.hex()
        r = c.post("/transfer", json={
            "from": frm, "to": to, "amount": 1,
            "recent_hash": chosen, "sig": sig
        })
        assert r.status_code == 200, r.text


def test_transfer_rejects_hash_outside_window():
    """
    Должно ОТКЛОНЯТЬ recent_hash, который старше окна K.
    Стратегия:
      - берём hash H0;
      - делаем много тиков (например, 40 при K=32);
      - используем H0 → ожидаем 400.
    """
    app = main.build_app(role="leader")
    with TestClient(app) as c:
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()

        assert c.post("/airdrop", json={"pubkey": frm, "amount": 5}).status_code == 200

        old_hash = c.get("/poh").json()["hash"]  # H0

        # Продвигаем PoH далеко за окно (K≈32); берём 40, чтобы точно «выпасть» из окна
        for _ in range(40):
            _ = c.get("/poh")

        msg = _canon_msg(frm, to, 1, old_hash)
        sig = sk.sign(msg).signature.hex()
        r = c.post("/transfer", json={
            "from": frm, "to": to, "amount": 1,
            "recent_hash": old_hash, "sig": sig
        })
        assert r.status_code == 400, "ожидали отклонение для старого recent_hash"
