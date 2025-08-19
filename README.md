# Python + FastAPI - Mini Ledger Solana

## 📌 Solution Abstract
This is a mini-implementation of a "Solana-like" ledger (Python + FastAPI).
It demonstrates the key ideas of Solana on a minimal set of primitives:

- **PoH (Proof of History)** as monotonic sha256 "ticks" collected in **Entry** and grouped in **Slot**.
- **Leader mode**: generates PoH, accepts signed transactions, buffers them in entries and produces a log `/ledger`.
- **Validator mode**: accepts foreign slots via `/ingest`, recalculates PoH, verifies signatures and *replays* transactions to a local bank, converging with the leader state.
- **Anti-replay** by signature and `recent_hash` window to protect against "stale" transactions.

Suitable for **TDD/demo/study**, and as a skeleton mini-sandbox based on Solana design.

## ⚙️ How to use

### Installation
```bash
pip install "fastapi[standard]" orjson pynacl httpx pytest anyio
```

### Run
#### Leader:
`LEDGER_ROLE=leader fastapi dev main.py`

##### Validator:
`LEDGER_ROLE=validator fastapi dev main.py --port 8001`

### Tests
`make test`

## 🌐 API
### Leader

- `GET /health`
- `GET /poh`
- `GET /bank`
- `GET /ledger`
- `POST /airdrop {"pubkey":"<hex32_ed25519>","amount":1000}`
- `POST /transfer {"from":"<hex>","to":"<hex>","amount":5,"recent_hash":"<hex>","sig":"<hex64>"}`

### Validator

- `GET /health | /poh | /bank | /ledger`
- `POST /ingest {"slots":[ SlotOut... ]}`
