"""Run explicitly on disposable local Compose host; no Docker socket in API."""

import os
import subprocess
import time

from aegis.db import connection


def main():
    if os.getenv("ENABLE_CHAOS") != "true" or os.getenv("ENVIRONMENT", "development") not in ("development", "test"):
        raise RuntimeError("Enable chaos only in a disposable local environment")
    actions = {
        "kill-worker": ["kill", "-s", "SIGKILL", "worker"],
        "restart-gateway": ["restart", "api"],
        "disconnect-client": ["restart", "api"],
    }
    while True:
        with connection() as c:
            row = c.execute(
                "SELECT * FROM incidents WHERE state='PENDING' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if row:
                command = actions.get(row["scenario"])
                result = (
                    subprocess.run(
                        ["docker", "compose", "--env-file", ".env", "-f", "infra/compose.yaml", *command],
                        capture_output=True,
                        check=False,
                        timeout=45,
                    )
                    if command
                    else None
                )
                c.execute(
                    "UPDATE incidents SET state=%s WHERE id=%s",
                    ("RESOLVED" if result and result.returncode == 0 else "FAILED", row["id"]),
                )
        time.sleep(1)


if __name__ == "__main__":
    main()
