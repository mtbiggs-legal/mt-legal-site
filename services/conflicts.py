"""conflicts.py — fuzzy conflict-of-interest checks across clients, parties, and leads.

Used by intake, client creation, self-registration, the manual Conflict Check
tool, and client edits. Every check is recorded (see make_check_record).
"""

import json
import os
import re
import secrets
import sys
import threading
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

import shared
from services import storage
from services import accounts

LIKELY           = 0.85
POSSIBLE         = 0.70
SINGLE_TOKEN_CAP = 0.75   # one-word names can be "possible" at most

_DROP_WORDS = frozenset({
    "mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii", "iv", "esq",
    "llc", "inc", "corp", "co", "ltd", "lp", "llp", "pllc", "company", "corporation",
    "incorporated", "limited", "the", "and", "pc", "pa", "plc", "group", "holdings",
})

_NICKNAMES = {
    "bob": "robert", "bobby": "robert", "rob": "robert", "robbie": "robert",
    "bill": "william", "billy": "william", "will": "william",
    "rick": "richard", "rich": "richard", "dick": "richard",
    "jim": "james", "jimmy": "james",
    "jack": "john", "johnny": "john",
    "liz": "elizabeth", "beth": "elizabeth", "betsy": "elizabeth",
    "kate": "katherine", "kathy": "katherine", "katie": "katherine",
    "maggie": "margaret", "peggy": "margaret",
    "mike": "michael", "chris": "christopher", "tony": "anthony", "joe": "joseph",
    "tom": "thomas", "tommy": "thomas", "dan": "daniel", "danny": "daniel",
    "jen": "jennifer", "jenny": "jennifer", "pat": "patricia", "patty": "patricia",
    "alex": "alexander",
}


def normalise_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    tokens = re.sub(r"[\W_]", " ", text.replace("&", " ")).split()
    kept = " ".join(_NICKNAMES.get(t, t) for t in tokens if t not in _DROP_WORDS)
    return kept or " ".join(tokens)   # all words were droppable: keep them as-is


def name_similarity(a: str, b: str) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    direct    = SequenceMatcher(None, na, nb).ratio()
    tokenwise = SequenceMatcher(None, " ".join(sorted(na.split())),
                                " ".join(sorted(nb.split()))).ratio()
    score = max(direct, tokenwise)
    ta, tb = na.split(), nb.split()
    if len(ta) == 1 or len(tb) == 1:
        score = min(score, SINGLE_TOKEN_CAP)
        if (len(ta) == 1 and ta[0] == tb[-1]) or (len(tb) == 1 and tb[0] == ta[-1]):
            score = max(score, POSSIBLE)
    return round(score, 3)


def level_for(score: float):
    if score >= LIKELY:
        return "likely"
    if score >= POSSIBLE:
        return "possible"
    return None


# ── Search ────────────────────────────────────────────────────────────────────

def _display(attorney: str) -> str:
    return shared.ATTORNEYS.get(attorney, {}).get("display", attorney or "")


def _candidates(exclude_username=None, skipped=None):
    for c in storage.all_clients(skipped):
        uname = c.get("username")
        if uname == exclude_username:
            continue
        atty = c.get("assigned_attorney", "")
        base = {"username": uname, "lead_file": None, "relationship": None,
                "matter": c.get("case_type", ""), "assigned_attorney": atty,
                "assigned_attorney_display": _display(atty)}
        if c.get("client_name"):
            yield dict(base, matched_name=c["client_name"],
                       source="former_client" if c.get("archived") else "client")
        for opp in c.get("opposing_parties") or []:
            yield dict(base, matched_name=opp, source="opposing_party")
        for rel in c.get("related_parties") or []:
            if isinstance(rel, dict) and rel.get("name"):
                yield dict(base, matched_name=rel["name"], source="related_party",
                           relationship=rel.get("relationship", ""))
    for path in sorted(shared.LEADS_DIR.glob("*.json")):
        try:
            lead = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if lead.get("archived") or not lead.get("name"):
            continue
        atty = lead.get("assigned_attorney", "")
        yield {"username": None, "lead_file": path.name, "relationship": None,
               "matter": lead.get("case_type", ""), "assigned_attorney": atty,
               "assigned_attorney_display": _display(atty),
               "matched_name": lead["name"], "source": "lead"}


def run_conflict_check(client_names=(), opposing_names=(), related_names=(),
                       other_names=(), exclude_username=None, skipped=None) -> list:
    """Return hits. If `skipped` is a list, usernames of undecryptable records are appended."""
    searched = ([(n, "client") for n in clean_names(client_names)]
                + [(n, "opposing") for n in clean_names(opposing_names)]
                + [(n, "related") for n in clean_names(related_names)]
                + [(n, "other") for n in clean_names(other_names)])
    if not searched:
        return []
    candidates = list(_candidates(exclude_username, skipped))
    hits = []
    for name, role in searched:
        for cand in candidates:
            score = name_similarity(name, cand["matched_name"])
            level = level_for(score)
            if not level:
                continue
            adverse = ((role == "opposing" and cand["source"] in ("client", "former_client"))
                       or (role == "client" and cand["source"] == "opposing_party"))
            hits.append(dict(cand, searched_name=name, searched_role=role,
                             score=score, level=level, adverse=adverse))
    hits.sort(key=lambda h: (h["level"] != "likely", -h["score"]))
    return hits


