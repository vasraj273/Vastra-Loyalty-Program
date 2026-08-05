"""Retailer import: a blank shop cell falls back to the owner's name.

The client's real customer export carries *both* a "Firm Name" and a "Name"
column, and only some rows fill the firm in — an individual retailer trading
under their own name leaves it blank. `_pick_col` resolves shop -> "Firm Name"
(alias order puts firm_name ahead of name), so those rows used to be rejected
as "missing shop name" even though the row plainly identifies a retailer. A
2230-row file lost 420 of them that way.
"""


def auth(client, username="acme", password="acmepass"):
    r = client.post("/auth/login", json={"username": username,
                                         "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def imp(client, headers, csv):
    return client.post("/retailers/import", json={"csv": csv}, headers=headers)


def by_shop(client, headers):
    rows = client.get("/retailers", headers=headers).json()
    return {r["shop_name"]: r for r in rows}


# Shaped like the client's export: Firm Name present on some rows, blank or
# "null" on others, with Name always filled.
MIXED_CSV = (
    "Firm Name,Name,Mobile,City,Point Balance\n"
    "Shanti collection,Shanti Lal,9825745754,Junagadh,600\n"
    ",Mahesh Kumar,9825745755,Surat,700\n"
    "null,Ramesh Patel,9825745756,Rajkot,800\n"
    '"   ",Dinesh Shah,9825745757,Vadodara,900\n'
)


def test_blank_firm_name_falls_back_to_the_person_name(client, seed):
    headers = auth(client)
    r = imp(client, headers, MIXED_CSV)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 4, body["errors"]
    assert body["errors"] == []

    shops = by_shop(client, headers)
    assert shops["Shanti collection"]["name"] == "Shanti Lal"
    # Rows with no firm are filed under the person's name, both fields.
    for person in ("Mahesh Kumar", "Ramesh Patel", "Dinesh Shah"):
        assert shops[person]["name"] == person
    assert body["points_credited"] == 600 + 700 + 800 + 900


def test_row_with_neither_shop_nor_name_is_still_an_error(client, seed):
    headers = auth(client)
    r = imp(client, headers,
            "Firm Name,Name,Mobile\n"
            "Real shop,Owner,9825700001\n"
            ",,9825700002\n"
            "null,null,9825700003\n")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert len(body["errors"]) == 2
    assert all("missing shop name" in e for e in body["errors"])


def test_fallback_row_still_gets_a_login_and_a_distributor(client, seed):
    headers = auth(client)
    r = imp(client, headers,
            "Firm Name,Name,Mobile,distributor_name\n"
            ",Kailash Traders,9825700010,Western Agency\n")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["credentials"][0]["username"] == "kailash"
    dists = client.get("/distributors", headers=headers).json()
    assert any(d["name"] == "Western Agency" for d in dists)
