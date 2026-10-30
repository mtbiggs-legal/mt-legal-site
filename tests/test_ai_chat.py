"""Client portal messaging: messages persist, AI replies are billed."""

import types

import pytest

from services import storage


def _stub_anthropic(monkeypatch, reply_text="I understand your concern."):
    """Stub get_anthropic_client so Claude returns reply_text."""
    fake_msg    = types.SimpleNamespace(content=[types.SimpleNamespace(text=reply_text)])
    fake_client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **kw: fake_msg)
    )
    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "get_anthropic_client", lambda: fake_client)


def test_message_saved_and_ai_reply_returned(client_session, make_client, monkeypatch):
    make_client()
    _stub_anthropic(monkeypatch, reply_text="Thank you for reaching out.")

    resp = client_session.post("/portal/client/message",
                               json={"text": "What is the status of my case?"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "Thank you for reaching out." in data["ai_reply"]

    client = storage.load_client("testclient")
    assert len(client["messages"]) == 2
    assert client["messages"][0]["from"] == "client"
    assert client["messages"][1]["from"] == "ai"


def test_ai_reply_billed_01_hours(client_session, make_client, monkeypatch):
    make_client()
    _stub_anthropic(monkeypatch)

    client_session.post("/portal/client/message", json={"text": "Hello"})

    client = storage.load_client("testclient")
    assert client["hours_billed"] == pytest.approx(0.1)
    ai_entries = [e for e in client["billing_log"] if e.get("type") == "ai_message"]
    assert len(ai_entries) == 1
    assert ai_entries[0]["hours"] == 0.1


def test_ai_billing_matches_billing_log_over_multiple_messages(
    client_session, make_client, monkeypatch
):
    """hours_billed is recomputed from the log, so it cannot drift."""
    make_client()
    _stub_anthropic(monkeypatch)

    for _ in range(3):
        client_session.post("/portal/client/message", json={"text": "Hello again"})

    client = storage.load_client("testclient")
    assert client["hours_billed"] == pytest.approx(0.3)
    assert client["hours_billed"] == pytest.approx(
        sum(e["hours"] for e in client["billing_log"])
    )


def test_anthropic_failure_still_saves_message(client_session, make_client, monkeypatch):
    """If Anthropic fails, the client message is still saved and nothing is billed."""
    make_client()

    def _raise():
        raise Exception("API error")

    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "get_anthropic_client", _raise)

    resp = client_session.post("/portal/client/message", json={"text": "Hello"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "ai_reply" not in data

    client = storage.load_client("testclient")
    assert len(client["messages"]) == 1          # only the client's message
    assert client["hours_billed"] == 0
    assert client["billing_log"] == []


def test_empty_message_rejected(client_session, make_client):
    make_client()
    resp = client_session.post("/portal/client/message", json={"text": "   "})
    assert resp.status_code == 400


def test_message_requires_client_login(client, make_client):
    make_client()
    resp = client.post("/portal/client/message", json={"text": "Hello"})
    assert resp.status_code in (302, 401)


def test_concurrent_attorney_reply_survives_the_ai_call(client_session, make_client, monkeypatch):
    """Regression: client_send_message used to load the client, make a
    multi-second AI call, then save the copy it loaded at the start — any
    write to the same client in between (here, an attorney's reply) was
    silently overwritten. The route now does two short atomic updates
    instead, so a write that lands during the AI call must survive."""
    make_client()

    from tests.conftest import flask_app

    def _attorney_reply_lands_mid_call(**kw):
        # Simulate another request completing while this AI call is in flight.
        with flask_app.test_client() as atty:
            with atty.session_transaction() as sess:
                sess["username"] = "Endocide"
                sess["role"]     = "attorney"
            r = atty.post("/portal/attorney/reply",
                          json={"username": "testclient", "text": "Attorney reply mid-call"})
            assert r.status_code == 200
        fake_msg = types.SimpleNamespace(content=[types.SimpleNamespace(text="AI reply")])
        return fake_msg

    import blueprints.portal_client as pc
    fake_client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=_attorney_reply_lands_mid_call)
    )
    monkeypatch.setattr(pc, "get_anthropic_client", lambda: fake_client)

    resp = client_session.post("/portal/client/message", json={"text": "Client message"})
    assert resp.status_code == 200
    assert resp.get_json()["ai_reply"] == "AI reply"

    client = storage.load_client("testclient")
    by_text = {m["text"] for m in client["messages"]}
    assert by_text == {"Client message", "Attorney reply mid-call", "AI reply"}, (
        f"expected all three messages to survive, got: {client['messages']}"
    )
