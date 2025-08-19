# tests/test_integration_smoke.py
from fastapi.testclient import TestClient
import importlib
from nacl.signing import SigningKey

# Берём фабрику приложений, чтобы на каждый тест было свежее состояние
main = importlib.import_module("app.main")
app = main.build_app(role="leader")


def _canon_msg(frm: str, to: str, amount: int, recent: str) -> bytes:
    """Каноничный JSON для подписи (тот же порядок ключей, без пробелов)."""
    return (
        "{"
        f"\"from\":\"{frm}\","
        f"\"to\":\"{to}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent}\""
        "}"
    ).encode("utf-8")


def test_smoke_end_to_end_and_invariants():
    with TestClient(app) as c:
        # 1) сервис жив
        r = c.get("/health")
        assert r.status_code == 200 and r.json() == {"ok": True}

        # 2) PoH тикает: высота растёт между вызовами
        h0 = c.get("/poh").json()["height"]
        h1 = c.get("/poh").json()["height"]
        assert h1 > h0

        # 3) создаём исходное состояние: airdrop на константный ключ (без подписи)
        alice = "aa" * 32
        bob   = "bb" * 32
        r = c.post("/airdrop", json={"pubkey": alice, "amount": 100})
        assert r.status_code == 200

        # supply после airdrop = 100
        bal = c.get("/bank").json()["balances"]
        assert bal.get(alice) == 100 and sum(bal.values()) == 100

        # 4) подписанный перевод: генерим ключи отправителя/получателя
        sk_alice = SigningKey.generate()
        pk_alice = sk_alice.verify_key.encode().hex()
        pk_bob   = SigningKey.generate().verify_key.encode().hex()

        # airdrop делаем на pk_alice (подписываемый аккаунт)
        assert c.post("/airdrop", json={"pubkey": pk_alice, "amount": 100}).status_code == 200

        # берём свежий PoH-хеш, формируем сообщение и подпись
        recent = c.get("/poh").json()["hash"]
        sig = sk_alice.sign(_canon_msg(pk_alice, pk_bob, 25, recent)).signature.hex()

        # отправляем подписанный перевод
        r = c.post("/transfer", json={
            "from": pk_alice, "to": pk_bob, "amount": 25,
            "recent_hash": recent, "sig": sig
        })
        assert r.status_code == 200, r.text

        # 5) проверяем инварианты и распределение балансов
        r = c.get("/bank")
        assert r.status_code == 200
        body = r.json()
        bal = body["balances"]

        # После двух airdrop'ов общий supply = 200,
        # transfer supply не меняет
        assert body.get("total_supply", sum(bal.values())) == 200
        assert sum(bal.values()) == 200

        # Подписанный перевод уменьшил pk_alice и увеличил pk_bob
        assert bal.get(pk_alice) == 75
        assert bal.get(pk_bob) == 25

        # Первая "старая" alice (константная) не участвовала в переводе — у неё осталось 100
        assert bal.get(alice) == 100


