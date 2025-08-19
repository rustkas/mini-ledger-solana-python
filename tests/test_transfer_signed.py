from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

# Берём фабрику приложений, чтобы каждый тест имел «свежее» состояние
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


def test_transfer_requires_signature_and_accepts_valid():
    # свежий app
    app = main.build_app(role="leader")
    with TestClient(app) as c:
        # генерим ключи
        sk_from = SigningKey.generate()
        pk_from_hex = sk_from.verify_key.encode().hex()
        sk_bad  = SigningKey.generate()  # для «плохой» подписи
        pk_to_hex = SigningKey.generate().verify_key.encode().hex()

        # исходное состояние: airdrop отправителю
        r = c.post("/airdrop", json={"pubkey": pk_from_hex, "amount": 100})
        assert r.status_code == 200

        # берём свежий PoH hash
        recent = c.get("/poh").json()["hash"]

        # 1) Без подписи и recent_hash — должно быть ОШИБКОЙ (400)
        r = c.post("/transfer", json={"from": pk_from_hex, "to": pk_to_hex, "amount": 25})
        assert r.status_code == 400, "transfer без подписи и recent_hash должен отклоняться"

        # 2) С НЕКОРРЕКТНОЙ подписью — тоже ОШИБКА (400)
        bad_msg = _canon_msg(pk_from_hex, pk_to_hex, 25, recent)
        bad_sig = sk_bad.sign(bad_msg).signature.hex()  # подписал «не тот» ключ
        r = c.post("/transfer", json={
            "from": pk_from_hex,
            "to": pk_to_hex,
            "amount": 25,
            "recent_hash": recent,
            "sig": bad_sig
        })
        assert r.status_code == 400, "некорректная подпись должна отклоняться"

        # 3) С КОРРЕКТНОЙ подписью — ОК (200) и балансы обновляются
        good_msg = _canon_msg(pk_from_hex, pk_to_hex, 25, recent)
        good_sig = sk_from.sign(good_msg).signature.hex()
        r = c.post("/transfer", json={
            "from": pk_from_hex,
            "to": pk_to_hex,
            "amount": 25,
            "recent_hash": recent,
            "sig": good_sig
        })
        assert r.status_code == 200, r.text

        bal = c.get("/bank").json()["balances"]
        assert bal.get(pk_from_hex) == 75
        assert bal.get(pk_to_hex) == 25
