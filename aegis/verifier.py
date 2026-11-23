"""Independent replay: deliberately does not import the auction engine or its rules."""

import argparse
import base64
import binascii
import hashlib
import json
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization


def verify(document, trusted_key=None):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    unsigned = {k: v for k, v in document.items() if k != "signature"}
    signed = False
    if document.get("signature") and trusted_key:
        try:
            key = serialization.load_pem_public_key(trusted_key)
            key.verify(base64.b64decode(document["signature"]), encode(unsigned))
            signed = True
        except (InvalidSignature, ValueError, TypeError, binascii.Error):
            errors.append("Signature does not match trusted key")
    elif trusted_key:
        errors.append("Missing signature")
    a = document["auction"]
    check(document["schema_version"] == 1, "Unknown schema")
    previous = "0" * 64
    offers = {}
    requests = set()
    closed = False
    last_intake = 0
    high = 0
    for seq, event in enumerate(document["events"], 1):
        payload = event["payload"]
        check(event["event_seq"] == seq and payload["decision_seq"] == seq, "Non-contiguous sequence")
        check(event["prev_hash"] == previous, "Broken previous hash")
        digest = hashlib.sha256(previous.encode() + encode(payload)).hexdigest()
        check(event["event_hash"] == digest, "Changed event hash")
        previous = event["event_hash"]
        if payload["type"] == "bid.decision":
            check(not closed, "Decision after final close")
            rid = payload["request_id"]
            check(rid not in requests, "Duplicate request decision")
            requests.add(rid)
            check(payload["intake_seq"] > last_intake, "Intake ordering mismatch")
            last_intake = payload["intake_seq"]
            admitted = datetime.fromisoformat(payload["admitted_at"])
            required = max(a["min_price_cents"], high + a["increment_cents"] if high else 0)
            expected = "ACCEPTED"
            if admitted >= datetime.fromisoformat(a["closes_at"]):
                expected = "CLOSED"
            elif admitted < datetime.fromisoformat(a["opens_at"]) or payload["amount_cents"] < required:
                expected = "REJECTED"
            check(payload["status"] == expected, "Decision violates auction rules")
            if payload["status"] == "ACCEPTED":
                offers[payload["bidder"]] = (payload["amount_cents"], seq)
                high = max(high, payload["amount_cents"])
        elif payload["type"] == "auction.closed":
            check(not closed, "Duplicate close")
            closed = True
            calculated = [
                {"bidder": k, "amount_cents": v[0]}
                for k, v in sorted(offers.items(), key=lambda pair: (-pair[1][0], pair[1][1]))[: a["stock"]]
            ]
            check(payload["winners"] == calculated, "Close-event winners mismatch")
        else:
            errors.append("Unknown event type")
    check(previous == document["anchor"], "Anchor mismatch")
    check(len(document["events"]) == a["version"], "Truncated history/version mismatch")
    check(closed == (a["status"] == "CLOSED"), "Auction status mismatch")
    expected_winners = (
        [
            {"bidder": k, "amount_cents": v[0], "rank": i}
            for i, (k, v) in enumerate(
                sorted(offers.items(), key=lambda pair: (-pair[1][0], pair[1][1]))[: a["stock"]], 1
            )
        ]
        if closed
        else []
    )
    check(document["winners"] == expected_winners, "Stored winners mismatch")
    check(len(document["winners"]) <= a["stock"], "Stock exceeded")
    return {
        "status": "FAIL" if errors else ("PASS" if signed else "INCOMPLETE"),
        "errors": errors,
        "signature_verified": signed,
        "events": len(document["events"]),
        "decisions": len(requests),
        "winners": len(expected_winners),
        "scope": "Single exported auction; unsigned evidence has no independent trusted anchor",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence")
    parser.add_argument("--trusted-key", required=True)
    args = parser.parse_args()
    try:
        report = verify(json.loads(Path(args.evidence).read_text()), Path(args.trusted_key).read_bytes())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
