"""Scheduling-order extraction (spec B)."""

import json
import types

import pytest

from services import scheduling_orders as so
import shared


GOOD = {
    "dates": {
        "first_discussion":  {"date": "2026-11-04", "page": 2, "evidence": "Initial conference on November 4, 2026", "confidence": "high"},
        "second_discussion": {"date": None, "page": None, "evidence": "", "confidence": "low"},
        "motions":           {"date": "2027-01-15", "page": 3, "evidence": "Dispositive motions due Jan. 15, 2027", "confidence": "high"},
        "pretrial":          {"date": "1999-01-01", "page": 3, "evidence": "x", "confidence": "high"},
        "trial":             {"date": "2027-13-40", "page": 4, "evidence": "y" * 500, "confidence": "medium"},
    },
    "notes": "n" * 2000,
}


class _Fake:
    def __init__(self, payload=None, stop="end_turn", raise_exc=None):
        self.calls, self.payload, self.stop, self.raise_exc = [], payload, stop, raise_exc
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.raise_exc:
            raise self.raise_exc
        text = json.dumps(self.payload) if not isinstance(self.payload, str) else self.payload
        return types.SimpleNamespace(
            stop_reason=self.stop, model=kw["model"],
            content=[types.SimpleNamespace(type="text", text=text)],
            usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def fake(monkeypatch):
    f = _Fake(GOOD)
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: f)
    return f


def test_pdf_request_shape(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(so, "SCHEDULING_ORDER_MODEL", "claude-opus-5-5")
    p = tmp_path / "o.pdf"; p.write_bytes(b"%PDF-1.4 fake")
    so.extract_case_dates(p)
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 16000
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["extra_body"] == {"fallbacks": "default"}
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in kw and "tool_choice" not in kw
    blocks = kw["messages"][0]["content"]
    assert blocks[0]["type"] == "document" and blocks[0]["source"]["media_type"] == "application/pdf"
    assert "\n" not in blocks[0]["source"]["data"] and blocks[-1]["type"] == "text"


def test_image_docx_txt(tmp_path, fake, monkeypatch):
    (tmp_path / "o.png").write_bytes(b"\x89PNG")
    so.extract_case_dates(tmp_path / "o.png")
    assert fake.calls[-1]["messages"][0]["content"][0]["type"] == "image"
    import mammoth
    monkeypatch.setattr(mammoth, "extract_raw_text",
                        lambda f: types.SimpleNamespace(value="Trial set for March 1, 2027"), raising=False)
    (tmp_path / "o.docx").write_bytes(b"PK")
    so.extract_case_dates(tmp_path / "o.docx")
    first = fake.calls[-1]["messages"][0]["content"][0]
    assert first["type"] == "text" and "<document>" in first["text"] and "March 1, 2027" in first["text"]
    (tmp_path / "o.txt").write_text("Trial 2027-03-01")
    so.extract_case_dates(tmp_path / "o.txt")
    assert "Trial 2027-03-01" in fake.calls[-1]["messages"][0]["content"][0]["text"]


def test_validation(tmp_path, fake):
    p = tmp_path / "o.pdf"; p.write_bytes(b"%PDF")
    r = so.extract_case_dates(p)
    d = r["dates"]
    assert d["first_discussion"]["date"] == "2026-11-04" and d["first_discussion"]["page"] == 2
    assert d["second_discussion"]["date"] is None
    assert d["pretrial"]["date"] is None and d["pretrial"]["confidence"] == "low"    # out of range
    assert d["trial"]["date"] is None and len(d["trial"]["evidence"]) == 200       # unparseable, truncated
    assert len(r["notes"]) <= 1000 and r["usage"].input_tokens == 10
    assert set(d) == set(so.CASE_DATE_KINDS)


@pytest.mark.parametrize("fake_kw,msg", [
    ({"stop": "refusal"}, "declined"),
    ({"stop": "max_tokens"}, "cut off"),
    ({"payload": "not json"}, "unavailable"),
])
def test_failures(tmp_path, monkeypatch, fake_kw, msg):
    f = _Fake(**{"payload": GOOD, **fake_kw})
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: f)
    p = tmp_path / "o.pdf"; p.write_bytes(b"%PDF")
    with pytest.raises(so.ExtractionError, match=msg):
        so.extract_case_dates(p)


