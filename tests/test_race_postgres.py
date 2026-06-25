"""Fix 1 & Fix 2 concurrency proof on real PostgreSQL.

Skipped unless DATABASE_URL points at a Postgres instance. Runs the proof in a
subprocess so it gets a clean PG-bound import (the rest of the suite runs on
SQLite within this process).

    DATABASE_URL=postgresql://user:pass@host/db pytest tests/test_race_postgres.py -s
"""
import os
import subprocess
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(__file__), "_pg_race_runner.py")


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                    reason="set DATABASE_URL (Postgres) to run the concurrency proof")
def test_scan_and_claim_single_reward_under_concurrency():
    env = dict(os.environ, RL_ENABLED="0")
    proc = subprocess.run([sys.executable, RUNNER], env=env,
                          capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(__file__)))
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    assert proc.returncode == 0, "concurrency proof failed (see output above)"
    assert "PASS" in proc.stdout
