"""Fuzzy conflict matching (spec D2)."""

import json

import pytest

from services import conflicts
import shared
from services import storage
from conftest import flask_app


@pytest.mark.parametrize("raw,expected", [
    ("Robert Smith Jr.", "robert smith"),
    ("Bob  SMITH", "robert smith"),
    ("Acme Roofing, LLC", "acme roofing"),
    ("Dr. Elizabeth O'Neil", "elizabeth o neil"),
    ("", ""),
    ("José_García", "jose garcia"),
    ("The Group", "the group"),
    ("LLC", "llc"),
])
def test_normalise_name(raw, expected):
    assert conflicts.normalise_name(raw) == expected


@pytest.mark.parametrize("a,b,level", [
    ("Bob Smith", "Robert Smith Jr.", "likely"),
    ("Smith, Robert", "Robert Smith", "likely"),
    ("Acme Roofing LLC", "ACME Roofing", "likely"),
    ("Jon Smith", "John Smith", "likely"),
    ("Smith", "Smith", "likely"),              # exact equality is exempt from the cap
    ("Smith", "John Smith", "possible"),       # single token equal to a token: possible
    ("Alice Morris", "Derek Williams", None),
    ("José García", "Jose Garcia", "likely"),
    ("John", "John Smith", None),
    ("Mr. Smith", "Robert Smith", "possible"),
    ("The Group", "THE GROUP", "likely"),
    ("Иван Петров", "Иван Петров", "likely"),
    ("李小龙", "李小龙", "likely"),
    ("Acme Inc.", "Acme Incorporated", "likely"),
    ("Smith & Sons", "Smith and Sons", "likely"),
])

def test_similarity_levels(a, b, level):
    assert conflicts.level_for(conflicts.name_similarity(a, b)) == level


def test_single_token_prefix_not_likely():
    assert conflicts.level_for(conflicts.name_similarity("Smith", "Smithers")) != "likely"


def _with_viewer(username):
    ctx = flask_app.test_request_context("/")
    ctx.push()
    shared.session["role"] = "attorney"
    shared.session["username"] = username
    return ctx


def test_sources(make_client, tmp_path):
    make_client("c1", client_name="Robert Smith", opposing_parties=["Acme Roofing LLC"],
                related_parties=[{"name": "Dana Morris", "relationship": "Spouse"}])
    make_client("c2", client_name="Old Client", archived=True)
    (tmp_path / "leads" / "l1.json").write_text(json.dumps(
        {"name": "Lena Lead", "case_type": "Real Estate", "assigned_attorney": "SophiaH"}))
    (tmp_path / "leads" / "l2.json").write_text(json.dumps(
        {"name": "Archived Lead", "archived": True}))

    def src(name):
        return [h["source"] for h in conflicts.run_conflict_check(other_names=[name])]

    assert src("Bob Smith") == ["client"]
    assert src("ACME Roofing") == ["opposing_party"]
    assert src("Dana Morris") == ["related_party"]
    assert src("Old Client") == ["former_client"]
    assert src("Lena Lead") == ["lead"]
    assert src("Archived Lead") == []


def test_exclude_username(make_client):
    make_client("c1", client_name="Robert Smith")
    assert conflicts.run_conflict_check(client_names=["Robert Smith"], exclude_username="c1") == []


def test_adverse_flags(make_client):
    make_client("c1", client_name="Robert Smith", opposing_parties=["Acme Roofing"])
    opp = conflicts.run_conflict_check(opposing_names=["Robert Smith"])
    assert opp[0]["adverse"] is True
    cli = conflicts.run_conflict_check(client_names=["Acme Roofing"])
    assert cli[0]["adverse"] is True
    other = conflicts.run_conflict_check(other_names=["Robert Smith"])
    assert other[0]["adverse"] is False


def test_likely_sorted_first(make_client):
    make_client("c1", client_name="John Smith")
    make_client("c2", client_name="Jon Smith")
    hits = conflicts.run_conflict_check(other_names=["John Smith"])
    assert hits[0]["matched_name"] == "John Smith"


