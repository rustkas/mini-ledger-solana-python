"""
Это учебная мини‑реализация «солано‑подобного» леджера на Python + FastAPI. Она демонстрирует ключевые идеи Solana на минимальном наборе примитивов:

PoH (Proof of History) как монотонные sha256‑«тики», собираемые в Entry и группируемые в Slot.
Leader‑режим: генерирует PoH, принимает подписанные переводы, буферизует их в entries и выдаёт журнал /ledger.
Validator‑режим: принимает чужие слоты через /ingest, пере‑считвает PoH, проверяет подписи и replay’ит транзакции в локальный банк, сходясь со стейтом лидера.
Anti‑replay по подписи и окно recent_hash для защиты от «устаревших» транзакций.

Подходит для TDD/демо/учёбы, а также как скелет мини‑песочницы по мотивам дизайна Solana.

Зачем это

Пощупать руками: как PoH превращает время в данные, а данные — в воспроизводимый журнал.
Увидеть разделение ролей: лидер пишет историю, валидатор воспроизводит без доверия к источнику.
Понять две важные защиты на «входе» транзакции: свежесть recent_hash и запрет на повтор подписи (anti‑replay).

Install & run:
  pip install "fastapi[standard]" orjson pynacl httpx pytest anyio
  # Leader
  LEDGER_ROLE=leader fastapi dev main.py
  # Validator
  LEDGER_ROLE=validator fastapi dev main.py --port 8001
Test:
    make test

API (leader):
  GET  /health | /poh | /bank | /ledger
  POST /airdrop {"pubkey":"<hex32_ed25519>","amount":1000}
  POST /transfer {"from":"<hex>","to":"<hex>","amount":5,"recent_hash":"<hex>","sig":"<hex64>"}

API (validator):
  GET  /health | /poh | /bank | /ledger   (state after replay)
  POST /ingest {"slots":[ SlotOut... ]}  (apply & verify)

Notes:
- Account id == Ed25519 **public key (hex)**. No separate registry.
- `recent_hash` should be taken from `/poh.hash` shortly before signing.

1. Entries

Entry — это минимальный «кусочек времени» в Solana.
В нём содержится:

num_hashes — сколько «тиков» (sha256 шагов) PoH было сделано;

hash — результат последнего тика;

transactions[] — список транзакций, которые произошли в этот интервал.

👉 По сути, Entry — это атом времени + данные.

Почему это важно:

позволяет упаковать транзакции в хронологический порядок;

каждый Entry подписан временем (PoH-хешем), поэтому нельзя подделать или вставить чужую транзакцию «назад во времени».

🔹 2. Slots

Slot — это «эпоха лидера» длительностью примерно 400 мс в реальной Solana.
Лидер генерирует много Entry подряд, пока его «очередь слота» не закончилась.

В нашем упрощении:

Slot = контейнер для массива Entries;

у него есть slot_id, started_ms (время старта), entries[].

Зачем нужен слот:

определяет границу ответственности одного лидера;

в блокчейне слот можно рассматривать как «блок», но с меньшей задержкой (в Solana блоки собираются из слотов пачками).

🔹 3. Ledger

Ledger — это последовательность слотов (и внутри — entries).
По сути, это аналог «блокчейна» в Solana.

Лидер генерирует Slots → складывает их в Ledger;

Ledger можно «отдать» другим узлам, чтобы они воспроизвели историю.

В нашем упрощении /ledger будет просто отдавать JSON-массив слотов.

🔹 4. Replay (валидаторский режим)

Replay (или «Replaying the ledger») — это процесс, когда валидатор получает от лидера слоты/entries и воспроизводит (применяет) транзакции в своём Bank.

Почему это нужно:

узлы не доверяют лидеру «на слово»;

они проверяют, что PoH в entries действительно корректный (каждый hash = sha256 от предыдущего);

затем проверяют подписи транзакций;

и применяют их в Bank, убеждаясь, что получилось то же самое состояние, что у лидера.

Это и есть «консенсус»: если все честные узлы, проигрывая ledger, получают одинаковое состояние, значит сеть синхронизирована.

"""




