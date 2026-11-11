"""IndexNow: key file, live-site guard, and pings from blog changes."""
import shared
from services import blog, indexnow


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(indexnow, "_send", lambda site, urls: sent.append((site, urls)))

    class _Now:  # run the "background" send inline
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(indexnow.threading, "Thread", _Now)
    return sent


def test_key_file_is_served(client):
    resp = client.get(f"/{indexnow.KEY}.txt")
    assert resp.status_code == 200 and resp.get_data(as_text=True) == indexnow.KEY


def test_no_ping_from_local_or_test_sites(monkeypatch):
    sent = _capture(monkeypatch)
    for site in ("http://127.0.0.1:5000", "https://localhost", "http://midtennlegal.com", "https://mt.test"):
        monkeypatch.setattr(shared, "SITE_URL", site)
        assert indexnow.submit(["/blog"]) is False
    assert sent == []


def test_publishing_a_post_pings_the_post_and_blog_index(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(shared, "SITE_URL", "https://midtennlegal.com")
    post = blog.new_post("Ping Me", "Summary.", "## Head\n\nPara", "civil-rights", "article")
    blog.save_post(post)
    assert blog.publish(post["slug"])
    assert sent == [("https://midtennlegal.com",
                     [f"https://midtennlegal.com/blog/{post['slug']}", "https://midtennlegal.com/blog"])]


def test_editing_a_draft_does_not_ping(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(shared, "SITE_URL", "https://midtennlegal.com")
    post = blog.new_post("Draft Only", "Summary.", "Body", "civil-rights", "article")
    blog.save_post(post)
    blog.update_post(post["slug"], "Draft Only 2", "Summary.", "Body")
    assert sent == []
