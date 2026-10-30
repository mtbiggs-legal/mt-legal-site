"""Statement notices: claim → send → finalise (spec B3, C4)."""

import threading

from services import billing
import blueprints.email_service as email_service
from services import storage


def _issue(make_client, email="c@example.com", username="nt"):
    make_client(username, email=email, client_name="Nora T",
                billing_log=[{"date": "2026-10-01", "hours": 1.0, "note": "x"}], hours_billed=1.0)
    return billing.issue_statement(username, reason="manual", issued_by="Endocide", notify=True)


def _status(username="nt"):
    return billing.load_ledger(username)["statements"][-1]["notice"]


def test_sent(make_client, sent_statement_emails):
    st = _issue(make_client)
    billing.send_pending_notices("nt")
    assert _status()["status"] == "sent"
    (args, _), = sent_statement_emails
    assert args == ("Nora T", "c@example.com", st["number"], st["amount"], st["billed_through"])


def test_not_configured_and_failed(make_client, monkeypatch):
    _issue(make_client)
    monkeypatch.setattr(email_service, "send_statement_email", lambda *a: "not_configured")
    billing.send_pending_notices("nt")
    assert (_status()["status"], _status()["error"]) == ("failed", "email not configured")
    assert billing.request_resend("nt", "st_1")
    monkeypatch.setattr(email_service, "send_statement_email", lambda *a: "failed")
    billing.send_pending_notices("nt")
    assert (_status()["status"], _status()["error"]) == ("failed", "send failed")


def test_sender_exception_is_failed(make_client, monkeypatch):
    _issue(make_client)
    monkeypatch.setattr(email_service, "send_statement_email",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down")))
    billing.send_pending_notices("nt")
    assert _status()["status"] == "failed"


def test_no_or_invalid_email(make_client, sent_statement_emails):
    _issue(make_client, email="not-an-email")
    billing.send_pending_notices("nt")
    assert _status()["status"] == "no_email" and sent_statement_emails == []


def test_concurrent_dispatch_sends_once(make_client, monkeypatch):
    _issue(make_client)
    calls = []
    entered, gate = threading.Event(), threading.Event()

    def slow(*a):
        calls.append(a)
        entered.set()
        gate.wait(5)
        return "sent"

    monkeypatch.setattr(email_service, "send_statement_email", slow)
    first = threading.Thread(target=billing.send_pending_notices, args=("nt",))
    first.start()
    assert entered.wait(5)
    assert _status()["status"] == "sending"          # claimed, send in flight
    others = [threading.Thread(target=billing.send_pending_notices, args=("nt",))
              for _ in range(3)]
    [t.start() for t in others]
    [t.join(5) for t in others]
    gate.set()
    first.join(5)
    assert len(calls) == 1 and _status()["status"] == "sent"


def test_stale_client_save_does_not_resend(make_client, sent_statement_emails):
    _issue(make_client)
    stale = storage.load_client("nt")
    billing.send_pending_notices("nt")
    storage.save_client(stale)            # triggers after_client_save
    assert len(sent_statement_emails) == 1


def test_stale_sending_is_reclaimed(make_client, monkeypatch, sent_statement_emails):
    _issue(make_client)
    led = billing.load_ledger("nt")
    led["statements"][0]["notice"].update(status="sending", claimed_at="2000-01-01T00:00:00")
    billing._write_ledger("nt", led)
    billing.send_pending_notices("nt")
    assert _status()["status"] == "sent"


def test_resend_refused_when_sent_or_fresh_sending(make_client):
    _issue(make_client)
    billing.send_pending_notices("nt")
    assert billing.request_resend("nt", "st_1") is False
    assert billing.request_resend("nt", "st_999") is False
    led = billing.load_ledger("nt")
    led["statements"][0]["notice"].update(status="sending", claimed_at=billing._now())
    billing._write_ledger("nt", led)
    assert billing.request_resend("nt", "st_1") is False       # fresh claim: refused


def test_unsafe_usernames_rejected_without_locking():
    before = set(billing._ledger_locks)
    assert billing.request_resend("../client-accounts/x", "st_1") is False
    billing.send_pending_notices("../x")                        # must not raise
    assert "../x" not in billing._ledger_locks
    assert "../client-accounts/x" not in billing._ledger_locks
    assert set(billing._ledger_locks) == before
    try:
        billing._ledger_path("../x")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unsafe username" in str(exc)


def test_stale_sender_cannot_overwrite_reclaim(make_client):
    _issue(make_client)
    led = billing.load_ledger("nt")
    led["statements"][0]["notice"].update(status="sending", claimed_at="2026-10-01T10:00:00")
    billing._write_ledger("nt", led)
    old_claim = [billing.load_ledger("nt")["statements"][0]]
    # Someone re-claims it (newer claimed_at) while the original sender is still working.
    led = billing.load_ledger("nt")
    led["statements"][0]["notice"]["claimed_at"] = "2026-10-01T11:00:00"
    billing._write_ledger("nt", led)
    billing._deliver("nt", old_claim)
    notice = _status()
    assert notice["status"] == "sending" and notice["claimed_at"] == "2026-10-01T11:00:00"


def test_async_notice_delivery(make_client, monkeypatch):
    _issue(make_client)
    monkeypatch.setattr(billing, "NOTICE_ASYNC", True)
    spawned = []
    real_thread = threading.Thread

    class _RecordingThread(real_thread):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            spawned.append(self)

    monkeypatch.setattr(billing.threading, "Thread", _RecordingThread)
    billing.send_pending_notices("nt")
    assert spawned
    for t in spawned:
        t.join()
    assert _status()["status"] == "sent"


def test_send_statement_email_not_configured(monkeypatch):
    from conftest import REAL_SEND_STATEMENT_EMAIL
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    assert REAL_SEND_STATEMENT_EMAIL("A", "a@b.co", 1, 10.0, "2026-10-01") == "not_configured"
