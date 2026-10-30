"""_log_activity appends timestamped entries to a client's activity log."""

import json
from datetime import datetime

from services import storage


def test_log_activity_appends_entry(tmp_path):
    (tmp_path / "accounts" / "testU.json").write_text(
        json.dumps({"username": "testU", "activity_log": []})
    )

    storage._log_activity("testU", "note_saved", "Test note saved.")

    updated = storage._read_record(tmp_path / "accounts" / "testU.json")
    assert len(updated["activity_log"]) == 1
    entry = updated["activity_log"][0]
    assert entry["action_type"] == "note_saved"
    assert entry["description"] == "Test note saved."
    datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%S")


def test_log_activity_creates_log_if_missing(tmp_path):
    (tmp_path / "accounts" / "testU2.json").write_text(
        json.dumps({"username": "testU2"})  # no activity_log key
    )

    storage._log_activity("testU2", "intake", "Client intake completed.")

    updated = storage._read_record(tmp_path / "accounts" / "testU2.json")
    assert len(updated["activity_log"]) == 1


def test_log_activity_silently_skips_missing_client(tmp_path):
    storage._log_activity("nonexistent", "note_saved", "whatever")
    assert not (tmp_path / "accounts" / "nonexistent.json").exists()
