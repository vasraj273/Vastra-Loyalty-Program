"""`status` and `qrStatus` on the three YourApp server-to-server endpoints.

`status` is a boolean answering one question for YourApp's backend: did the
call work? True means the API did its job (even when the answer is "no data"),
False means it did not. HTTP codes are unchanged — this is a second,
easier-to-read signal, not a replacement.

`qrStatus` is a separate string carrying the *code's* own state
("available"/"redeemed"), on /yourapp/qr/lookup only. The two must never be
merged: an already-redeemed code is a perfectly successful call, so it returns
status True with qrStatus "redeemed".

Both are scoped to /yourapp/*: nothing the panel or the webviews call may grow
either field.
"""
import pytest

KEY = "test-yourapp-key"
H = {"X-API-Key": KEY}


@pytest.fixture(autouse=True)
def enable_yourapp(appmod, monkeypatch):
    monkeypatch.setattr(appmod, "YOURAPP_API_KEY", KEY)


@pytest.fixture()
def phone_seed(seed, db):
    """The seeded retailer with a phone — how /yourapp/* identifies them."""
    with db() as conn:
        conn.execute("UPDATE retailers SET phone = ? WHERE id = ?",
                     ("9876500001", seed["rid"]))
    return seed


# ---------- success: status True ----------

def test_lookup_ok_is_true(client, phone_seed):
    r = client.post("/yourapp/qr/lookup",
                    json={"code": phone_seed["token"]}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] is True           # the call worked
    assert body["qrStatus"] == "available"  # the code is unused
    assert body["total_points"] == 10


def test_points_ok_is_true(client, phone_seed):
    r = client.post("/yourapp/points", json={"phone": "9876500001"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["status"] is True
    assert r.json()["total_points"] == 0


def test_scan_ok_is_true(client, phone_seed):
    r = client.post("/yourapp/scan",
                    json={"phone": "9876500001", "code": phone_seed["token"]},
                    headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] is True
    # Scan reports the outcome through `redeemed`, as it always has —
    # qrStatus belongs to the lookup endpoint only.
    assert "qrStatus" not in body
    assert body["redeemed"] is True
    assert body["points_awarded"] == 10


def test_already_redeemed_is_still_true(client, phone_seed):
    """The case the split exists for: a code already used is NOT a failure.
    The API worked — it is the code that has nothing left to give."""
    client.post("/yourapp/scan",
                json={"phone": "9876500001", "code": phone_seed["token"]},
                headers=H)
    r = client.post("/yourapp/qr/lookup",
                    json={"code": phone_seed["token"]}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] is True
    assert body["qrStatus"] == "redeemed"


def test_status_is_never_a_string(client, phone_seed):
    """Guards the rename: `status` must stay boolean on every endpoint, with
    the code's state living only in `qrStatus`."""
    for path, payload in (
        ("/yourapp/qr/lookup", {"code": phone_seed["token"]}),
        ("/yourapp/points", {"phone": "9876500001"}),
        ("/yourapp/scan", {"phone": "9876500001", "code": phone_seed["token"]}),
    ):
        body = client.post(path, json=payload, headers=H).json()
        assert isinstance(body["status"], bool), f"{path} -> {body['status']!r}"


# ---------- failure: status False ----------

def test_unknown_code_is_false(client, phone_seed):
    r = client.post("/yourapp/qr/lookup", json={"code": "nosuchcode"}, headers=H)
    assert r.status_code == 404
    assert r.json()["status"] is False
    assert r.json()["detail"] == "Invalid code"


def test_scan_unknown_code_is_false(client, phone_seed):
    r = client.post("/yourapp/scan",
                    json={"phone": "9876500001", "code": "nosuchcode"}, headers=H)
    assert r.status_code == 404
    assert r.json()["status"] is False


def test_unregistered_phone_is_false(client, phone_seed):
    r = client.post("/yourapp/points", json={"phone": "9000000009"}, headers=H)
    assert r.status_code == 403
    assert r.json()["status"] is False


def test_bad_api_key_is_false(client, phone_seed):
    r = client.post("/yourapp/points", json={"phone": "9876500001"},
                    headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json()["status"] is False


def test_missing_api_key_is_false(client, phone_seed):
    r = client.post("/yourapp/points", json={"phone": "9876500001"})
    assert r.status_code == 401
    assert r.json()["status"] is False


def test_integration_switched_off_is_false(client, phone_seed, appmod,
                                           monkeypatch):
    monkeypatch.setattr(appmod, "YOURAPP_API_KEY", "")
    r = client.post("/yourapp/points", json={"phone": "9876500001"}, headers=H)
    assert r.status_code == 503
    assert r.json()["status"] is False


def test_validation_error_is_false(client, phone_seed):
    """Raised by pydantic before the endpoint body ever runs."""
    r = client.post("/yourapp/qr/lookup", json={}, headers=H)
    assert r.status_code == 422
    assert r.json()["status"] is False


def test_short_phone_is_false(client, phone_seed):
    r = client.post("/yourapp/points", json={"phone": "123"}, headers=H)
    assert r.status_code == 422
    assert r.json()["status"] is False


def test_crash_answers_false_instead_of_dying(appmod, phone_seed, monkeypatch):
    """The case the flag exists for: the API is genuinely broken. It must
    still answer, with status False, rather than an empty 500."""
    from starlette.testclient import TestClient

    def boom(*a, **kw):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(appmod, "_norm_phone", boom)
    with TestClient(appmod.app, raise_server_exceptions=False) as c:
        r = c.post("/yourapp/points", json={"phone": "9876500001"}, headers=H)
    assert r.status_code == 500
    assert r.json()["status"] is False


# ---------- scope: everything else is untouched ----------

def test_panel_login_has_no_flag(client, phone_seed):
    r = client.post("/auth/login", json={"username": "acme", "password": "acmepass"})
    assert r.status_code == 200
    assert "status" not in r.json()


def test_panel_error_shape_unchanged(client, phone_seed):
    r = client.post("/auth/login", json={"username": "acme", "password": "wrong"})
    assert r.status_code == 401
    assert "status" not in r.json()
    assert r.json()["detail"]


def test_webview_scan_has_no_flag(client, phone_seed):
    """The retailer webview's own POST /scan keeps its exact shape."""
    r = client.post("/scan", json={"code": phone_seed["token"]},
                    headers={"Authorization": f"Bearer {phone_seed['rtoken']}"})
    assert r.status_code == 200, r.text
    assert "status" not in r.json()
    assert "qrStatus" not in r.json()
    assert r.json()["redeemed"] is True


def test_panel_schemes_status_untouched(client, phone_seed):
    """The panel's own `status` strings (scheme active/upcoming/previous) are
    a different field on a different endpoint and must not be disturbed."""
    login = client.post("/auth/login",
                        json={"username": "acme", "password": "acmepass"}).json()
    auth = {"Authorization": f"Bearer {login['token']}"}
    client.post("/schemes", json={"name": "Diwali", "bonus_points": 5,
                                  "start_date": "2020-01-01",
                                  "end_date": "2099-01-01"}, headers=auth)
    rows = client.get("/schemes", headers=auth).json()
    assert rows[0]["status"] == "active"
