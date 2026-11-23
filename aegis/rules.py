import hashlib
import json

ZERO_HASH = "0" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def event_hash(previous, payload):
    return hashlib.sha256(previous.encode() + canonical(payload)).hexdigest()


def evaluate(auction, request, high):
    # Eligibility uses durable server admission time. Closing waits for every queued command.
    if auction["status"] == "CLOSED" or request["admitted_at"] >= auction["closes_at"]:
        return "CLOSED", "Auction deadline passed"
    if request["admitted_at"] < auction["opens_at"]:
        return "REJECTED", "Auction has not opened"
    required = max(auction["min_price_cents"], high + auction["increment_cents"] if high else 0)
    if request["amount_cents"] < required:
        return "REJECTED", f"Minimum next bid is {required} cents"
    return "ACCEPTED", "Eligible offer"