# ── Input cleaning ────────────────────────────────────────────────────────────

def clean_names(names) -> list:
    out, seen = [], set()
    for n in names or []:
        if not isinstance(n, str):
            continue
        n = n.strip()[:200]
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:50]


def clean_related(items) -> list:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:200]
        if name:
            out.append({"name": name,
                        "relationship": str(item.get("relationship") or "").strip()[:60]})
    return out[:50]


# ── Records ───────────────────────────────────────────────────────────────────

DECISIONS = ("cleared", "waiver_obtained", "declined")


def make_check_record(trigger: str, run_by: str, names, hits) -> dict:
    now = datetime.now()
    return {
        "id":            f"cc_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(4)}",
        "timestamp":     now.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_by":        run_by,
        "trigger":       trigger,
        "names":         list(names),
        "hits":          hits,
        "decision":      None,
        "decision_note": "",
        "decided_by":    None,
        "decided_at":    None,
    }


def record_check(client: dict, trigger: str, run_by: str, client_names=(),
                 opposing_names=(), related_names=(), other_names=()) -> dict:
    """Run a check and append the record to client['conflict_checks'] (caller saves)."""
    skipped = []
    hits = run_conflict_check(client_names, opposing_names, related_names, other_names,
                              exclude_username=client.get("username"), skipped=skipped)
    names = (clean_names(client_names) + clean_names(opposing_names)
             + clean_names(related_names) + clean_names(other_names))
    rec = make_check_record(trigger, run_by, names, hits)
    if skipped:
        rec["incomplete"] = len(skipped)
    client.setdefault("conflict_checks", []).append(rec)
    return rec


def has_unresolved_conflict(client: dict) -> bool:
    return any(c.get("hits") and not c.get("decision")
               for c in client.get("conflict_checks") or [])


# ── Redaction (applied whenever hits leave the server) ────────────────────────

PUBLIC_HIT_FIELDS = ("searched_name", "searched_role", "matched_name", "score", "level",
                     "source", "matter", "assigned_attorney_display", "adverse")


def _viewer_can_see(hit: dict, viewer: str) -> bool:
    if hit.get("username"):
        try:
            c = storage.load_client(hit["username"])
        except storage.RecordDecryptError:
            return False
        return bool(c) and accounts.can_access_client(viewer, c)
    return hit.get("assigned_attorney") == viewer


def _public(hit: dict) -> dict:
    return {k: hit.get(k) for k in PUBLIC_HIT_FIELDS}


def redact_hits(hits, viewer: str) -> list:
    cache, out = {}, []
    for h in hits or []:
        key = ("u", h["username"]) if h.get("username") else ("l", h.get("assigned_attorney"))
        if key not in cache:
            cache[key] = _viewer_can_see(h, viewer)
        out.append(dict(h) if cache[key] else _public(h))
    return out


def redact_checks(checks, viewer: str) -> list:
    return [dict(c, hits=redact_hits(c.get("hits"), viewer)) for c in checks or []]


_SOURCE_LABEL = {
    "client":         "an existing client",
    "former_client":  "a former client",
    "opposing_party": "an opposing party in another matter",
    "related_party":  "a related party in another matter",
    "lead":           "a prospective client (lead)",
}


def hit_message(hit: dict) -> str:
    msg = (f"{hit['level'].capitalize()} match: '{hit['searched_name']}' ≈ "
           f"'{hit['matched_name']}' — {_SOURCE_LABEL.get(hit['source'], hit['source'])}")
    if hit.get("relationship"):
        msg += f" ({hit['relationship']})"
    if hit.get("matter"):
        msg += f", {hit['matter']}"
    if hit.get("assigned_attorney_display"):
        msg += f"; handled by {hit['assigned_attorney_display']}"
    if hit.get("adverse"):
        msg += " — potentially adverse"
    return msg + "."


# ── Firm-wide log for checks not attached to a client ─────────────────────────

_FIRM_LOG_MAX  = 2000
_firm_log_lock = threading.Lock()


def append_firm_log(record: dict) -> None:
    path  = shared.SECURITY_STATE_DIR / "conflict-checks.json"
    entry = dict(record, hits=[_public(h) for h in record.get("hits") or []])
    with _firm_log_lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            print(f"[warn] {path.name} unreadable - preserved as .corrupt-{stamp}", file=sys.stderr)
            try:
                os.replace(path, path.with_name(f"{path.name}.corrupt-{stamp}"))
            except OSError:
                pass
            data = []
        data.append(entry)
        storage.write_json(path, data[-_FIRM_LOG_MAX:])