def test_api_error_and_no_key(tmp_path, monkeypatch):
    import anthropic
    p = tmp_path / "o.pdf"; p.write_bytes(b"%PDF")
    f = _Fake(GOOD, raise_exc=anthropic.APIError("boom"))
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: f)
    with pytest.raises(so.ExtractionError, match="unavailable"):
        so.extract_case_dates(p)
    def no_key(): raise ValueError("ANTHROPIC_API_KEY is not set")
    monkeypatch.setattr(shared, "get_anthropic_client", no_key)
    with pytest.raises(so.ExtractionError, match="not configured"):
        so.extract_case_dates(p)


def test_limits(tmp_path, fake, monkeypatch):
    with pytest.raises(so.ExtractionError, match="file type"):
        p = tmp_path / "o.xlsx"; p.write_bytes(b"x"); so.extract_case_dates(p)
    monkeypatch.setattr(so, "MAX_BYTES", 3)
    with pytest.raises(so.ExtractionError, match="too large"):
        p = tmp_path / "big.pdf"; p.write_bytes(b"%PDF-1.4"); so.extract_case_dates(p)
    assert fake.calls == []


def _run(tmp_path, monkeypatch, payload, name="o.pdf", data=b"%PDF"):
    f = _Fake(payload)
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: f)
    p = tmp_path / name; p.write_bytes(data)
    return so.extract_case_dates(p)


def test_model_shape_tolerated(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, {"dates": {"trial": "2027-01-01"}, "notes": ""})
    assert r["dates"]["trial"]["date"] is None
    for bad in ({"dates": []}, [1], {"dates": "x"}):
        with pytest.raises(so.ExtractionError, match="unavailable"):
            _run(tmp_path, monkeypatch, bad)


def test_dates_normalised_and_page_strict(tmp_path, monkeypatch):
    entry = lambda **kw: {"date": "2027-1-5", "page": 1, "evidence": "", "confidence": "high", **kw}
    r = _run(tmp_path, monkeypatch, {"dates": {
        "trial": entry(), "motions": entry(page=True), "pretrial": entry(page=0)}, "notes": ""})
    assert r["dates"]["trial"]["date"] == "2027-01-05" and r["dates"]["trial"]["page"] == 1
    assert r["dates"]["motions"]["page"] is None and r["dates"]["pretrial"]["page"] is None


def test_docx_failures(tmp_path, fake, monkeypatch):
    import mammoth
    def bad(f): raise RuntimeError("corrupt")
    monkeypatch.setattr(mammoth, "extract_raw_text", bad, raising=False)
    (tmp_path / "o.docx").write_bytes(b"PK")
    with pytest.raises(so.ExtractionError, match="Word file"):
        so.extract_case_dates(tmp_path / "o.docx")
    monkeypatch.setattr(mammoth, "extract_raw_text",
                        lambda f: types.SimpleNamespace(value="  "), raising=False)
    with pytest.raises(so.ExtractionError, match="no readable text"):
        so.extract_case_dates(tmp_path / "o.docx")
    assert fake.calls == []


def test_per_type_caps(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(so, "MAX_IMAGE_BYTES", 3)
    (tmp_path / "big.png").write_bytes(b"12345678")
    with pytest.raises(so.ExtractionError, match="too large"):
        so.extract_case_dates(tmp_path / "big.png")
    monkeypatch.setattr(so, "MAX_TEXT_CHARS", 5)
    (tmp_path / "big.txt").write_text("123456789")
    with pytest.raises(so.ExtractionError, match="too large"):
        so.extract_case_dates(tmp_path / "big.txt")
    assert fake.calls == []


def test_too_many_pages_only_on_400(tmp_path, monkeypatch):
    import anthropic
    class Err(anthropic.APIError):
        def __init__(self, msg, status): super().__init__(msg); self.status_code = status
    p = tmp_path / "o.pdf"; p.write_bytes(b"%PDF")
    for status, msg in ((400, "too many pages"), (500, "unavailable")):
        f = _Fake(GOOD, raise_exc=Err("page limit", status))
        monkeypatch.setattr(shared, "get_anthropic_client", lambda f=f: f)
        with pytest.raises(so.ExtractionError, match=msg):
            so.extract_case_dates(p)
