"""The manual product catalog: CSV import, dynamic columns, and the
imported > samples > empty resolution order.

The catalog never calls Vastra — get-design-ids has no product names, so the
manufacturer imports their own list instead. Vastra OTP login is a separate
path and is not exercised here.
"""
import pytest


def auth(client, username="acme", password="acmepass"):
    r = client.post("/auth/login", json={"username": username,
                                         "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def imp(client, headers, csv, mode="upsert"):
    return client.post("/catalog/products/import",
                       json={"csv": csv, "mode": mode}, headers=headers)


# A CSV shaped like the real client's export: their own column names, a
# row-number column, and literal "null" cells.
REAL_CSV = (
    "SNo,Brand name,Product name,Product code,Sub Category,MRP,Color\n"
    "1,LONDON DREAM,93-TENCEL OVERSIZE T-SHIRT,93-TENCEL OVERSIZE T-SHIRT S TO 3XL,LOUNGE WEAR,0,null\n"
    "2,HARSHITA,91-RAYON PANT,91-RAYON PANT M TO 3XL,PANT,0,null\n"
)


# ---------------------------------------------------------------- parsing

def test_required_columns_and_aliases(appmod):
    """Any case/spelling of the name and code columns is accepted."""
    for header in ("Product Name,Product Code", "PRODUCT_NAME,PRODUCT_CODE",
                   "product name,product code", "name,sku", "P-Name,P-Code"):
        parsed = appmod._parse_catalog_csv(f"{header}\nSaree,BNS-01\n")
        assert parsed["rows"] == [{
            "external_id": "BNS-01", "name": "Saree", "sku": "BNS-01",
            "points": 0, "attrs": {},
        }], header


def test_missing_required_column_rejects_whole_file(appmod):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        appmod._parse_catalog_csv("Brand,Colour\nLONDON DREAM,Red\n")
    assert exc.value.status_code == 422
    assert "product name column" in exc.value.detail
    assert "product code column" in exc.value.detail


def test_row_numbers_dropped_and_nulls_blanked(appmod):
    parsed = appmod._parse_catalog_csv(REAL_CSV)
    # SNo is a render index, not data.
    assert "SNo" not in parsed["columns"]
    # Free-form columns keep their original header text, in CSV order.
    assert parsed["columns"] == ["Brand name", "Sub Category", "MRP", "Color"]
    # The literal string "null" never reaches the panel.
    assert parsed["rows"][0]["attrs"]["Color"] == ""
    assert parsed["rows"][0]["attrs"]["Brand name"] == "LONDON DREAM"


def test_bad_rows_skipped_not_fatal(appmod):
    parsed = appmod._parse_catalog_csv(
        "name,code,points\n"
        "Good,C1,50\n"
        ",C2,10\n"          # missing name
        "NoCode,,10\n"      # missing code
        "Bad,C3,abc\n")     # points not a number
    assert [r["external_id"] for r in parsed["rows"]] == ["C1"]
    assert parsed["skipped"] == 3
    assert len(parsed["errors"]) == 3


def test_duplicate_code_last_row_wins(appmod):
    parsed = appmod._parse_catalog_csv(
        "name,code\nFirst,DUP\nSecond,DUP\n")
    assert len(parsed["rows"]) == 1
    assert parsed["rows"][0]["name"] == "Second"
    assert any("duplicate" in e for e in parsed["errors"])


# ---------------------------------------------------------------- import

def test_import_then_catalog_returns_rows_and_columns(client, seed):
    h = auth(client)
    r = imp(client, h, REAL_CSV)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2
    assert r.json()["skipped"] == 0

    body = client.get("/catalog/products", headers=h).json()
    assert body["source"] == "import"
    assert body["columns"] == ["Brand name", "Sub Category", "MRP", "Color"]
    assert len(body["products"]) == 2
    p = next(x for x in body["products"] if x["sku"].startswith("93-"))
    assert p["name"] == "93-TENCEL OVERSIZE T-SHIRT"
    assert p["attrs"]["Brand name"] == "LONDON DREAM"
    assert p["points"] == 0


def test_optional_points_column_seeds_values(client, seed):
    h = auth(client)
    imp(client, h, "name,code,points\nSaree,C1,120\n")
    body = client.get("/catalog/products", headers=h).json()
    assert body["products"][0]["points"] == 120


def test_upsert_preserves_panel_points_but_csv_points_win(client, seed):
    h = auth(client)
    imp(client, h, "name,code\nSaree,C1\n")
    client.put("/catalog/products/C1/points", json={"points": 90}, headers=h)

    # No points column -> the value set in the panel survives re-import.
    r = imp(client, h, "name,code,Color\nSaree Deluxe,C1,Red\nKurta,C2,Blue\n")
    assert r.json() == {"created": 1, "updated": 1, "skipped": 0,
                        "errors": [], "columns": ["Color"]}
    body = client.get("/catalog/products", headers=h).json()
    saree = next(p for p in body["products"] if p["external_id"] == "C1")
    assert saree["points"] == 90
    assert saree["name"] == "Saree Deluxe"      # name refreshed
    assert saree["attrs"]["Color"] == "Red"     # new column appended
    assert len(body["products"]) == 2           # nothing deleted

    # A points column in the file is an explicit instruction -> it wins.
    imp(client, h, "name,code,points\nSaree Deluxe,C1,5\n")
    body = client.get("/catalog/products", headers=h).json()
    assert next(p for p in body["products"]
                if p["external_id"] == "C1")["points"] == 5


def test_replace_clears_previous_import(client, seed):
    h = auth(client)
    imp(client, h, "name,code\nOld1,C1\nOld2,C2\n")
    imp(client, h, "name,code\nNew,C9\n", mode="replace")
    body = client.get("/catalog/products", headers=h).json()
    assert [p["external_id"] for p in body["products"]] == ["C9"]


def test_replace_leaves_legacy_override_rows_alone(client, seed, db):
    """source IS NULL rows are legacy Vastra points overrides, not catalog."""
    h = auth(client)
    with db() as conn:
        conn.execute(
            "INSERT INTO product_points (manufacturer_id, product_external_id,"
            " points) VALUES (?, ?, ?)", (seed["mid"], "LEGACY-1", 42))
    imp(client, h, "name,code\nNew,C9\n", mode="replace")
    with db() as conn:
        row = conn.execute(
            "SELECT points FROM product_points WHERE manufacturer_id = ?"
            " AND product_external_id = 'LEGACY-1'", (seed["mid"],)).fetchone()
    assert row["points"] == 42
    # ...and it never shows up as a nameless product.
    body = client.get("/catalog/products", headers=h).json()
    assert [p["external_id"] for p in body["products"]] == ["C9"]


def test_import_promotes_colliding_legacy_row(client, seed, db):
    h = auth(client)
    with db() as conn:
        conn.execute(
            "INSERT INTO product_points (manufacturer_id, product_external_id,"
            " points) VALUES (?, ?, ?)", (seed["mid"], "C1", 7))
    r = imp(client, h, "name,code\nSaree,C1\n")
    assert r.status_code == 200, r.text
    body = client.get("/catalog/products", headers=h).json()
    assert len(body["products"]) == 1
    assert body["products"][0]["name"] == "Saree"


# ---------------------------------------------------------------- delete

def test_delete_removes_only_that_product(client, seed):
    h = auth(client)
    imp(client, h, "name,code\nA,C1\nB,C2\n")
    assert client.delete("/catalog/products/C1", headers=h).status_code == 204
    body = client.get("/catalog/products", headers=h).json()
    assert [p["external_id"] for p in body["products"]] == ["C2"]
    # Deleting again is a 404, not a silent success.
    assert client.delete("/catalog/products/C1", headers=h).status_code == 404


def test_delete_all_clears_catalog_but_spares_legacy_rows(client, seed, db):
    h = auth(client)
    with db() as conn:
        conn.execute(
            "INSERT INTO product_points (manufacturer_id, product_external_id,"
            " points) VALUES (?, ?, ?)", (seed["mid"], "LEGACY-1", 42))
    imp(client, h, "name,code\nA,C1\nB,C2\n")

    r = client.delete("/catalog/products", headers=h)
    assert r.status_code == 200
    assert r.json() == {"deleted": 2}
    assert client.get("/catalog/products", headers=h).json()["source"] != "import"

    with db() as conn:
        row = conn.execute(
            "SELECT points FROM product_points WHERE manufacturer_id = ?"
            " AND product_external_id = 'LEGACY-1'", (seed["mid"],)).fetchone()
    assert row["points"] == 42

    # Clearing an already-empty catalog is a no-op, not an error.
    assert client.delete("/catalog/products",
                         headers=h).json() == {"deleted": 0}


# ------------------------------------------------------- source precedence

def test_samples_show_only_while_catalog_is_empty(client, seed, monkeypatch,
                                                  appmod):
    h = auth(client)
    monkeypatch.setattr(appmod, "USE_SAMPLE_PRODUCTS", True)
    body = client.get("/catalog/products", headers=h).json()
    assert body["source"] == "sample"
    assert len(body["products"]) == 3

    imp(client, h, "name,code\nReal,C1\n")
    body = client.get("/catalog/products", headers=h).json()
    assert body["source"] == "import"
    assert [p["external_id"] for p in body["products"]] == ["C1"]


def test_samples_off_gives_empty_state(client, seed, monkeypatch, appmod):
    h = auth(client)
    monkeypatch.setattr(appmod, "USE_SAMPLE_PRODUCTS", False)
    body = client.get("/catalog/products", headers=h).json()
    assert body == {"products": [], "columns": [], "source": "empty"}


def test_editing_sample_points_does_not_create_a_catalog(client, seed,
                                                         monkeypatch, appmod):
    """Editing a sample's points writes a legacy override, so the account must
    not flip into 'import' mode with a single nameless product."""
    h = auth(client)
    monkeypatch.setattr(appmod, "USE_SAMPLE_PRODUCTS", True)
    client.put("/catalog/products/SAMPLE-001/points", json={"points": 33},
               headers=h)
    body = client.get("/catalog/products", headers=h).json()
    assert body["source"] == "sample"
    assert len(body["products"]) == 3
    assert next(p for p in body["products"]
                if p["external_id"] == "SAMPLE-001")["points"] == 33


def test_catalog_never_calls_vastra(client, seed, db, monkeypatch, appmod):
    """Even with a stored Vastra session, the catalog comes from the import."""
    import app.vastra_client as vc

    def boom(*a, **k):
        raise AssertionError("the catalog must not call Vastra")

    monkeypatch.setattr(vc, "fetch_vastra_products", boom)
    h = auth(client)
    with db() as conn:
        conn.execute("UPDATE manufacturers SET vastra_access_token = ?"
                     " WHERE id = ?", ("tok", seed["mid"]))
    imp(client, h, "name,code\nReal,C1\n")
    body = client.get("/catalog/products", headers=h).json()
    assert body["source"] == "import"


# ---------------------------------------------------------------- tenancy

def test_catalog_is_per_manufacturer(client, seed, db):
    from app.auth import hash_password
    with db() as conn:
        conn.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name,"
            " is_admin) VALUES (?, ?, ?, 0)",
            ("other", hash_password("otherpass"), "Other Mills"))

    h1 = auth(client)
    h2 = auth(client, "other", "otherpass")
    imp(client, h1, "name,code\nMine,C1\n")

    assert client.get("/catalog/products", headers=h2).json()["source"] != "import"
    # ...and one tenant cannot delete another's product, one at a time...
    assert client.delete("/catalog/products/C1", headers=h2).status_code == 404
    # ...or wholesale.
    assert client.delete("/catalog/products", headers=h2).json() == {"deleted": 0}
    assert len(client.get("/catalog/products",
                          headers=h1).json()["products"]) == 1
