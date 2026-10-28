"""Dedicated practice-area pages and their links from the homepage/footer."""

from markupsafe import escape

import pytest

from blueprints.public import PRACTICE_AREAS


def test_every_practice_area_page_renders(client):
    for slug, area in PRACTICE_AREAS.items():
        resp = client.get(f"/practice/{slug}")
        assert resp.status_code == 200, slug
        html = resp.get_data(as_text=True)
        # Jinja autoescapes "&", so compare against the escaped form (names
        # like "DeFi & Digital Assets" would otherwise never match).
        assert str(escape(area["name"])) in html
        for item in area["focus"]:
            assert str(escape(item)) in html


def test_unknown_practice_area_404s(client):
    assert client.get("/practice/not-a-real-area").status_code == 404


def test_practice_page_cta_prefills_the_first_case_type(client):
    resp = client.get("/practice/criminal-defense")
    html = resp.get_data(as_text=True)
    assert "/intake?case_type=Criminal%20Defense" in html


def test_practice_page_links_to_other_areas_not_itself(client):
    resp = client.get("/practice/family-law")
    html = resp.get_data(as_text=True)
    section = html.split("Other practice areas", 1)[1]
    for slug in PRACTICE_AREAS:
        if slug == "family-law":
            continue
        assert f"/practice/{slug}" in section
    # The "other areas" list itself must not link back to the current page
    # (the site-wide footer legitimately does, so this is scoped to that list).
    other_areas_block = section.split("</section>", 1)[0]
    assert 'href="/practice/family-law"' not in other_areas_block


def test_every_practice_page_has_a_personal_note(client):
    from blueprints.practice_areas import PRACTICE_AREAS
    for slug, area in PRACTICE_AREAS.items():
        assert area["story"]["paras"], slug
        html = client.get(f"/practice/{slug}").get_data(as_text=True)
        assert "From Madison" in html and area["story"]["heading"] in html, slug


def test_practice_area_case_types_route_to_the_managing_partner():
    """MT Legal is a solo practice: every case type a practice page offers must
    route to the managing partner shown on that page -- otherwise the page
    would promise one attorney and the backend would hand the client to another."""
    from shared import CASE_ATTORNEY_MAP, MANAGING_PARTNER
    for slug, area in PRACTICE_AREAS.items():
        for case_type in area["case_types"]:
            assert CASE_ATTORNEY_MAP.get(case_type) == MANAGING_PARTNER["username"], (
                f"{slug}: {case_type!r} routes to {CASE_ATTORNEY_MAP.get(case_type)!r}")


def test_practice_area_case_types_exist_in_intake_dropdown():
    html = open("templates/intake.html", encoding="utf-8").read()
    for slug, area in PRACTICE_AREAS.items():
        for case_type in area["case_types"]:
            assert f'<option value="{case_type}">' in html, (slug, case_type)


def test_tokenization_page_renders_structures_process_fees_and_faqs(client):
    html = client.get("/practice/rwa-tokenization").get_data(as_text=True)
    area = PRACTICE_AREAS["rwa-tokenization"]
    for s in area["structures"]:
        assert str(escape(s["name"])) in html
    for step in area["process"]:
        assert str(escape(step["title"])) in html
    for row in area["fees"]:
        assert str(escape(row["fee"])) in html
    for faq in area["faqs"]:
        assert str(escape(faq["q"])) in html


def test_homepage_practice_grid_links_to_dedicated_pages(client):
    html = client.get("/").get_data(as_text=True)
    for slug in PRACTICE_AREAS:
        assert f'href="/practice/{slug}"' in html
    # The old pattern (every card linking straight to /intake) is gone.
    assert "ed-num" not in html.split('id="practice"', 1)[1].split("</section>", 1)[0]


def test_homepage_practice_cards_have_no_numbers(client):
    html = client.get("/").get_data(as_text=True)
    practice_section = html.split('id="practice"', 1)[1].split("</section>", 1)[0]
    assert "01" not in practice_section and "<span class=\"ed-num\">" not in practice_section