from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import ORJSONResponse
from typing import Dict, Any
import hashlib
import time
import os
from collections import deque


# --- параметры времени и журнала ---
ENTRY_TICKS = max(1, int(os.getenv("ENTRY_TICKS", "4")))
# каждые N тиков PoH формируем новый Entry (по умолчанию 4)

SLOT_TICKS  = max(1, int(os.getenv("SLOT_TICKS",  "12")))   
# каждые N тиков закрываем Slot и переносим его в ledger (по умолчанию 12)

MAX_SLOTS   = max(1, int(os.getenv("MAX_SLOTS",  "256")))    
# максимальное количество слотов, которые храним в памяти (/ledger)

# --- защита от stale hash и повторов ---
RECENT_HASH_WINDOW = max(1, int(os.getenv("RECENT_HASH_WINDOW", "32")))
# принимаем transfer, если recent_hash входит в K последних PoH-хэшей (по умолчанию 32)

SIG_CACHE_MAX      = max(1, int(os.getenv("SIG_CACHE_MAX", "4096")))
# anti-replay: запоминаем последние M sig, чтобы не применить одну и ту же подпись дважды (по умолчанию 4096)


# --- Ed25519 (мягкая зависимость) ---
try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
except Exception:  # pragma: no cover
    VerifyKey = None  # type: ignore
    BadSignatureError = Exception  # type: ignore


# ---------- PoH: простые "часы" ----------
def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()

def _is_hex(s: str) -> bool:
    try: bytes.fromhex(s); return True
    except ValueError: return False

def _check_keys(from_pk: str, to_pk: str, sig_hex: str) -> None:
    if len(from_pk) != 64 or not _is_hex(from_pk):
        raise HTTPException(status_code=400, detail="bad 'from' pubkey (hex32)")
    if len(to_pk) != 64 or not _is_hex(to_pk):
        raise HTTPException(status_code=400, detail="bad 'to' pubkey (hex32)")
    if not _is_hex(sig_hex) or len(sig_hex) != 128:
        raise HTTPException(status_code=400, detail="bad 'sig' (hex64)")

def _check_recent_hash(rh: str) -> None:
    if len(rh) != 64 or not _is_hex(rh):
        raise HTTPException(status_code=400, detail="bad 'recent_hash' (hex32)")


class PoH:
    """Мини-реализация Proof of History: последовательные sha256-тики."""
    def __init__(self, seed: bytes) -> None:
        self._cur = hashlib.sha256(seed).digest()
        self._height = 0

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._cur = _sha256(self._cur)
        self._height += n

    def snapshot(self) -> dict:
        return {"height": self._height, "hash": self._cur.hex()}

# ---------- Bank: состояние балансов ----------
class Bank:
    """Простейший «банк»: хранилище балансов pubkey -> amount."""
    def __init__(self) -> None:
        self._balances: Dict[str, int] = {}

    def airdrop(self, pubkey: str, amount: int) -> None:
        if amount <= 0:
            raise ValueError("amount must be > 0")
        self._balances[pubkey] = self._balances.get(pubkey, 0) + amount

    def transfer(self, from_pk: str, to_pk: str, amount: int) -> None:
        """Перевод без подписей: списать у отправителя, начислить получателю."""
        if amount <= 0:
            raise ValueError("amount must be > 0")
        if from_pk == to_pk:
            return  # no-op
        bal = self._balances.get(from_pk, 0)
        if bal < amount:
            raise ValueError("insufficient funds")
        self._balances[from_pk] = bal - amount
        self._balances[to_pk] = self._balances.get(to_pk, 0) + amount

    def balances(self) -> Dict[str, int]:
        return dict(self._balances)

