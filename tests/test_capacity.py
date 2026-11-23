from scripts.socket_capacity import aggregate


def shard(number=0):
    return {
        "run_id": "run",
        "shard": str(number),
        "hold_started_at": "2026-11-23T10:00:00Z",
        "hold_ended_at": "2026-11-23T10:01:00Z",
        "requested": 100,
        "held_start": 100,
        "held_end": 100,
        "handshake_errors": 0,
    }


def test_capacity_requires_overlapping_live_connections():
    assert aggregate([shard(0), shard(1)], 200)["status"] == "PASS"
    dropped = shard(1)
    dropped["held_end"] = 99
    assert aggregate([shard(0), dropped], 200)["status"] == "FAIL"
    delayed = shard(1)
    delayed["hold_started_at"] = "2026-11-23T10:02:00Z"
    delayed["hold_ended_at"] = "2026-11-23T10:03:00Z"
    assert aggregate([shard(0), delayed], 200)["status"] == "FAIL"
    assert aggregate([shard(0), shard(0)], 200)["status"] == "FAIL"
