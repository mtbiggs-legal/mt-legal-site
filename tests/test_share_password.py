"""When SHARE_PASSWORD is set, the public + AI routes must all be gated.

These are the routes that spend Anthropic tokens or write files, so leaving any
of them open defeats the point of sharing the app behind a password.
"""

import base64

import pytest

GATED_GET_ROUTES = [
    "/",
    "/meet-the-firm",
    "/intake",
    "/research",
    "/drafting",
]

GATED_POST_ROUTES = [
    "/intake/submit",
    "/research/query",
    "/drafting/generate",
    "/drafting/claim-document",
    "/chat/message",
    "/capture/lead",
    "/follow-up/schedule",
    "/api/case-search",
    "/api/track-visit",
]


@pytest.fixture
def shared_app(monkeypatch):
    monkeypatch.setenv("SHARE_PASSWORD", "letmein")
    from conftest import flask_app
    with flask_app.test_client() as c:
        yield c


@pytest.mark.parametrize("route", GATED_GET_ROUTES)
def test_get_routes_require_share_password(shared_app, route):
    assert shared_app.get(route).status_code == 401


@pytest.mark.parametrize("route", GATED_POST_ROUTES)
def test_post_routes_require_share_password(shared_app, route):
    assert shared_app.post(route, json={}).status_code == 401


def test_correct_password_is_accepted(shared_app):
    token = base64.b64encode(b"user:letmein").decode()
    resp = shared_app.get("/", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 200


def test_wrong_password_is_rejected(shared_app):
    token = base64.b64encode(b"user:wrong").decode()
    resp = shared_app.get("/", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 401


def test_routes_open_when_no_share_password(client):
    """With sharing off (the default in tests) the marketing site is public."""
    assert client.get("/").status_code == 200
