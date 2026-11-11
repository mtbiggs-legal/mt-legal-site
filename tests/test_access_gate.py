"""Default deny: every route declares who may reach it, and the gate enforces it."""

import pytest

import app as app_module
import shared
from conftest import flask_app

LEVELS = {"public", "portal", "attorney", "client"}

# Anonymous routes. Adding one here is a deliberate decision: review it.
EXPECTED_PUBLIC = {
    "healthz", "static",
    "public.index", "public.meet_the_firm", "public.favicon", "public.robots_txt",
    "public.google_site_verification", "public.indexnow_key",
    "public.llms_txt", "public.llms_full_txt", "public.sitemap_xml", "public.case_search",
    "public.how_it_works", "public.why_nashville", "public.emerging_tech",
    "public.practice_area", "public.capture_lead", "public.follow_up_schedule",
    "public.chat_message", "public.api_track_visit", "public.api_case_search",
    "blog.index", "blog.feed", "blog.post", "blog.review_confirm", "blog.review_edit",
    "intake.intake", "intake.intake_submit",
}
EXPECTED_PORTAL = {
    "auth.attorney_login", "auth.client_login", "auth.logout", "auth.accept_invite",
    "auth.attorney_totp", "auth.attorney_totp_setup",
    "esign.esign_callback", "portal_client.webhook_stripe", "portal_client.webhook_coinbase",
}


def _levels():
    return {ep: app_module.endpoint_access(ep) for ep in flask_app.view_functions}


def test_every_route_declares_access():
    missing = sorted(ep for ep, lvl in _levels().items() if lvl not in LEVELS)
    assert not missing, f"routes with no access level: {missing}"


def test_anonymous_routes_are_the_reviewed_set():
    levels = _levels()
    assert {ep for ep, l in levels.items() if l == "public"} == EXPECTED_PUBLIC
    assert {ep for ep, l in levels.items() if l == "portal"} <= EXPECTED_PORTAL


def test_unmarked_route_is_refused(client, monkeypatch):
    # Swap a public page's view for one that declares no access level.
    monkeypatch.setitem(flask_app.view_functions, "public.how_it_works", lambda: "secret")
    assert client.get("/how-it-works").status_code == 404


@pytest.mark.parametrize("path", ["/portal/attorney/clients", "/portal/client/billing"])
def test_wrong_role_is_refused(client_session, attorney_session, path):
    other = client_session if "attorney" in path else attorney_session
    r = other.get(path, headers={"Accept": "application/json"})
    assert r.status_code == 401 and r.headers["X-Login-Url"]


def test_public_site_only_hides_portal_level(client, monkeypatch):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    assert client.get("/client-portal/invite/x.y").status_code == 404
    assert client.get("/webhooks/stripe").status_code == 404     # wrong method still 404
    assert client.get("/intake").status_code == 200


def test_csp_blocks_inline_handlers_and_uses_a_nonce(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in csp and "unsafe-inline" not in csp.split("style-src")[0]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    html = r.get_data(as_text=True)
    assert f'nonce="{nonce}"' in html
    assert " onclick=" not in html and " onsubmit=" not in html


def test_no_inline_handlers_left_in_templates():
    import re
    from pathlib import Path
    hits = []
    for p in Path("templates").rglob("*.html"):
        hits += [f"{p}:{m.group(0)}" for m in re.finditer(r'\son[a-z]+="', p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_upload_limit(attorney_session, monkeypatch):
    monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 1024)
    r = attorney_session.post("/portal/attorney/upload-document",
                              data={"username": "x", "file": (__import__("io").BytesIO(b"x" * 4096), "a.pdf")},
                              content_type="multipart/form-data")
    assert r.status_code == 413


def test_canonical_host_middleware():
    seen = {}

    def inner(environ, start_response):
        seen.update(host=environ["HTTP_HOST"], scheme=environ["wsgi.url_scheme"])
        return []
    app_module._CanonicalHost(inner, "midtennlegal.com", "https")(
        {"HTTP_HOST": "evil.example", "wsgi.url_scheme": "http"}, None)
    assert seen == {"host": "midtennlegal.com", "scheme": "https"}
