"""Production and public-site-only behaviour used by the hosted deployment."""

import pytest

import shared


def test_healthz_is_always_available(client):
    resp = client.get("/healthz")
    data = resp.get_json()
    assert resp.status_code == 200 and data["ok"] is True
    assert set(data) == {"ok", "production", "public_site_only", "persistent_data"}


@pytest.mark.parametrize("raw", ['1', '"1"', "'1'", " true ", "on"])
def test_public_site_only_flag_tolerates_quotes_and_spaces(monkeypatch, raw):
    monkeypatch.setenv("PUBLIC_SITE_ONLY", raw)
    assert shared._env("PUBLIC_SITE_ONLY").lower() in ("1", "true", "yes", "on")


@pytest.mark.parametrize("path", [
    "/client-login", "/attorney-login", "/client-portal", "/attorney-portal",
    "/portal/attorney/clients", "/research", "/drafting", "/calendar/status",
    "/webhooks/stripe",
])
def test_public_site_only_hides_private_routes(client, monkeypatch, path):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", [
    "/", "/meet-the-firm", "/emerging-tech", "/why-nashville", "/case-search",
    "/how-it-works", "/intake", "/practice/criminal-defense",
])
def test_public_site_only_keeps_public_pages(client, monkeypatch, path):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    assert client.get(path).status_code == 200


def test_public_site_only_hides_login_links(client, monkeypatch):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    html = client.get("/").get_data(as_text=True)
    assert 'href="/client-login"' not in html and 'href="/attorney-login"' not in html


def test_intake_email_omits_portal_login_when_public_only(monkeypatch):
    from blueprints import email_service
    sent = {}
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    monkeypatch.setattr(email_service, "_send",
                        lambda *a, **kw: sent.update(kw) or True)
    monkeypatch.setattr(email_service, "_send_firm_alert", lambda *a, **kw: None)
    email_service.send_intake_email(
        name="Jane Smith", email="jane@example.com", case_type="Criminal Defense",
        assigned_attorney="Endocide", portal_username="jsmith",
        portal_password="TempPass123!", urgent_dates=[])
    body = " ".join(str(v) for v in sent.values())
    assert sent, "email was not sent"
    assert "TempPass123!" not in body and "client-login" not in body


def test_versioned_static_files_are_cached_for_a_year(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/images/hero-home.webp?v=" in html
    resp = client.get("/static/css/style.css?v=1")
    assert "immutable" in resp.headers["Cache-Control"]
    assert "max-age=86400" in client.get("/static/css/style.css").headers["Cache-Control"]


def test_link_preview_tags_and_icons(client):
    html = client.get("/meet-the-firm").get_data(as_text=True)
    assert 'property="og:image" content="http://localhost/static/images/og-image.jpg"' in html
    assert 'max-image-preview:large' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert 'rel="apple-touch-icon"' in html
    assert client.get("/favicon.ico").status_code == 200


def test_robots_and_sitemap(client):
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /attorney-login" in robots and "Sitemap: http://localhost/sitemap.xml" in robots
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    assert "<loc>http://localhost/practice/stablecoins</loc>" in sitemap
    assert "/attorney-portal" not in sitemap
