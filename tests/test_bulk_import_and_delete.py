"""Bulk CSV import and "Delete all" for retailers, rewards and distributors.

Every CSV below uses the **verbatim header row** of the manufacturer's real
export, because that is the whole point of the feature: their file imports as
it comes out of their other system, with no hand-edited headers. The rows are a
representative slice of the real data — repeated owner names on different
phones, blank cities, literal "null" cells, quoted names with trailing spaces,
and images written as a JSON array.
"""


def auth(client, username="acme", password="acmepass"):
    r = client.post("/auth/login", json={"username": username,
                                         "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def rauth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- retailers

# Real header. Note there is no shop column at all — "Name" has to serve as
# both shop and owner — and the phone/city/address columns are theirs, not ours.
RETAILER_CSV = (
    "Name,Email,Mobile,User Type,gender,whatsapp_number,city,state,district,"
    "address1,pincode,lat,log,Point Earned,"
    "Total Point Redeemed (As of Current Date),Point Balance\n"
    "Sankalp Ahluwalia,null,9828995109,retailer,null,null,Sriganganagar,"
    "Rajasthan,null,\"Sankalp Ahluwalia \",335001,null,null,0.00,0.00,0.00\n"
    "Omprakash manwani,Ommanwani64@gmail.com,7517531888,retailer,null,null,"
    "Dhule Collectorate,Maharashtra,null,\"Kumar nagar,dhule\",424001,null,"
    "null,0.00,0.00,0.00\n"
    # Same first name as a later row but a different phone: both are real,
    # separate shops and both must import.
    "Akshay,null,7874355939,retailer,null,null,Ankleshwar Ie,Gujarat,null,"
    "null,393002,null,null,0.00,0.00,0.00\n"
    "Akshay,akash.agarwal31@yahoo.com,9766088631,retailer,null,null,Lonavala,"
    "Maharashtra,null,\"Lonavala \",410401,null,null,5288.00,0.00,5288.00\n"
    # Blank city (the file has these) — region stays empty, import still works.
    "Test Ganesh,null,9808558555,retailer,null,null,,,,null,,null,null,"
    "2070.00,0.00,2070.00\n"
)


def test_real_retailer_export_maps_every_column(client, seed):
    headers = auth(client)
    r = client.post("/retailers/import", json={"csv": RETAILER_CSV},
                    headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 5
    assert body["columns"] == {
        "shop_name": "Name", "name": "Name", "phone": "Mobile",
        "region": "city",  # city beats state — the more precise pin
        "address": "address1", "distributor": None,
        # The file carries three points columns; the balance is the wallet,
        # "Point Earned" and the redeemed total are its history and are not read.
        "points": "Point Balance", "external_id": None,
    }
    assert body["points_credited"] == 5288 + 2070

    rows = {x["shop_name"]: x for x in client.get("/retailers",
                                                  headers=headers).json()}
    assert rows["Sankalp Ahluwalia"]["phone"] == "9828995109"
    assert rows["Sankalp Ahluwalia"]["region"] == "Sriganganagar"
    assert rows["Sankalp Ahluwalia"]["address"] == "Sankalp Ahluwalia"
    assert rows["Omprakash manwani"]["address"] == "Kumar nagar,dhule"
    # "null" cells never reach the table.
    assert rows["Test Ganesh"]["address"] is None
    assert rows["Test Ganesh"]["region"] == ""
    # The carried-over balance lands in the wallet without inventing scans.
    assert rows["Test Ganesh"]["points"] == 2070
    assert rows["Test Ganesh"]["scans"] == 0
    assert rows["Sankalp Ahluwalia"]["points"] == 0


def test_same_name_different_phone_both_import(client, seed):
    """Phone is the identity key, so two shops named "Akshay" both survive."""
    headers = auth(client)
    assert client.post("/retailers/import", json={"csv": RETAILER_CSV},
                       headers=headers).json()["created"] == 5
    akshays = [x for x in client.get("/retailers", headers=headers).json()
               if x["shop_name"] == "Akshay"]
    assert sorted(x["phone"] for x in akshays) == ["7874355939", "9766088631"]


def test_reimport_skips_on_phone(client, seed):
    headers = auth(client)
    client.post("/retailers/import", json={"csv": RETAILER_CSV},
                headers=headers)
    again = client.post("/retailers/import", json={"csv": RETAILER_CSV},
                        headers=headers).json()
    assert (again["created"], again["skipped"]) == (0, 5)


def test_retailer_header_aliases_and_distributor_link(client, seed):
    """Our own documented spellings still work, and a distributor column
    find-or-creates and links."""
    headers = auth(client)
    csv = ("shop_name,name,region,Contact No,distributor,external_id\n"
           "Kumar Textiles,Ravi Kumar,Surat,9876500001,KAILASH HOSIERY,YA-1\n")
    r = client.post("/retailers/import", json={"csv": csv}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["columns"]["phone"] == "Contact No"
    row = [x for x in client.get("/retailers", headers=headers).json()
           if x["shop_name"] == "Kumar Textiles"][0]
    assert row["name"] == "Ravi Kumar" and row["external_id"] == "YA-1"
    dist = client.get("/distributors", headers=headers).json()
    assert [d["name"] for d in dist] == ["KAILASH HOSIERY"]
    assert row["distributor_id"] == dist[0]["id"]


def test_retailer_import_needs_a_name_column(client, seed):
    headers = auth(client)
    r = client.post("/retailers/import",
                    json={"csv": "Email,Mobile\na@b.c,9828995109\n"},
                    headers=headers)
    assert r.status_code == 422
    assert "shop or name column" in r.json()["detail"]


# ----------------------------------------------------------------- gifts

# Real header. Points live in "Product Points", the image is a JSON array, and
# "Value" is theirs alone (loyalty has nowhere to put it, so it is dropped).
GIFT_CSV = (
    "brand,category,Name,Product Points,Value,images,description\n"
    "HONDA,Automobiles,HONDA SP 125 BIKE EX- SHOWROOM,179999,179999,"
    "\"[\"\"https://example.s3.amazonaws.com/honda.jpg\"\"]\",null\n"
    "IPHONE,Smartphone,IPHONE-15 (128 GB),124999,124999,"
    "\"[\"\"https://example.s3.amazonaws.com/iphone.jpg\"\"]\",null\n"
    # A name containing commas, quoted in the file.
    "SMART PHONE,Smartphone,\"SMART PHONE UNDER RS.10,000 MI/ REALME/ VIVO\","
    "19999,19999,\"[\"\"https://example.s3.amazonaws.com/phone.jpg\"\"]\",null\n"
    # Inch marks inside a quoted cell, doubled the way the real file writes them.
    "COMFORTER,Other,\"COMFORTER SIZE- SINGLE (60\"\" X 90\"\")\",1499,"
    "1499,\"[\"\"undefined\"\"]\",Cotton\n"
)


def test_real_gift_export_maps_every_column(client, seed):
    headers = auth(client)
    r = client.post("/gifts/import", json={"csv": GIFT_CSV}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 4, body
    assert body["columns"] == {
        "name": "Name", "points_cost": "Product Points",
        "description": "description", "image_url": "images",
    }

    rows = {g["name"]: g for g in client.get("/gifts", headers=headers).json()}
    honda = rows["HONDA SP 125 BIKE EX- SHOWROOM"]
    assert honda["points_cost"] == 179999
    # The JSON array is unwrapped to the single URL the shop can render.
    assert honda["image_url"] == "https://example.s3.amazonaws.com/honda.jpg"
    assert honda["description"] == ""  # literal "null" blanked
    assert "SMART PHONE UNDER RS.10,000 MI/ REALME/ VIVO" in rows
    comforter = rows['COMFORTER SIZE- SINGLE (60" X 90")']
    # ["undefined"] is their placeholder for "no image", not a URL.
    assert comforter["image_url"] is None
    assert comforter["description"] == "Cotton"


def test_gift_import_plain_url_and_our_own_spellings(client, seed):
    headers = auth(client)
    csv = ("reward_name,points,description,image\n"
           "Mixer Grinder,14999,Sujata / Boss,https://example.com/mixer.jpg\n")
    r = client.post("/gifts/import", json={"csv": csv}, headers=headers)
    assert r.status_code == 200, r.text
    g = client.get("/gifts", headers=headers).json()[0]
    assert g["points_cost"] == 14999
    assert g["image_url"] == "https://example.com/mixer.jpg"


def test_gift_import_requires_name_and_points(client, seed):
    headers = auth(client)
    r = client.post("/gifts/import", json={"csv": "brand,Value\nHONDA,1799\n"},
                    headers=headers)
    assert r.status_code == 422
    assert "reward name column" in r.json()["detail"]
    assert "points column" in r.json()["detail"]


def test_gift_import_rejects_unusable_points(client, seed):
    headers = auth(client)
    csv = ("Name,Product Points\nGood Reward,500\nFree Thing,0\nJunk,abc\n")
    body = client.post("/gifts/import", json={"csv": csv},
                       headers=headers).json()
    assert (body["created"], body["skipped"]) == (1, 2)
    assert [g["name"] for g in client.get("/gifts", headers=headers).json()] \
        == ["Good Reward"]


def test_gift_reimport_skips_existing_names(client, seed):
    headers = auth(client)
    assert client.post("/gifts/import", json={"csv": GIFT_CSV},
                       headers=headers).json()["created"] == 4
    again = client.post("/gifts/import", json={"csv": GIFT_CSV},
                        headers=headers).json()
    assert (again["created"], again["skipped"]) == (0, 4)


# ------------------------------------------------------------ delete all

def test_delete_all_retailers_keeps_those_with_history(client, seed):
    """seed's retailer has scanned, so it survives; imported ones do not."""
    headers = auth(client)
    client.post("/retailers/import", json={"csv": RETAILER_CSV},
                headers=headers)
    assert client.post("/scan", json={"code": "TOKCHILD"},
                       headers=rauth(seed["rtoken"])).status_code == 200
    assert len(client.get("/retailers", headers=headers).json()) == 6

    res = client.delete("/retailers", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"deleted": 5, "skipped": 1}
    left = client.get("/retailers", headers=headers).json()
    assert [r["shop_name"] for r in left] == ["Ravi Shop"]
    # The kept retailer's wallet is untouched.
    assert left[0]["points"] == 10


def test_delete_all_clears_imported_opening_balances(client, seed):
    """A carried-over balance must not make a bad import un-undoable.

    RETAILER_CSV credits two shops from its "Point Balance" column. Those
    'import_opening' ledger rows are part of the import, so Delete all takes
    them with the retailer — unlike a scan, a claim or a manual adjustment,
    which keep their retailer alive."""
    headers = auth(client)
    client.post("/retailers/import", json={"csv": RETAILER_CSV},
                headers=headers)
    assert client.post("/scan", json={"code": "TOKCHILD"},
                       headers=rauth(seed["rtoken"])).status_code == 200
    rows = client.get("/retailers", headers=headers).json()
    imported = [r for r in rows if r["shop_name"] != "Ravi Shop"]
    assert sum(r["points"] for r in imported) == 5288 + 2070, "balances imported"

    # Give one imported shop real history: it must now survive the clear.
    kept = next(r for r in rows if r["shop_name"] == "Test Ganesh")
    assert client.post(f"/retailers/{kept['id']}/adjust",
                       json={"points": 5, "note": "manual"},
                       headers=headers).status_code == 200

    res = client.delete("/retailers", headers=headers)
    assert res.status_code == 200, res.text
    # 5 imported + seed's Ravi Shop = 6; Ravi scanned, Test Ganesh was adjusted.
    assert res.json() == {"deleted": 4, "skipped": 2}
    left = {r["shop_name"]: r for r in client.get("/retailers",
                                                  headers=headers).json()}
    assert set(left) == {"Ravi Shop", "Test Ganesh"}
    # The survivor keeps its imported balance plus the adjustment.
    assert left["Test Ganesh"]["points"] == 2075


def test_delete_one_retailer_clears_its_opening_balance(client, seed):
    """Same rule on the single-row delete: an imported balance alone does not
    409, but any other ledger row still does."""
    headers = auth(client)
    client.post("/retailers/import", json={"csv": RETAILER_CSV},
                headers=headers)
    rows = {r["shop_name"]: r for r in client.get("/retailers",
                                                  headers=headers).json()}
    ganesh = rows["Test Ganesh"]
    assert ganesh["points"] == 2070

    assert client.delete(f"/retailers/{ganesh['id']}",
                         headers=headers).status_code == 204
    assert "Test Ganesh" not in {
        r["shop_name"] for r in client.get("/retailers", headers=headers).json()}

    # A shop with a real scan is still protected.
    ravi = rows["Ravi Shop"]
    assert client.post("/scan", json={"code": "TOKCHILD"},
                       headers=rauth(seed["rtoken"])).status_code == 200
    assert client.delete(f"/retailers/{ravi['id']}",
                         headers=headers).status_code == 409


def test_delete_all_retailers_is_tenant_scoped(client, seed):
    """Another manufacturer's customers are never touched."""
    from app.auth import hash_password
    from app.database import get_db
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name,"
            " is_admin) VALUES (?,?,?,0)",
            ("other", hash_password("otherpass"), "Other Co"))
        db.execute(
            "INSERT INTO retailers (manufacturer_id, name, shop_name, region)"
            " VALUES (?,?,?,?)", (cur.lastrowid, "X", "Other Shop", "Surat"))

    headers = auth(client)
    client.post("/retailers/import", json={"csv": RETAILER_CSV},
                headers=headers)
    assert client.delete("/retailers", headers=headers).json()["deleted"] == 6

    other = auth(client, "other", "otherpass")
    assert [r["shop_name"] for r in client.get("/retailers",
                                               headers=other).json()] \
        == ["Other Shop"]


def test_delete_all_gifts_keeps_claimed_rewards(client, seed):
    headers = auth(client)
    client.post("/gifts/import", json={"csv": GIFT_CSV}, headers=headers)
    gifts = client.get("/gifts", headers=headers).json()
    cheap = min(gifts, key=lambda g: g["points_cost"])

    # Give the retailer enough points, then claim the cheapest reward.
    client.post(f"/retailers/{seed['rid']}/adjust",
                json={"points": cheap["points_cost"], "note": "test float"},
                headers=headers)
    claim = client.post("/retailer/claim", json={"gift_id": cheap["id"]},
                        headers=rauth(seed["rtoken"]))
    assert claim.status_code in (200, 201), claim.text

    res = client.delete("/gifts", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"deleted": 3, "skipped": 1}
    assert [g["name"] for g in client.get("/gifts", headers=headers).json()] \
        == [cheap["name"]]


def test_delete_all_distributors_unlinks_retailers(client, seed):
    headers = auth(client)
    csv = ("shop_name,phone,distributor\n"
           "Kumar Textiles,9876500001,KAILASH HOSIERY\n")
    client.post("/retailers/import", json={"csv": csv}, headers=headers)
    assert len(client.get("/distributors", headers=headers).json()) == 1

    res = client.delete("/distributors", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"deleted": 1}
    assert client.get("/distributors", headers=headers).json() == []
    # The retailer is unlinked, never deleted.
    row = [r for r in client.get("/retailers", headers=headers).json()
           if r["shop_name"] == "Kumar Textiles"][0]
    assert row["distributor_id"] is None