def test_redaction_for_inaccessible_client(make_client):
    make_client("c1", client_name="Robert Smith", assigned_attorney="Endocide",
                related_parties=[{"name": "Dana Morris", "relationship": "Spouse"}])
    hits = conflicts.run_conflict_check(other_names=["Dana Morris"])
    ctx = _with_viewer("SophiaH")
    try:
        red = conflicts.redact_hits(hits, "SophiaH")[0]
    finally:
        ctx.pop()
    assert set(red) == set(conflicts.PUBLIC_HIT_FIELDS)
    assert red["assigned_attorney_display"] == shared.ATTORNEYS["Endocide"]["display"]
    full = conflicts.redact_hits(hits, "Endocide")[0]
    assert full["username"] == "c1" and full["relationship"] == "Spouse"


def test_record_check_appends_to_client(make_client):
    make_client("c1", client_name="Robert Smith")
    new = {"username": "newc"}
    rec = conflicts.record_check(new, "create", "Endocide", client_names=["Bob Smith", ""])
    assert new["conflict_checks"] == [rec]
    assert rec["names"] == ["Bob Smith"] and rec["decision"] is None
    assert rec["id"].startswith("cc_") and len(rec["hits"]) == 1
    assert conflicts.has_unresolved_conflict(new)
    rec["decision"] = "cleared"
    assert not conflicts.has_unresolved_conflict(new)


def test_firm_log_capped_and_redacted(make_client, tmp_path, monkeypatch):
    make_client("c1", client_name="Robert Smith")
    monkeypatch.setattr(conflicts, "_FIRM_LOG_MAX", 3)
    for _ in range(5):
        hits = conflicts.run_conflict_check(other_names=["Robert Smith"])
        conflicts.append_firm_log(conflicts.make_check_record("manual", "Endocide",
                                                              ["Robert Smith"], hits))
    log = json.loads((tmp_path / "security" / "conflict-checks.json").read_text())
    assert len(log) == 3
    assert "username" not in log[0]["hits"][0]


def test_clean_names_and_related():
    assert conflicts.clean_names([" A ", "", "a", None, "B" * 300]) == ["A", "B" * 200]
    assert conflicts.clean_related([{"name": " X ", "relationship": "Spouse"},
                                    {"name": ""}, "junk"]) ==            [{"name": "X", "relationship": "Spouse"}]


def test_record_check_incomplete_on_undecryptable(make_client, tmp_path):
    make_client("c1", client_name="Robert Smith")
    (tmp_path / "accounts" / "bad.json").write_bytes(b"not-a-fernet-token")
    new = {"username": "newc"}
    rec = conflicts.record_check(new, "create", "Endocide", client_names=["Bob Smith"])
    assert rec["incomplete"] == 1
    ok = conflicts.record_check({"username": "n2"}, "create", "Endocide", client_names=["x"])
    assert ok["incomplete"] == 1  # still one undecryptable file


def test_all_clients_skipped_list(make_client, tmp_path):
    make_client("c1")
    (tmp_path / "accounts" / "bad.json").write_bytes(b"not-a-fernet-token")
    skipped = []
    assert len(storage.all_clients(skipped)) == 1
    assert skipped == ["bad"]


def test_firm_log_corrupt_file_preserved(tmp_path):
    path = tmp_path / "security" / "conflict-checks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    conflicts.append_firm_log(conflicts.make_check_record("manual", "Endocide", ["X"], []))
    assert len(json.loads(path.read_text())) == 1
    kept = list(path.parent.glob("conflict-checks.json.corrupt-*"))
    assert len(kept) == 1 and kept[0].read_text() == "{not json"


def test_check_id_has_more_entropy():
    rec = conflicts.make_check_record("manual", "Endocide", [], [])
    assert len(rec["id"].rsplit("_", 1)[1]) == 8
