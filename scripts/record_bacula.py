"""Import actual Bacula Catalog job evidence; no browser-supplied success statuses."""

import argparse
import json
import subprocess
from pathlib import Path

from psycopg.types.json import Jsonb

from aegis.db import connection
from scripts.backup_export import digest


def catalog_job(job_id):
    if not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Positive catalog JobId required")
    query = f"SELECT row_to_json(j) FROM (SELECT jobid,name,type,jobstatus,jobfiles,jobbytes,starttime,endtime FROM job WHERE jobid={job_id}) j"
    raw = subprocess.check_output(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "infra/compose.bacula.yaml",
            "exec",
            "-T",
            "bacula",
            "runuser",
            "-u",
            "postgres",
            "--",
            "psql",
            "-d",
            "bacula",
            "-tAc",
            query,
        ],
        text=True,
    )
    return json.loads(raw.strip())


def record(directory, job_id):
    manifest_path = Path(directory) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    job = catalog_job(job_id)
    if job["type"] != "B" or job["jobstatus"] != "T":
        raise ValueError("Selected Bacula backup did not complete successfully")
    metadata = {
        **manifest,
        "bacula": job,
        "evidence_scope": "Catalog success; use isolated restore report to establish recoverability",
    }
    with connection() as c:
        c.execute(
            "INSERT INTO backup_jobs(job_id,status,artifact_path,checksum,metadata) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,metadata=excluded.metadata",
            ("bacula-" + str(job_id), "BACULA_COMPLETED", str(directory), digest(manifest_path), Jsonb(metadata)),
        )
    return metadata


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory")
    p.add_argument("--job-id", type=int, required=True)
    args = p.parse_args()
    print(json.dumps(record(args.directory, args.job_id), indent=2))
