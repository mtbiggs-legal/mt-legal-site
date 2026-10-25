"""Per-attorney statement thresholds (spec A4)."""

import pytest

import billing
import shared


def test_default_threshold():
    assert billing.get_threshold("Endocide") == 2000.0
    assert billing.get_threshold(None) == 2000.0


def test_set_and_get_per_attorney():
    assert billing.set_threshold("SophiaH", "1500") == 1500.0
    assert billing.get_threshold("SophiaH") == 1500.0
    assert billing.get_threshold("Endocide") == 2000.0


@pytest.mark.parametrize("bad", [99, 100001, "abc", None, float("nan"), float("inf")])
def test_set_threshold_rejects(bad):
    with pytest.raises(ValueError):
        billing.set_threshold("Endocide", bad)


def test_corrupt_settings_file_falls_back(capsys):
    (shared.FIRM_SETTINGS_DIR / "attorney-settings.json").write_text("{nope")
    assert billing.get_threshold("Endocide") == 2000.0
    assert "unreadable" in capsys.readouterr().err


def test_out_of_range_stored_value_falls_back():
    (shared.FIRM_SETTINGS_DIR / "attorney-settings.json").write_text(
        '{"Endocide": {"statement_threshold": 5}}')
    assert billing.get_threshold("Endocide") == 2000.0


def test_migration_flag(tmp_path):
    assert billing.is_migrated()            # conftest marks it
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert not billing.is_migrated()
    billing.mark_migrated()
    assert billing.is_migrated()
