# tests/test_validator_replay.py
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


def test_leader_to_validator_ingest_and_replay_balances_match():
    # два независимых приложения: лидер и валидатор
    leader_app = main.build_app(role="leader")
    validator_app = main.build_app(role="validator")

    with TestClient(leader_app) as cl, TestClient(validator_app) as cv:
        # подготовим ключи и сделаем на лидере несколько переводов
        sk_from = SigningKey.generate()
        pk_from = sk_from.verify_key.encode().hex()
        pk_to   = SigningKey.generate().verify_key.encode().hex()

        assert cl.post("/airdrop", json={"pubkey": pk_from, "amount": 100}).status_code == 200

        # первый перевод
        recent = cl.get("/poh").json()["hash"]
        sig = sk_from.sign(_canon_msg(pk_from, pk_to, 10, recent)).signature.hex()
        assert cl.post("/transfer", json={
            "from": pk_from, "to": pk_to, "amount": 10,
            "recent_hash": recent, "sig": sig
        }).status_code == 200

        # второй перевод
        recent = cl.get("/poh").json()["hash"]
        sig = sk_from.sign(_canon_msg(pk_from, pk_to, 5, recent)).signature.hex()
        assert cl.post("/transfer", json={
            "from": pk_from, "to": pk_to, "amount": 5,
            "recent_hash": recent, "sig": sig
        }).status_code == 200

        # чуть протикаем PoH, чтобы слот(ы) «закрылись»
        for _ in range(10):
            _ = cl.get("/poh")

        # снимем состояние и слоты с лидера
        leader_bank = cl.get("/bank").json()
        ledger = cl.get("/ledger").json()
        assert "slots" in ledger and isinstance(ledger["slots"], list) and len(ledger["slots"]) >= 1

        # отдадим валидатору на /ingest
        r = cv.post("/ingest", json=ledger)
        assert r.status_code == 200, r.text

        # результат на валидаторе должен совпасть по балансам и total_supply
        vb = cv.get("/bank").json()
        assert vb["total_supply"] == leader_bank["total_supply"]
        # хотя бы эти ключи должны совпасть:
        assert vb["balances"].get(pk_from) == leader_bank["balances"].get(pk_from)
        assert vb["balances"].get(pk_to)   == leader_bank["balances"].get(pk_to)


def test_ingest_rejects_corrupted_entry():
    # лидер/валидатор
    leader_app = main.build_app(role="leader")
    validator_app = main.build_app(role="validator")
    with TestClient(leader_app) as cl, TestClient(validator_app) as cv:
        # простая транзакция на лидере
        sk = SigningKey.generate()
        frm = sk.verify_key.encode().hex()
        to  = SigningKey.generate().verify_key.encode().hex()
        assert cl.post("/airdrop", json={"pubkey": frm, "amount": 20}).status_code == 200
        recent = cl.get("/poh").json()["hash"]
        sig = sk.sign(_canon_msg(frm, to, 3, recent)).signature.hex()
        assert cl.post("/transfer", json={
            "from": frm, "to": to, "amount": 3,
            "recent_hash": recent, "sig": sig
        }).status_code == 200

        for _ in range(6):
            _ = cl.get("/poh")

        ledger = cl.get("/ledger").json()
        assert "slots" in ledger and ledger["slots"], "ожидали хотя бы один слот"

        # «ломаем» первый entry в первом слоте: меняем num_hashes
        ledger_bad = dict(ledger)  # поверхностная копия
        # глубокое изменение
        ledger_bad["slots"] = [dict(ledger["slots"][0])]
        ledger_bad["slots"][0]["entries"] = [dict(ledger["slots"][0]["entries"][0])]
        ledger_bad["slots"][0]["entries"][0]["num_hashes"] = ledger_bad["slots"][0]["entries"][0]["num_hashes"] + 1

        r = cv.post("/ingest", json=ledger_bad)
        assert r.status_code in (400, 422), r.text  # валидатор должен отвергнуть повреждённый slot
