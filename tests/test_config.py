"""config.Settings: one place that reads the environment."""

from pathlib import Path

import app as app_module
import shared
from config import Settings


def test_defaults_from_an_empty_environment(tmp_path):
    s = Settings(env={}, base_dir=tmp_path)
    assert s.HOURLY_RATE == 350.0 and s.DATA_ROOT == tmp_path
    assert s.ATTORNEY_2FA_REQUIRED and s.DROPBOX_SIGN_TEST_MODE and s.EMAIL_REVIEW_AUTO
    assert not s.IS_PRODUCTION and not s.PUBLIC_SITE_ONLY and not s.BLOG_AUTOGEN
    assert s.DB_PATH == tmp_path / "db" / "mt-legal.db"
    assert s.problems == []


def test_values_from_the_environment(tmp_path):
    s = Settings(env={"APP_ENV": "'production'", "PUBLIC_SITE_ONLY": ' "1" ', "ATTORNEY_2FA": "off",
                      "DATA_DIR": str(tmp_path / "data"), "HOURLY_RATE": "400",
                      "PORTAL_URL": "https://portal.example.test/"}, base_dir=tmp_path)
    assert s.IS_PRODUCTION and s.PUBLIC_SITE_ONLY and not s.ATTORNEY_2FA_REQUIRED
    assert s.LEADS_DIR == tmp_path / "data" / "leads"
    assert s.HOURLY_RATE == 400.0 and s.PORTAL_URL == "https://portal.example.test"


def test_bad_values_are_reported_not_fatal(tmp_path):
    s = Settings(env={"HOURLY_RATE": "abc", "EMAIL_DIGEST_HOUR": "seven",
                      "PORTAL_URL": "portal.example.test"}, base_dir=tmp_path)
    assert s.HOURLY_RATE == 350.0 and s.EMAIL_DIGEST_HOUR == 7
    assert len(s.problems) == 3 and any("PORTAL_URL" in p for p in s.problems)


def test_problems_stop_startup(monkeypatch):
    monkeypatch.setattr(shared.settings, "problems", ["HOURLY_RATE='abc' is not a number"])
    assert any("HOURLY_RATE" in p for p in app_module.check_startup_config())


def test_shared_publishes_every_setting():
    for name, value in shared.settings.as_dict().items():
        assert hasattr(shared, name), name
    assert shared.BASE_DIR == Path(shared.__file__).parent


def test_decorators_still_come_from_shared():
    import access
    assert shared.require_attorney is access.require_attorney
    assert shared.public is access.public
