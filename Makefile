.PHONY: run run-validator test bench-poh bench-transfer

PY := python
PORT ?= 8000

run:
	LEDGER_ROLE=leader fastapi dev main.py --host 0.0.0.0 --port $(PORT)

run-validator:
	LEDGER_ROLE=validator fastapi dev main.py --host 0.0.0.0 --port 8001

test:
	python3 -m pytest -q

# Simple RPS bench against /poh (needs 'hey' or falls back to ab)
bench-poh:
	@which hey >/dev/null 2>&1 && hey -z 10s http://127.0.0.1:$(PORT)/poh || \
	 (which ab >/dev/null 2>&1 && ab -n 5000 -c 100 http://127.0.0.1:$(PORT)/poh || echo "Install 'hey' or 'ab'")

# Fire N signed transfers as a micro-bench
bench-transfer:
	@$(PY) - <<-'PY'
	import asyncio, os, json, time
	import httpx
	from nacl.signing import SigningKey
	URL = os.environ.get("URL","http://127.0.0.1:8000")
	async def main():
	    async with httpx.AsyncClient(base_url=URL) as c:
	        sk_from = SigningKey.generate(); from_hex = sk_from.verify_key.encode().hex()
	        sk_to = SigningKey.generate(); to_hex = sk_to.verify_key.encode().hex()
	        await c.post("/airdrop", json={"pubkey": from_hex, "amount": 100000})
	        t0 = time.time()
	        for i in range(1000):
	            poh = (await c.get("/poh")).json()
	            msg = ("{"
	                   f"\"from\":\"{from_hex}\","
	                   f"\"to\":\"{to_hex}\","
	                   f"\"amount\":1,\"recent_hash\":\"{poh['hash']}\""
	                   "}")
	            sig = sk_from.sign(msg.encode()).signature.hex()
	            await c.post("/transfer", json={"from":from_hex,"to":to_hex,"amount":1,"recent_hash":poh["hash"],"sig":sig})
	        t1 = time.time()
	        print("queued 1000 transfers in", round(t1-t0,3), "s")
	asyncio.run(main())
	PY
