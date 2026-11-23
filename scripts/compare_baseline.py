"""Deterministic in-memory race demonstration, explicitly not a production benchmark."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor


def experiment(safe):
    barrier = threading.Barrier(30)
    lock = threading.Lock()
    high = 0
    accepted = 0

    def bid(_):
        nonlocal high, accepted
        if safe:
            barrier.wait()
            with lock:
                if high < 100:
                    high = 100
                    accepted += 1
        else:
            eligible = high < 100
            barrier.wait()
            if eligible:
                with lock:
                    high = 100
                    accepted += 1

    with ThreadPoolExecutor(max_workers=30) as pool:
        list(pool.map(bid, range(30)))
    return {"accepted": accepted, "contradictory_acceptances": max(0, accepted - 1), "valid": accepted == 1}


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "scope": "Synthetic barrier-controlled same-price race, no database or network; see PostgreSQL integration tests for implemented engine",
                "unsafe": experiment(False),
                "locked": experiment(True),
            },
            indent=2,
        )
    )
