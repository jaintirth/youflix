# wasmer-probe (throwaway)

Tiny FastAPI app to test what Wasmer Edge supports (pymongo, Atlas over TCP, env vars) before deploying the real API.
Not part of YOUFLIX. Delete this folder once the answer is known.

1. Deploy this folder to Wasmer Edge (entrypoint `main:app`), set `MONGODB_URI` in its environment.
2. Visit `/libs`, `/env`, `/mongo` and note the results.

Local check: `pip install -r requirements.txt && python main.py`, then open http://localhost:8000/libs
