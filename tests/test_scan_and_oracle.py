"""Fix 1 (sequential correctness) + Fix 5 (enumeration oracle) via the real
HTTP endpoint. The concurrency proof for Fix 1 is in test_race_mysql.py."""


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_single_scan_credits_once(client, seed):
    r = client.post("/scan", json={"code": "TOKCHILD"}, headers=_auth(seed["rtoken"]))
    assert r.status_code == 200
    body = r.json()
    assert body["points_awarded"] == 10
    assert body["new_balance"] == 10

    # Second scan of the same code must NOT credit again.
    r2 = client.post("/scan", json={"code": "TOKCHILD"}, headers=_auth(seed["rtoken"]))
    assert r2.status_code == 409
    w = client.get("/retailer/wallet", headers=_auth(seed["rtoken"]))
    assert w.json()["balance"] == 10  # unchanged


def test_manual_code_scan(client, seed):
    r = client.post("/scan", json={"code": "aaaaaa"}, headers=_auth(seed["rtoken"]))
    assert r.status_code == 200
    assert r.json()["points_awarded"] == 10


def test_enumeration_oracle_uniform_404(client, seed):
    """A non-existent code and a real code owned by ANOTHER manufacturer must be
    indistinguishable: identical status code AND identical detail message."""
    from app.database import get_db
    from app.auth import hash_password
    # A second manufacturer with its own code.
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name, is_admin)"
            " VALUES (?,?,?,0)", ("other", hash_password("x"), "Other Co"))
        omid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO products (manufacturer_id, name, sku, loyalty_points)"
            " VALUES (?,?,?,?)", (omid, "Other", "SKU-O", 5))
        opid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO qr_batches (product_id, quantity, points_per_code)"
            " VALUES (?,?,?)", (opid, 1, 5))
        obid = cur.lastrowid
        db.execute(
            "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent, parent_token)"
            " VALUES (?,?,?,0,NULL)", ("OTHERTOKEN", "BBBBBB", obid))

    nonexistent = client.post("/scan", json={"code": "ZZZZZZ"}, headers=_auth(seed["rtoken"]))
    cross = client.post("/scan", json={"code": "OTHERTOKEN"}, headers=_auth(seed["rtoken"]))
    assert nonexistent.status_code == cross.status_code == 404
    assert nonexistent.json()["detail"] == cross.json()["detail"] == "Invalid code"


def test_box_parent_child(client, seed):
    """A box scan registers all unredeemed children once; a re-scan is a 409 and
    credits nothing more."""
    from app.database import get_db
    with get_db() as db:
        # two more children under a parent box
        for tok, man in (("BOXCHILD1", "CCCCCC"), ("BOXCHILD2", "DDDDDD")):
            db.execute(
                "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent, parent_token)"
                " VALUES (?,?,?,0,?)", (tok, man, seed["bid"], "BOXPARENT"))
        db.execute(
            "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent, parent_token)"
            " VALUES (?,?,?,1,NULL)", ("BOXPARENT", "EEEEEE", seed["bid"]))

    r = client.post("/scan", json={"code": "BOXPARENT"}, headers=_auth(seed["rtoken"]))
    assert r.status_code == 200
    body = r.json()
    assert body["is_box"] is True
    assert body["items_registered"] == 2
    assert body["points_awarded"] == 20

    r2 = client.post("/scan", json={"code": "BOXPARENT"}, headers=_auth(seed["rtoken"]))
    assert r2.status_code == 409
    assert client.get("/retailer/wallet", headers=_auth(seed["rtoken"])).json()["balance"] == 20
