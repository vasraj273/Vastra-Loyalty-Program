"""Fix 2 (sequential correctness) via the real endpoint. Concurrency proof is
in test_race_mysql.py."""


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _gift(mid, cost):
    from app.database import get_db
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO gifts (manufacturer_id, name, description, points_cost, active)"
            " VALUES (?,?,?,?,1)", (mid, "Mug", "", cost))
        return cur.lastrowid


def test_claim_deducts_and_blocks_overspend(client, seed):
    # earn 10 points
    client.post("/scan", json={"code": "TOKCHILD"}, headers=_auth(seed["rtoken"]))
    gid = _gift(seed["mid"], 10)

    r = client.post("/retailer/claim", json={"gift_id": gid}, headers=_auth(seed["rtoken"]))
    assert r.status_code == 201
    assert r.json()["new_balance"] == 0

    # second claim must fail — balance exhausted, wallet never negative
    r2 = client.post("/retailer/claim", json={"gift_id": gid}, headers=_auth(seed["rtoken"]))
    assert r2.status_code == 409
    assert client.get("/retailer/wallet", headers=_auth(seed["rtoken"])).json()["balance"] == 0


def test_claim_insufficient_balance(client, seed):
    gid = _gift(seed["mid"], 1000)
    r = client.post("/retailer/claim", json={"gift_id": gid}, headers=_auth(seed["rtoken"]))
    assert r.status_code == 409
    assert client.get("/retailer/wallet", headers=_auth(seed["rtoken"])).json()["balance"] == 0
