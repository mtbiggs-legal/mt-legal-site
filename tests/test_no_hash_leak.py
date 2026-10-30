"""Password hashes never leave the server (spec A2)."""

from services import storage
from services import accounts


def test_portal_page_has_no_hashes(attorney_session, make_client):
    make_client("victim", password=accounts.hash_password("s3cret-pass"))
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert "$2b$" not in html
    assert '"password":' not in html          # no JSON password key in _ALL_CLIENTS_DATA


def test_client_json_has_no_password(attorney_session, make_client):
    make_client("victim", password=accounts.hash_password("s3cret-pass"))
    for url in ("/portal/attorney/clients", "/portal/attorney/client/victim"):
        body = attorney_session.get(url).get_data(as_text=True)
        assert "$2b$" not in body and '"password"' not in body


def test_co_counsel_client_in_sidebar_with_badge(other_attorney_session, make_client):
    make_client("shared1", client_name="Shared Person", co_counsel=["SophiaH"])
    html = other_attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert "Shared Person" in html
    assert ">Co-counsel</span>" in html      # the badge element, not just the CSS rule


def test_create_client_without_password_generates_one(attorney_session):
    r = attorney_session.post("/portal/attorney/create-client",
                              json={"username": "newbie", "client_name": "New Bie"})
    d = r.get_json()
    assert d["success"] and len(d["temp_password"]) >= 8
    rec = storage.load_client("newbie")
    assert accounts.check_password(d["temp_password"], rec["password"])
    assert not accounts.check_password("password", rec["password"])
    assert rec["must_change_password"] is True


def test_create_client_rejects_weak_password(attorney_session):
    d = attorney_session.post("/portal/attorney/create-client", json={
        "username": "weak", "client_name": "W", "password": "password",
        "must_change_password": False}).get_json()
    assert d["temp_password"] != "password"
    assert storage.load_client("weak")["must_change_password"] is True


def test_create_client_keeps_acceptable_password(attorney_session):
    d = attorney_session.post("/portal/attorney/create-client", json={
        "username": "ok1", "client_name": "O", "password": "Tr1cky-Horse"}).get_json()
    assert d["temp_password"] == "Tr1cky-Horse"


def test_password_replaced_flag(attorney_session):
    def flag(u, **kw):
        return attorney_session.post("/portal/attorney/create-client",
                                     json={"username": u, "client_name": "X", **kw}).get_json()["password_replaced"]
    assert flag("pr1", password="password") is True
    assert flag("pr2", password="Tr1cky-Horse") is False
    assert flag("pr3") is False
    assert flag("pr4", password="") is False


def test_portal_page_has_no_default_password(attorney_session):
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert 'value="password"' not in html and '|| "password"' not in html


def test_acceptable_password():
    assert accounts.acceptable_password("Tr1cky-Horse", "jdoe")
    assert not accounts.acceptable_password("short", "jdoe")
    assert not accounts.acceptable_password("PASSWORD", "jdoe")
    assert not accounts.acceptable_password("jdoe1234", "jdoe1234")
