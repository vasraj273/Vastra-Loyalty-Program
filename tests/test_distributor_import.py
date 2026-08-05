"""The distributor CSV import: dynamic header matching, like the catalog import.

The manufacturer exports their distributor list from whatever system they
already run, so the headers are theirs, not ours. Before this, only the literal
`name`/`phone`/`region` spellings were read and a real export's "Mobile" column
was silently dropped — every imported distributor landed with a blank phone.
"""


def auth(client, username="acme", password="acmepass"):
    r = client.post("/auth/login", json={"username": username,
                                         "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def imp(client, headers, csv):
    return client.post("/distributors/import", json={"csv": csv},
                       headers=headers)


# The real client's distributor export: their column names, a row-number
# column, a profile-pic column we have nowhere to put, and "Mobile" for phone.
REAL_CSV = (
    "SNo,Profile Pic,Name,Mobile,UserType,Shop Id,Shop Name\n"
    "1,,KAILASH HOSIERY,8209575016,distributor,,\n"
    "2,,MITTAL TRADERS,9437201426,distributor,,\n"
    "3,,BHAGWAN HOSIERY,9887782820,distributor,,\n"
)


def test_real_export_keeps_phone(client, seed):
    """The regression: "Mobile" must land in phone."""
    headers = auth(client)
    r = imp(client, headers, REAL_CSV)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3
    assert r.json()["columns"] == {"name": "Name", "phone": "Mobile",
                                   "region": None}

    rows = {d["name"]: d for d in client.get("/distributors",
                                             headers=headers).json()}
    assert rows["KAILASH HOSIERY"]["phone"] == "8209575016"
    assert rows["MITTAL TRADERS"]["phone"] == "9437201426"
    assert rows["BHAGWAN HOSIERY"]["phone"] == "9887782820"


def test_header_aliases(client, seed):
    """Any case/spelling of the three columns is accepted."""
    headers = auth(client)
    for i, header in enumerate((
        "name,phone,region",
        "Distributor Name,Mobile No,City",
        "FIRM_NAME,CONTACT NUMBER,State",
        "Party Name,WhatsApp,Territory",
    )):
        r = imp(client, headers, f"{header}\nAgency {i},98765{i},Surat\n")
        assert r.status_code == 200, (header, r.text)
        assert r.json()["created"] == 1, header

    rows = {d["name"]: d for d in client.get("/distributors",
                                             headers=headers).json()}
    assert len(rows) == 4
    for i in range(4):
        assert rows[f"Agency {i}"]["phone"] == f"98765{i}"
        assert rows[f"Agency {i}"]["region"] == "Surat"


def test_name_beats_shop_name_whatever_the_column_order(client, seed):
    """A file carrying both resolves to the plain name column, not the shop."""
    headers = auth(client)
    assert imp(client, headers,
               "Shop Name,Name\nKAILASH SHOP,KAILASH HOSIERY\n").json()[
        "columns"]["name"] == "Name"
    # ...and "Shop Name" alone still works as a fallback.
    assert imp(client, headers,
               "Shop Name,Mobile\nMITTAL SHOP,9437201426\n").json()[
        "columns"]["name"] == "Shop Name"

    names = {d["name"] for d in client.get("/distributors",
                                           headers=headers).json()}
    assert names == {"KAILASH HOSIERY", "MITTAL SHOP"}


def test_nullish_cells_blanked(client, seed):
    """The literal text "null"/"N/A" never reaches the distributor table."""
    headers = auth(client)
    r = imp(client, headers, "Name,Mobile,City\nJAIN HOSIERY,null,N/A\n")
    assert r.status_code == 200, r.text
    d = client.get("/distributors", headers=headers).json()[0]
    assert d["phone"] is None and d["region"] is None


def test_missing_name_column_rejects_whole_file(client, seed):
    headers = auth(client)
    r = imp(client, headers, "Profile Pic,Mobile,UserType\n,8209575016,distributor\n")
    assert r.status_code == 422
    assert "distributor name column" in r.json()["detail"]
    assert client.get("/distributors", headers=headers).json() == []


def test_existing_names_skipped(client, seed):
    headers = auth(client)
    assert imp(client, headers, REAL_CSV).json()["created"] == 3
    again = imp(client, headers, REAL_CSV).json()
    assert (again["created"], again["skipped"]) == (0, 3)
