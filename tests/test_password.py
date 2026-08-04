"""Fix 3: retailer credential security."""


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _manuf_token(client):
    r = client.post("/auth/login", json={"username": "acme", "password": "acmepass"})
    assert r.status_code == 200
    return r.json()["token"]


def test_new_retailer_password_is_random(client, seed):
    mtok = _manuf_token(client)
    r = client.post("/retailers",
                    json={"name": "Sun", "shop_name": "Sunrise Store", "region": "Surat"},
                    headers=_auth(mtok))
    assert r.status_code == 201
    body = r.json()
    user, pw = body["login_username"], body["login_password"]
    assert user == "sunrise"
    # The crux: password must NOT be the old deterministic "<username>123".
    assert pw != f"{user}123"
    assert len(pw) >= 12
    assert body["must_change"] == 1  # forced change flagged

    # The generated password actually logs in, and login advertises must_change.
    lr = client.post("/auth/retailer/login", json={"username": user, "password": pw})
    assert lr.status_code == 200
    assert lr.json()["must_change"] is True


def test_password_change_flow(client, seed):
    # seed retailer 'ravi' has temp password 'TempPass123', must_change=1
    lr = client.post("/auth/retailer/login", json={"username": "ravi", "password": "TempPass123"})
    assert lr.json()["must_change"] is True
    rtok = lr.json()["token"]

    # wrong current password rejected
    bad = client.post("/retailer/password",
                      json={"current_password": "WRONG", "new_password": "BrandNew99"},
                      headers=_auth(rtok))
    assert bad.status_code == 401

    # new == current rejected
    same = client.post("/retailer/password",
                       json={"current_password": "TempPass123", "new_password": "TempPass123"},
                       headers=_auth(rtok))
    assert same.status_code == 422

    # too-short new password rejected by validation
    short = client.post("/retailer/password",
                        json={"current_password": "TempPass123", "new_password": "short"},
                        headers=_auth(rtok))
    assert short.status_code == 422

    # valid change succeeds, clears must_change
    ok = client.post("/retailer/password",
                     json={"current_password": "TempPass123", "new_password": "BrandNew99"},
                     headers=_auth(rtok))
    assert ok.status_code == 200

    # old password no longer works; new one does and must_change is cleared
    assert client.post("/auth/retailer/login",
                       json={"username": "ravi", "password": "TempPass123"}).status_code == 401
    relog = client.post("/auth/retailer/login",
                        json={"username": "ravi", "password": "BrandNew99"})
    assert relog.status_code == 200
    assert relog.json()["must_change"] is False


def test_login_is_case_sensitive(client, seed):
    """Usernames are credentials: they match byte-for-byte, like the password
    and the session token. Backend-independent (the app no longer case-folds;
    the MySQL column additionally carries COLLATE utf8mb4_bin)."""
    ok = client.post("/auth/retailer/login",
                     json={"username": "ravi", "password": "TempPass123"})
    assert ok.status_code == 200, ok.text

    for wrong in ("Ravi", "RAVI", "rAvI"):
        r = client.post("/auth/retailer/login",
                        json={"username": wrong, "password": "TempPass123"})
        assert r.status_code == 401, f"{wrong!r} should not log in: {r.text}"

    # ...and the password itself stays case-sensitive (it always was: PBKDF2 is
    # verified in Python, never compared by the database).
    for wrong_pw in ("temppass123", "TEMPPASS123"):
        r = client.post("/auth/retailer/login",
                        json={"username": "ravi", "password": wrong_pw})
        assert r.status_code == 401, f"{wrong_pw!r} should not log in"
