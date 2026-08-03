"""Fix 1 & Fix 2 concurrency proof on real MySQL.

Skipped unless DATABASE_URL points at a MySQL instance. Runs the proof in a
subprocess so it gets a clean MySQL-bound import (the rest of the suite runs on
SQLite within this process).

    DATABASE_URL=mysql://user:pass@host:3306/db pytest tests/test_race_mysql.py -s
"""
import os
import subprocess
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(__file__), "_mysql_race_runner.py")


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                    reason="set DATABASE_URL (MySQL) to run the concurrency proof")
def test_scan_and_claim_single_reward_under_concurrency():
    # PYTHONPATH: the runner is executed as a script, so its own dir
    # (tests/) lands on sys.path -- not the repo root that holds app/.
    env = dict(os.environ, RL_ENABLED="0",
               PYTHONPATH=os.path.dirname(os.path.dirname(__file__)))
    proc = subprocess.run([sys.executable, RUNNER], env=env,
                          capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(__file__)))
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    assert proc.returncode == 0, "concurrency proof failed (see output above)"
    assert "PASS" in proc.stdout
