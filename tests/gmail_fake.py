"""An in-memory stand-in for the Gmail API client, built from sample emails.

Implements only the calls services/gmail.py makes, and records every call so
tests can check the reviewer never does anything but read, label and send to
itself. Used by tests/test_email_review.py and scripts/email_review_demo.py.
"""

import base64
import email
from email import policy
import json
from datetime import datetime
from pathlib import Path

SAMPLES_FILE = Path(__file__).parent / "fixtures" / "sample_emails.json"
ACCOUNT = "firm@mtlegal.example"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def load_samples() -> list:
    return json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))


def to_gmail_message(sample: dict) -> dict:
    """A sample as Gmail returns it with format=full."""
    parts = []
    if sample.get("body"):
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(sample["body"])}})
    if sample.get("html"):
        parts.append({"mimeType": "text/html", "body": {"data": _b64(sample["html"])}})
    for name in sample.get("attachments", []):
        parts.append({"mimeType": "application/pdf", "filename": name,
                      "body": {"attachmentId": "att-" + name}})
    headers = ([{"name": "Authentication-Results", "value": sample["auth_results"]}]
               if sample.get("auth_results") else [])
    headers += [{"name": "From", "value": sample["from"]},
               {"name": "To", "value": sample.get("to", ACCOUNT)},
               {"name": "Subject", "value": sample["subject"]},
               {"name": "Date", "value": sample.get("date", "")}]
    received = datetime.fromisoformat(sample.get("received", "2026-11-04T08:00:00"))
    return {
        "id": sample["id"], "threadId": "t" + sample["id"],
        "internalDate": str(int(received.timestamp() * 1000)),
        "snippet": (sample.get("body") or "")[:100],
        "payload": {"mimeType": "multipart/mixed", "headers": headers, "parts": parts},
    }


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmail:
    """users() returns self, so service.users().messages()... works."""

    def __init__(self, samples=None, account=ACCOUNT):
        self.account = account
        self.messages_by_id = {s["id"]: to_gmail_message(s) for s in (samples or load_samples())}
        self.label_store = {}      # label name -> id
        self.added = {}            # msg id -> [label ids added]
        self.sent = []             # parsed email.message.Message objects
        self.calls = []            # (method, details)
        self.fail_get = set()      # msg ids whose fetch raises

    def users(self):
        return self

    def getProfile(self, userId):
        self.calls.append(("getProfile", {"userId": userId}))
        return _Call(lambda: {"emailAddress": self.account})

    def messages(self):
        return _Messages(self)

    def labels(self):
        return _Labels(self)


class _Messages:
    def __init__(self, fake):
        self.f = fake

    def list(self, userId, q, maxResults):
        self.f.calls.append(("messages.list", {"q": q, "maxResults": maxResults}))
        after = int(q.split("after:")[1].split()[0])
        def run():
            msgs = sorted(self.f.messages_by_id.values(), key=lambda m: -int(m["internalDate"]))
            hits = [{"id": m["id"]} for m in msgs if int(m["internalDate"]) // 1000 > after]
            return {"messages": hits[:maxResults]} if hits else {}
        return _Call(run)

    def get(self, userId, id, format):
        self.f.calls.append(("messages.get", {"id": id, "format": format}))
        def run():
            if id in self.f.fail_get:
                raise RuntimeError("fetch failed")
            return self.f.messages_by_id[id]
        return _Call(run)

    def modify(self, userId, id, body):
        self.f.calls.append(("messages.modify", {"id": id, "body": body}))
        def run():
            self.f.added.setdefault(id, []).extend(body.get("addLabelIds", []))
            return {"id": id}
        return _Call(run)

    def send(self, userId, body):
        self.f.calls.append(("messages.send", {}))
        def run():
            raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
            self.f.sent.append(email.message_from_bytes(raw, policy=policy.default))
            return {"id": f"sent{len(self.f.sent)}"}
        return _Call(run)


class _Labels:
    def __init__(self, fake):
        self.f = fake

    def list(self, userId):
        self.f.calls.append(("labels.list", {}))
        return _Call(lambda: {"labels": [{"name": n, "id": i} for n, i in self.f.label_store.items()]})

    def create(self, userId, body):
        self.f.calls.append(("labels.create", {"name": body["name"]}))
        def run():
            lid = f"Label_{len(self.f.label_store) + 1}"
            self.f.label_store[body["name"]] = lid
            return {"id": lid, "name": body["name"]}
        return _Call(run)


def keyword_classifier(msg, matched_client, received):
    """A deterministic stand-in for Claude, for offline tests and demos."""
    text = (msg.get("subject", "") + " " + msg.get("body", "")).lower()
    if "ignore your previous instructions" in text or "verify your password" in text:
        return {"category": "spam", "urgent": False, "urgency_reason": "", "deadlines": [],
                "summary": "Phishing attempt posing as an e-filing system."}
    if "wire my settlement" in text:
        return {"category": "other", "urgent": True,
                "urgency_reason": "Asks to redirect settlement funds; possible payment fraud.",
                "deadlines": [], "summary": "Request to wire settlement funds to a new account."}
    if "notice of hearing" in text:
        return {"category": "court", "urgent": True,
                "urgency_reason": "Hearing on Nov 12; response due Nov 10.",
                "deadlines": [{"date": "2026-11-12", "description": "Motion hearing"},
                              {"date": "2026-11-10", "description": "Response to motion in limine"}],
                "summary": "Court set a motion hearing in State v. Ellis."}
    if "arrested" in text:
        return {"category": "new_client", "urgent": True, "urgency_reason": "Son in jail; arraignment tomorrow.",
                "deadlines": [], "summary": "Parent asking for DUI representation for her son."}
    if matched_client:
        return {"category": "existing_client", "urgent": False, "urgency_reason": "",
                "deadlines": [], "summary": "Client asking for a case update."}
    if "payout" in text:
        return {"category": "billing", "urgent": False, "urgency_reason": "", "deadlines": [],
                "summary": "Stripe payout of $1,750 on the way."}
    if "cle" in text:
        return {"category": "vendor", "urgent": False, "urgency_reason": "", "deadlines": [],
                "summary": "CLE reminder."}
    if "interrogatories" in text:
        return {"category": "court", "urgent": False, "urgency_reason": "", "deadlines": [
            {"date": None, "description": "Discovery responses due 30 days from service"}],
                "summary": "Opposing counsel served first interrogatories and RFPs."}
    return {"category": "spam", "urgent": False, "urgency_reason": "", "deadlines": [],
            "summary": "Marketing email."}
