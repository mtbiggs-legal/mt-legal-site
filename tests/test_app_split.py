"""create_app("public") / ("portal"): separate route sets and session cookies."""

import importlib

import pytest

import app as app_module
import shared


@pytest.fixture(scope="module")
def public_app():
    a = app_module.create_app("public")
    a.config.update(TESTING=True, CSRF_ENABLED=False, RATE_LIMITS_ENABLED=False)
    return a


@pytest.fixture(scope="module")
def portal_app():
    a = app_module.create_app("portal")
    a.config.update(TESTING=True, CSRF_ENABLED=False, RATE_LIMITS_ENABLED=False)
    return a


def _endpoints(a):
    return {r.endpoint.split(".")[0] for r in a.url_map.iter_rules()}


def test_public_app_registers_no_portal_routes(public_app):
    eps = _endpoints(public_app)
    assert {"public", "intake", "blog"} <= eps
    assert not eps & {"auth", "portal_attorney", "portal_client", "research", "matters", "esign"}


def test_portal_app_registers_no_marketing_pages(portal_app):
    eps = _endpoints(portal_app)
    assert {"auth", "portal_attorney", "portal_client"} <= eps
    assert not eps & {"public", "blog", "intake"}


def test_public_app_hides_portal_paths(public_app, patch_dirs):
    c = public_app.test_client()
    assert c.get("/").status_code == 200
    for path in ("/attorney-login", "/client-portal", "/portal/attorney/clients", "/webhooks/stripe"):
        assert c.get(path).status_code == 404, path


def test_separate_cookies(public_app, portal_app):
    assert public_app.config["SESSION_COOKIE_NAME"] == "mtl_site"
    assert portal_app.config["SESSION_COOKIE_NAME"] == "mtl_portal"


def test_login_links_point_to_portal_url(public_app, patch_dirs, monkeypatch):
    c = public_app.test_client()
    assert 'href="/client-login"' not in c.get("/").get_data(as_text=True)
    monkeypatch.setattr(shared, "PORTAL_URL", "https://portal.example.test")
    html = c.get("/").get_data(as_text=True)
    assert 'href="https://portal.example.test/client-login"' in html


def test_portal_root_goes_to_sign_in(portal_app, patch_dirs):
    r = portal_app.test_client().get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/client-login")


def test_wsgi_dispatches_by_host(monkeypatch, patch_dirs):
    monkeypatch.setattr(shared, "PORTAL_URL", "https://portal.example.test")
    import wsgi
    wsgi = importlib.reload(wsgi)
    for a in (wsgi.public_app, wsgi.portal_app):
        a.config["PROPAGATE_EXCEPTIONS"] = True
    seen = []

    def start_response(status, headers, exc_info=None):
        seen.append(status)

    def call(host, path):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "SERVER_NAME": host, "SERVER_PORT": "443",
                   "HTTP_HOST": host, "wsgi.url_scheme": "https", "wsgi.input": None,
                   "SERVER_PROTOCOL": "HTTP/1.1"}
        b"".join(wsgi.application(environ, start_response))
        return seen.pop()
    assert call("portal.example.test", "/client-login").startswith("200")
    assert call("www.example.test", "/client-login").startswith("404")
    assert call("www.example.test", "/healthz").startswith("200")


def test_run_once_claims_a_name_once(tmp_path, monkeypatch):
    from services import run_once
    monkeypatch.setattr(shared, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(run_once, "_held", {})
    assert run_once.claim("jobs")
    assert run_once.claim("jobs")                  # same process: still ours
    monkeypatch.setattr(run_once, "_held", {})     # pretend to be a second process
    assert not run_once.claim("jobs")


@pytest.mark.parametrize("role,path", [
    (None, "/attorney-login"), (None, "/client-login"),
    ("attorney", "/attorney-portal"), ("attorney", "/drafting"), ("attorney", "/research"),
    ("client", "/client-portal"),
])
def test_portal_pages_render_in_portal_app(portal_app, patch_dirs, make_client, role, path):
    make_client()
    c = portal_app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["username"] = "Endocide" if role == "attorney" else "testclient"
    r = c.get(path)
    assert r.status_code == 200, path
    html = r.get_data(as_text=True)
    assert "/chat/message" not in html and "chat_widget.js" not in html


def test_wsgi_ignores_forwarded_host(monkeypatch, patch_dirs):
    monkeypatch.setattr(shared, "PORTAL_URL", "https://portal.example.test")
    import wsgi
    wsgi = importlib.reload(wsgi)
    seen = []
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/client-login", "SERVER_NAME": "www.example.test",
               "SERVER_PORT": "443", "HTTP_HOST": "www.example.test",
               "HTTP_X_FORWARDED_HOST": "portal.example.test", "wsgi.url_scheme": "https",
               "wsgi.input": None, "SERVER_PROTOCOL": "HTTP/1.1"}
    b"".join(wsgi.application(environ, lambda status, headers, exc=None: seen.append(status)))
    assert seen[0].startswith("404")
