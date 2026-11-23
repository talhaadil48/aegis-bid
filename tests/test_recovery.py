import json
from datetime import UTC, datetime

import pytest

from scripts.compare_baseline import experiment
from scripts.restore_sandbox import restore
from scripts.verify_recovery import write_certificate


def test_corrupt_backup_rejected_before_database_access(tmp_path):
    (tmp_path / "auction-db.dump").write_bytes(b"corrupted")
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"auction-db.dump": "wrong"}}))
    with pytest.raises(ValueError, match="checksum"):
        restore(tmp_path, tmp_path / "certificate", "postgresql://unreachable/unused")


def test_certificate_escapes_untrusted_text(tmp_path):
    write_certificate(
        {"status": "FAIL", "errors": ["<script>alert(1)</script>"], "finished_at": datetime.now(UTC).isoformat()},
        tmp_path / "certificate",
    )
    assert "<script>" not in (tmp_path / "certificate.html").read_text()
    assert json.loads((tmp_path / "certificate.json").read_text())["status"] == "FAIL"


def test_parallel_universe_demonstration():
    assert experiment(False)["accepted"] == 30
    assert experiment(True)["accepted"] == 1
