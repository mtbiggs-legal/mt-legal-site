"""_log_activity appends timestamped entries to a client's activity log."""

from datetime import datetime

from services import storage
from conftest import get_record, put_record


def test_log_activity_appends_entry(tmp_path):
    put_record({"username": "testU", "activity_log": []})

    storage._log_activity("testU", "note_saved", "Test note saved.")

    updated = get_record("testU")
    assert len(updated["activity_log"]) == 1
    entry = updated["activity_log"][0]
    assert entry["action_type"] == "note_saved"
    assert entry["description"] == "Test note saved."
    datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%S")


def test_log_activity_creates_log_if_missing(tmp_path):
    put_record({"username": "testU2"})  # no activity_log key

    storage._log_activity("testU2", "intake", "Client intake completed.")

    updated = get_record("testU2")
    assert len(updated["activity_log"]) == 1


def test_log_activity_silently_skips_missing_client(tmp_path):
    storage._log_activity("nonexistent", "note_saved", "whatever")
    assert not storage.client_exists("nonexistent")
