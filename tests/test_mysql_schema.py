"""MySQL-specific schema guarantees. Skipped unless DATABASE_URL points at a
MySQL instance, and run in a subprocess for the same reason as the race proof:
the rest of the suite imports app.database bound to SQLite in this process.

Covers the three things MySQL does differently from SQLite/Postgres, each of
which would otherwise fail silently (create_constraints swallows exceptions):

  1. Startup DDL is idempotent. MySQL has no CREATE INDEX IF NOT EXISTS or
     ADD COLUMN IF NOT EXISTS, so every statement is guarded by an
     information_schema lookup instead. A second deploy must be a clean no-op.
  2. uq_ledger_active_scan_token is rebuilt from a STORED generated column,
     because MySQL has no partial indexes. It must enforce one active scan per
     token AND release the token once the scan is reversed.
  3. Collation split: identifier columns compare case-sensitively (as they do
     on SQLite today), human-facing usernames case-insensitively.

    DATABASE_URL=mysql://user:pass@host:3306/db pytest tests/test_mysql_schema.py -s
"""
import os
import subprocess
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(__file__), "_mysql_schema_runner.py")


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                    reason="set DATABASE_URL (MySQL) to run the schema checks")
def test_mysql_ddl_idempotency_generated_column_and_collation():
    env = dict(os.environ,
               PYTHONPATH=os.path.dirname(os.path.dirname(__file__)))
    proc = subprocess.run([sys.executable, RUNNER], env=env,
                          capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(__file__)))
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    assert proc.returncode == 0, "MySQL schema checks failed (see output above)"
    assert "PASS" in proc.stdout
