"""Portal invitations: single use, expiring, and the only way a password is set."""

from datetime import datetime, timedelta

from services import accounts, storage

GOOD = {"new_password": "Tr1cky-Horse", "confirm_password": "Tr1cky-Horse"}


def _token(make_client, username="invitee"):
    make_client(username, password="", email="i@example.com")
    return accounts.issue_invite(username)


def test_invite_sets_password_and_signs_in(client, make_client):
    tok = _token(make_client)
    assert client.get(f"/client-portal/invite/{tok}").status_code == 200
    r = client.post(f"/client-portal/invite/{tok}", data=GOOD)
    assert r.status_code == 302 and r.headers["Location"].endswith("/client-portal")
    rec = storage.load_client("invitee")
    assert accounts.check_password("Tr1cky-Horse", rec["password"]) and rec["invite"] is None
    with client.session_transaction() as s:
        assert s["role"] == "client" and s["username"] == "invitee"


def test_invite_is_single_use(client, make_client):
    tok = _token(make_client)
    client.post(f"/client-portal/invite/{tok}", data=GOOD)
    assert client.get(f"/client-portal/invite/{tok}").status_code == 404


def test_reissue_invalidates_old_link(client, make_client):
    old = _token(make_client)
    accounts.issue_invite("invitee")
    assert client.get(f"/client-portal/invite/{old}").status_code == 404


def test_expired_invite_rejected(client, make_client):
    tok = _token(make_client)
    past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    storage.update_client_atomic("invitee", lambda c: c["invite"].update(expires=past))
    assert client.get(f"/client-portal/invite/{tok}").status_code == 404


def test_tampered_token_rejected(client, make_client):
    tok = _token(make_client)
    assert client.get(f"/client-portal/invite/{tok[:-2]}xx").status_code == 404
    assert client.get("/client-portal/invite/other.abc").status_code == 404


def test_weak_password_refused(client, make_client):
    tok = _token(make_client)
    r = client.post(f"/client-portal/invite/{tok}",
                    data={"new_password": "password", "confirm_password": "password"})
    assert r.status_code == 200 and storage.load_client("invitee")["password"] == ""


def test_account_without_password_cannot_sign_in(client, make_client):
    _token(make_client)
    r = client.post("/client-login", data={"username": "invitee", "password": ""})
    assert r.status_code == 200 and b"Invalid" in r.data


def test_create_client_issues_invite_not_password(attorney_session):
    d = attorney_session.post("/portal/attorney/create-client",
                              json={"client_name": "New Bie"}).get_json()
    assert d["success"] and "temp_password" not in d
    assert d["invite_link"].split("/client-portal/invite/")[1].startswith(d["username"] + ".")
    rec = storage.load_client(d["username"])
    assert rec["password"] == "" and rec["invite"]


def test_resend_invite(attorney_session, make_client):
    make_client("resend", password="")
    d = attorney_session.post("/portal/attorney/send-invite", json={"username": "resend"}).get_json()
    assert d["success"] and d["invite_link"]
