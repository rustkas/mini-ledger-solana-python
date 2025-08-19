# Solana airdrop — это способ получить тестовые токены «из воздуха» (фактически — faucet).
# Когда разработчик пишет смарт-контракты или тестирует приложение, ему нужны токены, но покупать SOL ради тестов нецелесообразно.
# Для этого в dev/test-средах есть эндпоинт /airdrop, который просто увеличивает баланс аккаунта.
# /airdrop будет искусственным источником денег, чтобы можно было потом гонять транзакции и видеть движение токенов.


# В Solana bank — это объект, который хранит состояние счетов: кто и сколько токенов имеет.
# Банк меняется при транзакциях:
# Airdrop увеличивает баланс.
# Transfer уменьшает у отправителя и увеличивает у получателя.
# Валидатор при воспроизведении слотов также строит банк локально и сверяет, совпадают ли балансы.
# /bank будет API-эндпоинтом для отладки — можно посмотреть текущее распределение балансов (словарь pubkey → amount).

# Необходимо научить систему хранить состояние (балансы).
# Без этого тестировать транзакции не получится.

from fastapi.testclient import TestClient
import importlib

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def test_airdrop_and_bank_balance():
    with TestClient(app) as c:
        # псевдо-ключ аккаунта (в проде это был бы pubkey в hex)
        pk = "deadbeef" * 4

        # 1) airdrop 100 токенов
        r = c.post("/airdrop", json={"pubkey": pk, "amount": 100})
        assert r.status_code == 200, r.text

        # 2) проверяем баланс через /bank
        r = c.get("/bank")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "balances" in body
        assert isinstance(body["balances"], dict)
        assert body["balances"].get(pk) == 100
