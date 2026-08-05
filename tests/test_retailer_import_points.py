"""Retailer import: carrying the wallet balance and the distributor link over.

The manufacturer's customer list already holds a live points balance ("Point
Balance" in their export). Importing it used to land every shop at 0 points, so
the panel disagreed with the system the manufacturer actually runs on. The
balance now becomes one `adjustment` ledger row per new retailer — the wallet
and the Customers "Points" column pick it up, scan analytics do not.
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


# The client's real customer export, verbatim (decimal balances, "null" cells,
# trailing spaces in shop names, no distributor column).
REAL_CSV = (
    "Name,Email,Mobile,User Type,gender,Point Balance,City,pincode\n"
    "Paras hosiery,pmcreation99999@gmail.com,9879448245,retailer,null,14.00,Barvala,363641\n"
    '"Sadanad hosiery ",null,9420370793,retailer,null,0.00,null,424001\n'
    '"Shree Sai hosiery and cloth ",hemu91329132@gmail.com,9586889152,retailer,null,1005.00,Vadodara,390022\n'
    "Shanti hosieryendcosmetic,null,9825745754,retailer,null,6092.00,Junagadh,362002\n"
)


def test_point_balance_column_credits_the_wallet(client, seed):
    headers = auth(client)
    r = imp(client, headers, REAL_CSV)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 4
    # "Point Balance" must be the column that was read.
    assert body["columns"]["points"] == "Point Balance"
    assert body["points_credited"] == 14 + 0 + 1005 + 6092

    shops = by_shop(client, headers)
    assert shops["Paras hosiery"]["points"] == 14
    assert shops["Shree Sai hosiery and cloth"]["points"] == 1005
    assert shops["Shanti hosieryendcosmetic"]["points"] == 6092
    assert shops["Sadanad hosiery"]["points"] == 0


def test_opening_balance_is_not_scan_history(client, seed):
    """The wallet moves; the scan funnel does not. An imported balance is a
    carried-over number, not evidence anybody scanned a code."""
    headers = auth(client)
    assert imp(client, headers, REAL_CSV).status_code == 200

    shops = by_shop(client, headers)
    assert shops["Shanti hosieryendcosmetic"]["scans"] == 0

    before = client.get("/analytics/dashboard", headers=headers).json()
    assert before["totals"]["scans"] == 0
    assert before["totals"]["points_awarded"] == 0


def test_balance_survives_as_a_spendable_wallet(client, seed):
    """The imported points are real points: the retailer can spend them."""
    headers = auth(client)
    assert imp(client, headers, REAL_CSV).status_code == 200
    rid = by_shop(client, headers)["Shree Sai hosiery and cloth"]["id"]

    # Deducting more than the balance is still refused...
    over = client.post(f"/retailers/{rid}/adjust",
                       json={"points": -1006, "note": "test"}, headers=headers)
    assert over.status_code == 409
    # ...and deducting within it works, proving the 1005 is really there.
    ok = client.post(f"/retailers/{rid}/adjust",
                     json={"points": -1000, "note": "test"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["balance"] == 5


def test_reimport_does_not_double_credit(client, seed):
    """A duplicate row is skipped whole — including its balance — so importing
    the same list twice cannot inflate a wallet."""
    headers = auth(client)
    assert imp(client, headers, REAL_CSV).json()["created"] == 4
    again = imp(client, headers, REAL_CSV).json()
    assert again["created"] == 0
    assert again["skipped"] == 4
    assert again["points_credited"] == 0
    assert by_shop(client, headers)["Shanti hosieryendcosmetic"]["points"] == 6092


def test_points_cells_are_parsed_forgivingly(client, seed):
    """Thousands separators, currency noise and junk cells."""
    headers = auth(client)
    csv = (
        "Name,Mobile,Points Balance\n"
        "Comma Shop,9000000001,\"1,250.00\"\n"
        "Blank Shop,9000000002,null\n"
        "Junk Shop,9000000003,abc\n"
        "Negative Shop,9000000004,-50\n"
        "Round Shop,9000000005,10.6\n"
    )
    body = imp(client, headers, csv).json()
    assert body["created"] == 5
    shops = by_shop(client, headers)
    assert shops["Comma Shop"]["points"] == 1250
    assert shops["Blank Shop"]["points"] == 0
    assert shops["Junk Shop"]["points"] == 0
    assert shops["Round Shop"]["points"] == 11
    # A negative balance is refused, not silently applied — the wallet has no
    # concept of debt, and the manufacturer is told which row was odd.
    assert shops["Negative Shop"]["points"] == 0
    assert any("negative points" in e for e in body["errors"])


def test_no_points_column_still_imports(client, seed):
    headers = auth(client)
    csv = "Name,Mobile,City\nPlain Shop,9111111111,Surat\n"
    body = imp(client, headers, csv).json()
    assert body["created"] == 1
    assert body["columns"]["points"] is None
    assert body["points_credited"] == 0
    assert by_shop(client, headers)["Plain Shop"]["points"] == 0


def test_distributor_column_links_the_retailer(client, seed):
    """A distributor named in the customer list is found-or-created and linked,
    so the Customers tab's Distributor cell is filled in on import."""
    headers = auth(client)
    csv = (
        "Name,Mobile,City,Distributor,Point Balance\n"
        "Alpha Shop,9222222221,Surat,KAILASH HOSIERY,100.00\n"
        "Beta Shop,9222222222,Surat,KAILASH HOSIERY,200.00\n"
        "Gamma Shop,9222222223,Surat,MITTAL TRADERS,0.00\n"
    )
    body = imp(client, headers, csv).json()
    assert body["created"] == 3
    assert body["columns"]["distributor"] == "Distributor"

    shops = by_shop(client, headers)
    dists = {d["name"]: d for d in client.get("/distributors",
                                              headers=headers).json()}
    assert "KAILASH HOSIERY" in dists and "MITTAL TRADERS" in dists
    # Two shops share one distributor — it is created once, not twice.
    assert dists["KAILASH HOSIERY"]["retailers"] == 2
    assert shops["Alpha Shop"]["distributor_id"] == dists["KAILASH HOSIERY"]["id"]
    assert shops["Gamma Shop"]["distributor_id"] == dists["MITTAL TRADERS"]["id"]


