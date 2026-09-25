"""Bounded load test for the local market read endpoint (never calls Xianyu)."""

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:18080")
    parser.add_argument("--watch-id", type=int, required=True)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Only local services may be load tested by this script")
    if not 1 <= args.requests <= 10000 or not 1 <= args.concurrency <= 100:
        parser.error("requests must be 1..10000; concurrency 1..100")
    token = os.environ.get("MARKET_TEST_TOKEN", "")
    if not token:
        parser.error("Set MARKET_TEST_TOKEN to a user login token")
    url = args.base_url.rstrip("/") + "/api/market/trends?" + urlencode({"watchId": args.watch_id, "days": 7})

    def call(_):
        start = time.monotonic()
        request = Request(url, headers={"Authorization": "Bearer " + token})
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read()
                try:
                    code = json.loads(body).get("code")
                except (ValueError, AttributeError):
                    code = None
                return response.status == 200 and code in (0, 200), time.monotonic() - start
        except (HTTPError, URLError) as error:
            return False, time.monotonic() - start

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = [future.result() for future in as_completed(pool.submit(call, i) for i in range(args.requests))]
    latencies = sorted(result[1] for result in results)
    print(f"requests={len(results)} success={sum(ok for ok, _ in results)} "
          f"duration={time.monotonic()-started:.2f}s mean={statistics.mean(latencies)*1000:.1f}ms "
          f"p95={latencies[int(.95*(len(latencies)-1))]*1000:.1f}ms "
          f"max={max(latencies)*1000:.1f}ms")


if __name__ == "__main__":
    main()
