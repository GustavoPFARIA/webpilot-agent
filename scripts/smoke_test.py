"""Smoke test for a running server: start a real task through the API and wait
for the answer. Used by CI against the Docker image; handy after any deploy.

    python scripts/smoke_test.py [http://127.0.0.1:8000] [--token TOKEN]
"""

import argparse
import json
import sys
import time
import urllib.request


def call(base: str, path: str, token: str | None, body: dict | None = None) -> dict:
    # The scheme is validated in main(), so file:// and friends can't reach urlopen.
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data, timeout=10) as resp:  # noqa: S310
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--token")
    args = parser.parse_args()
    if not args.base.startswith(("http://", "https://")):
        parser.error("base must be an http(s) URL")

    for _ in range(60):
        try:
            print("health:", call(args.base, "/health", None))
            break
        except OSError:
            time.sleep(1)
    else:
        print("server never became healthy")
        return 1

    run = call(args.base, "/api/runs", args.token, {"task": "What is the price of the Aurora Headphones?"})
    for _ in range(120):
        run = call(args.base, f"/api/runs/{run['id']}", args.token)
        if run["status"] not in ("running", "awaiting_approval"):
            break
        time.sleep(0.5)
    print(f"status={run['status']} steps={len(run['steps'])} answer={run['answer']!r}")
    return 0 if run["status"] == "done" and "149.00" in run["answer"] else 1


if __name__ == "__main__":
    sys.exit(main())
