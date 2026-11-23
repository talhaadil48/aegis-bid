from copy import deepcopy
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegis.db import connection
from aegis.engine import admit, close, process
from aegis.evidence import export_auction
from aegis.verifier import verify


def test_signed_independent_replay(auction, tmp_path, monkeypatch):
    aid, bidder = auction
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "private.pem"
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setenv("AUDIT_SIGNING_KEY", str(path))
    for amount in [100, 100, 120]:
        admit(aid, bidder, uuid4(), amount)
        process(aid, "worker")
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    close(aid, "worker")
    doc = export_auction(aid)
    assert verify(doc, public)["status"] == "PASS"
    assert str(bidder) not in str(doc)
    changed = deepcopy(doc)
    changed["events"][0]["payload"]["amount_cents"] += 1
    assert verify(changed, public)["status"] == "FAIL"
    changed = deepcopy(doc)
    changed["events"].pop()
    assert verify(changed, public)["status"] == "FAIL"
    changed = deepcopy(doc)
    changed["winners"] = []
    assert verify(changed, public)["status"] == "FAIL"
    monkeypatch.delenv("AUDIT_SIGNING_KEY")
    assert verify(export_auction(aid))["status"] == "INCOMPLETE"
