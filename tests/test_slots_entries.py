# tests/test_slots_entries.py
import importlib
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

main = importlib.import_module("app.main")

def _canon_msg(frm: str, to: str, amount: int, recent: str) -> bytes:
    return (
        "{"
        f"\"from\":\"{frm}\","
        f"\"to\":\"{to}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent}\""
        "}"
    ).encode("utf-8")


def test_leader_forms_entries_and_slots_and_exposes_ledger():
    # Лидер с фоновым PoH (пока падение — т.к. этого нет)
    leader_app = main.build_app(role="leader")
    with TestClient(leader_app) as c:
        # готовим подписанный перевод
        sk_from = SigningKey.generate()
        pk_from = sk_from.verify_key.encode().hex()
        pk_to   = SigningKey.generate().verify_key.encode().hex()

        # начальное состояние
        assert c.post("/airdrop", json={"pubkey": pk_from, "amount": 100}).status_code == 200

        # немного «протикаем» PoH
        for _ in range(5):
            _ = c.get("/poh")

        # берём свежий hash для сообщения
        recent = c.get("/poh").json()["hash"]
        sig = sk_from.sign(_canon_msg(pk_from, pk_to, 7, recent)).signature.hex()
        assert c.post("/transfer", json={
            "from": pk_from, "to": pk_to, "amount": 7,
            "recent_hash": recent, "sig": sig
        }).status_code == 200

        # ещё тикаем, чтобы лидер успел оформить хотя бы один слот
        for _ in range(10):
            _ = c.get("/poh")

        # /ledger должен вернуть хотя бы один слот с энтри и транзакцией
        r = c.get("/ledger")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "slots" in body and isinstance(body["slots"], list)
        assert len(body["slots"]) >= 1

        # проверяем схему первого слота и наличие хотя бы одной транзакции
        s0 = body["slots"][0]
        assert {"slot", "started_ms", "entries"} <= set(s0.keys())
        assert isinstance(s0["entries"], list) and len(s0["entries"]) >= 1

        # в каком-то entry должна быть наша транзакция
        found = False
        for e in s0["entries"]:
            assert {"num_hashes", "hash", "transactions"} <= set(e.keys())
            for tx in e["transactions"]:
                assert {"from", "to", "amount", "recent_hash", "sig"} <= set(tx.keys())
                if tx["from"] == pk_from and tx["to"] == pk_to and tx["amount"] == 7:
                    found = True
                    break
            if found:
                break
        assert found, "Ожидали найти нашу транзакцию внутри хотя бы одного entry"