def test_distributor_links_to_the_existing_row_case_insensitively(client, seed):
    """The distributor list is normally imported first, so the customer list
    must attach to those rows rather than creating near-duplicates."""
    headers = auth(client)
    assert client.post("/distributors/import",
                       json={"csv": "Name,Mobile\nKAILASH HOSIERY,8209575016\n"},
                       headers=headers).status_code == 200
    existing = client.get("/distributors", headers=headers).json()
    kailash = next(d for d in existing if d["name"] == "KAILASH HOSIERY")

    csv = ("Name,Mobile,Dealer\n"
           "Delta Shop,9333333331,kailash hosiery\n")
    assert imp(client, headers, csv).json()["created"] == 1

    after = client.get("/distributors", headers=headers).json()
    assert len(after) == len(existing), "must not create a second KAILASH row"
    assert by_shop(client, headers)["Delta Shop"]["distributor_id"] == kailash["id"]
    # Phone came from the distributor import and is untouched by the link.
    assert next(d for d in after if d["id"] == kailash["id"])["phone"] == "8209575016"


def test_distributor_header_aliases(client, seed):
    """Their export may call the column anything; alias order decides."""
    headers = auth(client)
    for i, header in enumerate(("Distributor Name", "Agency", "Supplier",
                                "Parent", "Stockist", "Wholesaler")):
        csv = (f"Name,Mobile,{header}\n"
               f"Shop{i},900000100{i},Dist {header}\n")
        body = imp(client, headers, csv).json()
        assert body["created"] == 1, f"{header}: {body}"
        assert body["columns"]["distributor"] == header, header
    names = {d["name"] for d in client.get("/distributors", headers=headers).json()}
    assert "Dist Agency" in names and "Dist Parent" in names
