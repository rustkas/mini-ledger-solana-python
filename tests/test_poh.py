from fastapi.testclient import TestClient
import importlib

main = importlib.import_module("app.main")
app = main.build_app(role="leader")

def test_poh_shape_and_defaults():
    with TestClient(app) as c:
        r = c.get("/poh")
        assert r.status_code == 200
        data = r.json()
        # ожидаем поля height/hash/slot
        # Это минимальный снимок состояния Proof of History (PoH) в нашем API.

        # height: 1234
        # Это номер тика PoH — сколько раз мы уже применили хэш-функцию с начала работы.
        # Аналог секунд на часах: каждый тик = очередной шаг PoH.
        # Чем больше число, тем длиннее и «дороже» вся история.

        # hash: "abc123…"
        # Это текущий PoH-хэш (результат последнего тика).
        # Он «подписывает» всё, что произошло до этого момента.
        # Если поменять хоть одно событие в прошлом → весь хэш изменится.

        # slot: 0
        # Это номер слота, к которому относится этот PoH-тик.
        # В реальной Solana один слот ≈ 400 мс, в нём лидер накапливает набор транзакций и хэшей.

        # У нас пока slot = 0 всегда (заглушка), но потом появится:
        #       slot 0 → первые 100 тиков,
        #       slot 1 → следующие 100 тиков,
        #       и т.д.
        # Слот = контейнер для группы PoH-steps + транзакций.
        
        assert set(data.keys()) == {"height", "hash", "slot"}
        assert isinstance(data["height"], int) and data["height"] >= 0
        assert isinstance(data["slot"], int) and data["slot"] >= 0
        assert isinstance(data["hash"], str) and len(data["hash"]) == 64

        # повторный вызов должен увеличить height хотя бы на 1
        h1 = data["height"]
        r2 = c.get("/poh")
        assert r2.status_code == 200
        assert r2.json()["height"] > h1
