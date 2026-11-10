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










def test_portal_page_has_no_default_password(attorney_session):
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert 'value="password"' not in html and '|| "password"' not in html


def test_acceptable_password():
    assert accounts.acceptable_password("Tr1cky-Horse", "jdoe")
    assert not accounts.acceptable_password("short", "jdoe")
    assert not accounts.acceptable_password("PASSWORD", "jdoe")
    assert not accounts.acceptable_password("jdoe1234", "jdoe1234")