def test_footer_practice_links_point_to_practice_pages(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/practice/criminal-defense"' in html
    assert 'href="/practice/civil-rights"' in html
    assert 'href="/practice/stablecoins"' in html
    assert 'href="/practice/family-law"' in html


def test_intake_prefills_case_type_only_for_known_options():
    html = open("templates/intake.html", encoding="utf-8").read()
    assert "case_type" in html and "URLSearchParams" in html


def test_emerging_tech_hub_links_its_areas_and_renders_topics(client):
    from blueprints.practice_areas import EMERGING_TECH_AREAS, EMERGING_TECH_TOPICS
    html = client.get("/emerging-tech").get_data(as_text=True)
    for slug in EMERGING_TECH_AREAS:
        assert f'href="/practice/{slug}"' in html
    for t in EMERGING_TECH_TOPICS:
        assert str(escape(t["title"])) in html


def test_homepage_boxes_open_meet_madison_and_emerging_tech(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/meet-the-firm"' in html and 'href="/emerging-tech"' in html


def test_no_numbered_step_boxes_on_public_pages(client):
    for path in ["/", "/meet-the-firm", "/emerging-tech",
                 *(f"/practice/{slug}" for slug in PRACTICE_AREAS)]:
        assert "ed-process" not in client.get(path).get_data(as_text=True), path


@pytest.mark.parametrize("path", ["/research", "/drafting"])
def test_research_and_drafting_tools_are_attorney_only(client, attorney_session, path):
    assert client.get(path).status_code == 302          # public visitor -> attorney login
    assert attorney_session.get(path).status_code == 200


def test_public_pages_do_not_link_attorney_tools(client):
    for path in ["/", "/meet-the-firm", "/emerging-tech", "/practice/criminal-defense"]:
        html = client.get(path).get_data(as_text=True)
        assert 'href="/research"' not in html and 'href="/drafting"' not in html, path


def test_why_nashville_page_renders_and_is_linked_from_homepage(client):
    assert client.get("/why-nashville").status_code == 200
    assert 'href="/why-nashville"' in client.get("/").get_data(as_text=True)


def test_homepage_explore_boxes_all_open_pages(client):
    html = client.get("/").get_data(as_text=True)
    explore = html.split("ed-boxes--explore", 1)[1].split("</section>", 1)[0]
    assert "<details" not in explore
    for href in ["/meet-the-firm", "/emerging-tech", "/case-search", "/how-it-works"]:
        assert f'href="{href}"' in explore
        assert client.get(href).status_code == 200
    # Questions and service area are always expanded on the homepage.
    assert "Is there a consultation fee?" in html and "Davidson County" in html


def test_service_area_counties_link_to_case_search_with_county_preset(client):
    from shared import SERVICE_COUNTIES
    html = client.get("/").get_data(as_text=True)
    for c in SERVICE_COUNTIES:
        assert f'href="/case-search?county={c}"' in html
    page = client.get("/case-search?county=Bedford").get_data(as_text=True)
    assert "URLSearchParams(location.search).get('county')" in page
    assert '<option value="Bedford">' in page


def test_old_civil_litigation_url_redirects_to_civil_rights(client):
    resp = client.get("/practice/civil-litigation")
    assert resp.status_code == 301 and resp.headers["Location"].endswith("/practice/civil-rights")


def test_old_real_estate_tokenization_url_redirects(client):
    resp = client.get("/practice/real-estate-tokenization")
    assert resp.status_code == 301 and resp.headers["Location"].endswith("/practice/rwa-tokenization")


@pytest.mark.parametrize("slug", ["ai-emerging-tech", "defi-digital-assets"])
def test_retired_practice_pages_redirect_to_emerging_tech(client, slug):
    resp = client.get(f"/practice/{slug}")
    assert resp.status_code == 301 and resp.headers["Location"].endswith("/emerging-tech")


def test_stablecoins_page_covers_agentic_payments(client):
    html = client.get("/practice/stablecoins").get_data(as_text=True)
    assert "Stablecoins &amp; Agentic Payments" in html and "What are agentic payments?" in html


def test_meet_the_firm_shows_both_attorneys(client):
    html = client.get("/meet-the-firm").get_data(as_text=True)
    assert "Meet the firm." in html
    assert "Madison T. Biggs, Esq." in html and "Paul Randolph, Esq." in html
    assert "paul-randolph.webp" in html
    nav = client.get("/").get_data(as_text=True)
    assert "Meet the Firm" in nav and "Meet Madison" not in nav
