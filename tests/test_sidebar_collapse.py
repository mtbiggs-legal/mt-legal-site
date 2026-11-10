"""Attorney portal sidebar: each section header collapses its own section."""
import re


def test_sidebar_sections_are_collapsible(attorney_session):
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    keys = re.findall(r'data-collapse="([a-z]+)"[^>]*aria-expanded="false" aria-controls="sb-\1"', html)
    assert keys == ["workspace", "clients", "recent", "searches"]
    for key in keys:
        assert f'id="sb-{key}" hidden' in html      # closed when the page opens
    assert "js/attorney_sidebar.js" in html
