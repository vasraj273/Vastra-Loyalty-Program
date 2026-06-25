"""Fix 4: rate limiting is wired and enforced. Reloads the app with limiting
enabled and a low login limit, in isolation, then restores the disabled state
so other tests stay deterministic."""
import importlib
import os

from starlette.testclient import TestClient


def test_login_is_rate_limited(appmod):
    os.environ["RL_ENABLED"] = "1"
    os.environ["RL_LOGIN"] = "3/minute"
    try:
        importlib.reload(appmod)  # rebuild app + limiter from current env
        with TestClient(appmod.app) as client:
            codes = [
                client.post("/auth/login",
                            json={"username": "nobody", "password": "x"}).status_code
                for _ in range(6)
            ]
        # First few are 401 (bad creds), then the limiter trips with 429.
        assert 429 in codes, codes
        assert codes.index(429) >= 3  # not before the configured budget
    finally:
        os.environ["RL_ENABLED"] = "0"
        os.environ.pop("RL_LOGIN", None)
        importlib.reload(appmod)  # restore disabled limiter for remaining tests