# простой вид транзакции для журнала (то, что уже проверяется тестами по ключам)
def _canon_tx_bytes(from_hex: str, to_hex: str, amount: int, recent_hash: str) -> bytes:
    # Каноничный JSON в фиксированном порядке ключей, без пробелов
    return (
        "{"
        f"\"from\":\"{from_hex}\","
        f"\"to\":\"{to_hex}\","
        f"\"amount\":{amount},"
        f"\"recent_hash\":\"{recent_hash}\""
        "}"
    ).encode("utf-8")


def build_app(role: str | None = None) -> FastAPI:
    state: Dict[str, Any] = {"role": (role or "leader")}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # инициализируем PoH и Bank на старте приложения
        SEED = os.getenv("POH_SEED", "genesis-seed").encode()
        state["poh"] = PoH(seed=SEED)
        state["bank"] = Bank()
        # журнал слотов/энтри (только у лидера заполняется)
        state["slots"] = []              # список слотов: [{"slot", "started_ms", "entries": [...]}]
        state["cur_slot"] = None         # текущий незакрытый слот
        state["ticks_in_slot"] = 0       # тики внутри текущего слота
        state["ticks_since_entry"] = 0   # тики с момента последнего entry
        state["pending_txs"] = []        # неподписанные (уже проверенные) tx для ближайшего entry
        state["pending_sys"] = []
        state["slot_seq"] = 0            # номер слота (инкремент)

        # стартуем окно recent_hash
        initial_hash = state["poh"].snapshot()["hash"]
        state["recent_hashes"] = deque([initial_hash], maxlen=RECENT_HASH_WINDOW)
        # кэш сигнатур (anti-replay)
        state["sig_seen_set"] = set()
        state["sig_seen_q"]   = deque()


        yield
        # тут пока ничего закрывать не нужно

    app = FastAPI(
        title="Solana TDD — step3",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    def _ensure_slot_started():
        if state["cur_slot"] is None:
            state["cur_slot"] = {
                "slot": state["slot_seq"],
                "started_ms": int(time.time() * 1000),
                "entries": []
            }
            state["ticks_in_slot"] = 0
            state["ticks_since_entry"] = 0

    def _flush_entry_if_needed():
        if state["ticks_since_entry"] >= ENTRY_TICKS and state["cur_slot"] is not None:
            # записываем entry с текущим hash и накопленными транзакциями
            poh: PoH = state["poh"]
            entry = {
                "num_hashes": state["ticks_since_entry"],
                "hash": poh.snapshot()["hash"],
                "transactions": list(state["pending_txs"])  # копия
            }
            #  ⬇️ если есть системные события — положим их в отдельный ключ "system"
            if state["pending_sys"]:
                entry["system"] = list(state["pending_sys"])
                state["pending_sys"].clear()
            state["cur_slot"]["entries"].append(entry)
            state["pending_txs"].clear()
            state["ticks_since_entry"] = 0

    def _flush_slot_if_needed():
        if state["ticks_in_slot"] >= SLOT_TICKS and state["cur_slot"] is not None:
            # закрываем слот и публикуем в общий список
            state["slots"].append(state["cur_slot"])
            if len(state["slots"]) > MAX_SLOTS:
                state["slots"] = state["slots"][-MAX_SLOTS:]
            state["slot_seq"] += 1
            state["cur_slot"] = None  # следующий тик запустит новый слот


    @app.get("/health", response_model=dict)
    async def health() -> dict:
        return {"ok": True}

    @app.get("/poh", response_model=dict)
    async def get_poh() -> dict:
        """Возвращает снимок PoH и тикает на 1 шаг. В leader-режиме собирает entries/slots."""
        poh: PoH = state["poh"]
        # тик
        poh.step(1)

        snap = poh.snapshot()
        state["recent_hashes"].append(snap["hash"])

        # если лидер — собираем временные структуры
        if state["role"] == "leader":
            _ensure_slot_started()
            state["ticks_in_slot"] += 1
            state["ticks_since_entry"] += 1
            _flush_entry_if_needed()
            _flush_slot_if_needed()

        # slot в ответе — номер текущего активного слота (или последний закрытый)
        cur_slot_no = (
            state["cur_slot"]["slot"] if (state["role"] == "leader" and state["cur_slot"] is not None)
            else max(state["slot_seq"] - 1, 0)
        )

        return {"height": snap["height"], "hash": snap["hash"], "slot": cur_slot_no}


    # ---------- новые эндпойнты ----------
    @app.post("/airdrop", response_model=dict)
    async def post_airdrop(req: Dict[str, Any]) -> dict:
        """Начислить amount на указанный pubkey (faucet для тестов)."""
        pubkey = str(req.get("pubkey", "")).lower()
        amount = int(req.get("amount", 0))
        try:
            state["bank"].airdrop(pubkey, amount)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # стало: кладём в системный буфер
        state["pending_sys"].append({
            "type": "airdrop",
            "to": pubkey,
            "amount": amount
        })
        return {"ok": True}

    @app.get("/bank", response_model=dict)
    async def get_bank() -> dict:
        balances = state["bank"].balances()
        return {"balances": balances, "total_supply": sum(balances.values())}

    
    @app.post("/transfer", response_model=dict)
    async def post_transfer(req: Dict[str, Any]) -> dict:
        from_pk = str(req.get("from", "")).lower()
        to_pk   = str(req.get("to", "")).lower()
        amount  = int(req.get("amount", 0))
        recent  = str(req.get("recent_hash", "")).lower()
        sig_hex = str(req.get("sig", "")).lower()

        if not from_pk or not to_pk or amount <= 0 or not recent or not sig_hex:
            raise HTTPException(status_code=400, detail="missing or invalid fields (from,to,amount,recent_hash,sig)")

        _check_keys(from_pk, to_pk, sig_hex)
        _check_recent_hash(recent)

        # recent_hash должен быть одним из последних K значений
        if recent not in state["recent_hashes"]:
            raise HTTPException(status_code=400, detail="stale recent_hash")

        # anti-replay
        if sig_hex in state["sig_seen_set"]:
            raise HTTPException(status_code=400, detail="duplicate signature")

        if VerifyKey is None:
            raise HTTPException(status_code=500, detail="PyNaCl (Ed25519) not installed")
        try:
            msg = _canon_tx_bytes(from_pk, to_pk, amount, recent)
            VerifyKey(bytes.fromhex(from_pk)).verify(msg, bytes.fromhex(sig_hex))
        except BadSignatureError:
            raise HTTPException(status_code=400, detail="bad signature")
        except ValueError:
            raise HTTPException(status_code=400, detail="bad key or signature encoding")

        try:
            state["bank"].transfer(from_pk, to_pk, amount)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 1) зафиксировать sig в anti-replay кэше
        state["sig_seen_set"].add(sig_hex)
        state["sig_seen_q"].append(sig_hex)
        if len(state["sig_seen_q"]) > SIG_CACHE_MAX:
            old = state["sig_seen_q"].popleft()
            state["sig_seen_set"].discard(old)

        # 2) затем буферизуем tx в entry
        state["pending_txs"].append({
            "from": from_pk, "to": to_pk, "amount": amount,
            "recent_hash": recent, "sig": sig_hex
        })

        return {"ok": True}


    @app.get("/ledger", response_model=dict)
    async def get_ledger() -> dict:
        """Отдать накопленные слоты (leader)."""
        slots = list(state["slots"])
        # если слот незакрыт, можно отдать и его (в тестах достаточно закрытых)
        if state["role"] == "leader":
            cur = state["cur_slot"]
            if cur is not None and cur["entries"]:
                slots = slots + [cur]
        return {"slots": slots}

    @app.post("/ingest", response_model=dict)
    async def post_ingest(payload: Dict[str, Any]) -> dict:
        """Валидаторский режим: принять слоты лидера, перепроверить PoH и подписи, выполнить replay."""
        slots = payload.get("slots")
        if not isinstance(slots, list):
            raise HTTPException(status_code=400, detail="invalid payload: slots[] required")


        poh: PoH = state["poh"]
        bank: Bank = state["bank"]

        for sl in slots:
            entries = sl.get("entries", [])
            if not isinstance(entries, list):
                raise HTTPException(status_code=400, detail="invalid slot: entries[] required")

            for e_idx, e in enumerate(entries):
                # 1) перепроверяем PoH: сделать num_hashes шагов и сверить конечный hash
                try:
                    nh = int(e["num_hashes"])
                    want_hash = str(e["hash"])
                except Exception:
                    raise HTTPException(status_code=400, detail="invalid entry format")

                poh.step(nh)
                got = poh.snapshot()["hash"]
                if got != want_hash:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"poh mismatch at slot={sl.get('slot')} entry_index={e_idx}"
                                )   

                # 2a) системные записи (без подписей)
                sys_events = e.get("system", [])
                if not isinstance(sys_events, list):
                    raise HTTPException(status_code=400, detail="invalid entry: system[]")

                for ev in sys_events:
                    if ev.get("type") == "airdrop":
                        try:
                            to_acct = str(ev["to"])
                            amt = int(ev["amount"])
                        except Exception:
                            raise HTTPException(status_code=400, detail="bad airdrop fields in ingest")
                        try:
                            bank.airdrop(to_acct, amt)
                        except ValueError as ex:
                            raise HTTPException(status_code=400, detail=f"bank error: {ex}")
                    else:
                        raise HTTPException(status_code=400, detail=f"unknown system event: {ev.get('type')}")


                # 2b) для каждой транзакции — проверка подписи и применение
                txs = e.get("transactions", [])
                if not isinstance(txs, list):
                    raise HTTPException(status_code=400, detail="invalid entry: transactions[]")

                for tx in txs:
                    # ⬇️ системная транзакция AIRDROP (без подписи)
                    if tx.get("type") == "airdrop":
                        try:
                            to_acct = str(tx["to"])
                            amt = int(tx["amount"])
                        except Exception:
                            raise HTTPException(status_code=400, detail="bad airdrop fields in ingest")
                        try:
                            bank.airdrop(to_acct, amt)
                        except ValueError as e:
                            raise HTTPException(status_code=400, detail=f"bank error: {e}")
                        continue  # к следующей tx

                    # ⬇️ обычный подписанный TRANSFER (как у вас было)
                    try:
                        frm = str(tx["from"]); to = str(tx["to"])
                        amt = int(tx["amount"])
                        rh  = str(tx["recent_hash"])
                        sig_hex = str(tx["sig"])
                    except Exception:
                        raise HTTPException(status_code=400, detail="bad tx fields")

                    # свежесть recent_hash: в режиме ingest валидатор уже шагнул PoH и ожидает,
                    # что recent_hash относится к цепочке лидера; здесь можно смягчить правило.
                    # Мы ограничимся проверкой подписи (PoH уже проверили как последовательность).
                    if VerifyKey is None:
                        raise HTTPException(status_code=500, detail="PyNaCl (Ed25519) not installed")
                    try:
                        msg = _canon_tx_bytes(frm, to, amt, rh)
                        VerifyKey(bytes.fromhex(frm)).verify(msg, bytes.fromhex(sig_hex))
                    except BadSignatureError:
                        raise HTTPException(status_code=400, detail="bad signature in ingest")
                    except ValueError:
                        raise HTTPException(status_code=400, detail="bad key or signature encoding in ingest")

                    try:
                        bank.transfer(frm, to, amt)
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=f"bank error: {e}")

        # обновляем локальный «журнал» как принятый (по желанию можно сохранить)
        return {"ok": True}

    @app.get("/config", response_model=dict)
    async def get_config() -> dict:
        return {
            "ENTRY_TICKS": ENTRY_TICKS,
            "SLOT_TICKS": SLOT_TICKS,
            "MAX_SLOTS": MAX_SLOTS,
            "RECENT_HASH_WINDOW": RECENT_HASH_WINDOW,
            "SIG_CACHE_MAX": SIG_CACHE_MAX,
            "ROLE": state["role"],
        }
    
    return app

# для fastapi dev app/main.py
app = build_app(role="leader")
