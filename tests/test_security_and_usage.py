"""Regression tests for the auth, path-safety, and token-accounting fixes."""

import json
import types

import pytest

import shared


# ── Token usage: writer and reader must agree on one file format ──────────────

def test_token_usage_writes_the_format_the_portal_reads(tmp_path, attorney_session):
    usage = types.SimpleNamespace(input_tokens=100, output_tokens=40)
    shared._log_token_usage("Endocide", "Legal Issue Analysis", usage)
    shared._log_token_usage("Endocide", "Legal Issue Analysis", usage)
    shared._log_token_usage("Endocide", "Motion Draft Generation", usage)

    # One aggregate file per user, not one file per call.
    assert (tmp_path / "tokens" / "Endocide.json").exists()
    assert len(list((tmp_path / "tokens").glob("*.json"))) == 1

    resp = attorney_session.get("/portal/attorney/token-usage")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_input_tokens"] == 300
    assert data["total_output_tokens"] == 120
    assert data["by_label"]["Legal Issue Analysis"]["calls"] == 2
    assert data["by_label"]["Motion Draft Generation"]["calls"] == 1
    assert data["today_input"] == 300


def test_token_usage_empty_for_new_attorney(attorney_session):
    resp = attorney_session.get("/portal/attorney/token-usage")
    assert resp.status_code == 200
    assert resp.get_json()["total_input_tokens"] == 0


# ── Username sanitising ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("jsmith",        "jsmith"),
    ("j_smith-2",     "j_smith-2"),
    ("../../etc",     "etc"),
    ("..\\..\\secret", "secret"),
    ("  jsmith  ",    "jsmith"),
    ("",              ""),
])
def test_safe_username_strips_traversal(raw, expected):
    assert shared.safe_username(raw) == expected


def test_load_client_refuses_traversal(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"username": "outside"}))
    assert shared.load_client("../outside") is None


def test_save_client_refuses_unsafe_username():
    with pytest.raises(ValueError):
        shared.save_client({"username": "../escape"})


def test_document_download_cannot_escape_client_dir(attorney_session, make_client, tmp_path):
    make_client()
    secret = tmp_path / "files" / "secret.txt"
    secret.write_text("privileged", encoding="utf-8")

    resp = attorney_session.get(
        "/portal/attorney/document/testclient/Intake/..%2F..%2Fsecret.txt")
    assert resp.status_code in (404, 400)
    assert b"privileged" not in resp.data


# ── Public chat: anonymous, and carries conversation history ──────────────────

def _stub_chat(monkeypatch, capture):
    def _create(**kw):
        capture.update(kw)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text="Happy to help.")])
    import blueprints.public as pub
    monkeypatch.setattr(
        pub, "get_anthropic_client",
        lambda: types.SimpleNamespace(messages=types.SimpleNamespace(create=_create)))


def test_chat_replays_history(client, monkeypatch):
    captured = {}
    _stub_chat(monkeypatch, captured)

    resp = client.post("/chat/message", json={
        "message": "And what about the deadline?",
        "history": [
            {"role": "user",      "content": "Do I need a lawyer for a DUI?"},
            {"role": "assistant", "content": "It is strongly advised."},
        ],
    })
    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "Happy to help."

    msgs = captured["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "And what about the deadline?"


def test_chat_history_must_start_with_user_turn(client, monkeypatch):
    """A leading assistant turn would be rejected by the API — drop it."""
    captured = {}
    _stub_chat(monkeypatch, captured)

    client.post("/chat/message", json={
        "message": "Hello?",
        "history": [{"role": "assistant", "content": "Welcome!"}],
    })
    assert [m["role"] for m in captured["messages"]] == ["user"]


def test_chat_ignores_posted_username(client, make_client, monkeypatch):
    """A caller must not be able to read or write another person's file."""
    make_client(client_name="Real Client")
    captured = {}
    _stub_chat(monkeypatch, captured)

    resp = client.post("/chat/message",
                       json={"message": "hi", "username": "testclient"})
    assert resp.status_code == 200

    # No client details leaked into the prompt...
    assert "Real Client" not in captured["system"]
    # ...and nothing was written to that client's message thread.
    assert shared.load_client("testclient")["messages"] == []


def test_chat_rejects_empty_message(client):
    assert client.post("/chat/message", json={"message": "  "}).status_code == 400


# ── Public analytics is attorney-only ─────────────────────────────────────────

def test_page_visits_requires_attorney(client):
    assert client.get("/api/page-visits").status_code in (302, 401)


def test_page_visits_visible_to_attorney(attorney_session):
    assert attorney_session.get("/api/page-visits").status_code == 200
