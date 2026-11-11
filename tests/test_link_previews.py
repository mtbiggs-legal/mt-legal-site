"""Link previews (Open Graph) for texts and social apps."""
import re
from pathlib import Path


def _og_image(html):
    return re.search(r'<meta property="og:image" content="([^"]+)"', html).group(1)


def test_meet_madison_preview_shows_the_headshot_card(client):
    html = client.get("/meet-the-firm").get_data(as_text=True)
    assert _og_image(html).endswith("/static/images/og-meet-madison.jpg")
    assert 'name="twitter:image" content="http' in html and "og-meet-madison.jpg" in html
    assert Path("static/images/og-meet-madison.jpg").is_file()


def test_other_pages_keep_the_site_preview(client):
    for path in ["/", "/practice/criminal-defense", "/blog"]:
        assert _og_image(client.get(path).get_data(as_text=True)).endswith("/static/images/og-image.jpg"), path


def _json_ld(html):
    import json
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_meet_madison_profile_markup_names_the_headshot(client):
    blocks = _json_ld(client.get("/meet-the-firm").get_data(as_text=True))
    profile = next(b for b in blocks if b["@type"] == "ProfilePage")
    person = profile["mainEntity"]
    assert person["name"] == "Madison T. Biggs"
    assert person["image"]["url"] == "http://localhost/static/images/managing-partner.jpg"
    # The firm's founder entry points at the same person.
    firm = next(b for b in blocks if b["@type"] == "LegalService")
    assert firm["founder"]["@id"] == person["@id"] == "http://localhost/meet-the-firm#person"


def _flat(blocks):
    for b in blocks:
        yield from (b if isinstance(b, list) else [b])


def test_firm_markup_has_contact_details_and_id(client):
    firm = next(b for b in _flat(_json_ld(client.get("/").get_data(as_text=True)))
                if b["@type"] == "LegalService")
    assert firm["@id"] == "http://localhost/#firm"
    assert firm["telephone"].startswith("+1-") and "@" in firm["email"]


def test_practice_page_marks_up_service_and_breadcrumbs(client):
    blocks = list(_flat(_json_ld(client.get("/practice/criminal-defense").get_data(as_text=True))))
    service = next(b for b in blocks if b["@type"] == "Service")
    assert service["name"] == "Criminal Defense"
    assert service["provider"]["@id"] == "http://localhost/#firm"
    crumbs = next(b for b in blocks if b["@type"] == "BreadcrumbList")["itemListElement"]
    assert [c["position"] for c in crumbs] == [1, 2]
