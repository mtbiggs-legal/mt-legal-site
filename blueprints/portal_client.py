"""blueprints/portal_client.py — Client portal: login views, messaging, billing, payments, docs."""

import hmac as _hmac
import hashlib
import requests as _http
import stripe
from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, send_file
from werkzeug.utils import secure_filename

# Payment settings and the hourly rate are read through `shared.` at call time
# rather than imported by value, so a changed setting takes effect without a
# reimport (and so tests can patch one place).
import billing
import shared
from shared import (
    require_client,
    ATTORNEYS, MIN_PASSWORD_LENGTH,
    CLIENT_FILES_DIR,
    DOCS_CATEGORIES,
    load_client, save_client, hash_password, recalc_hours,
    _apply_payment, get_anthropic_client, MODEL,
)

portal_client_bp = Blueprint("portal_client", __name__)


def _balance_for(client: dict):
    """Return (hours_owed, balance_due) from issued statements less payments."""
    due = billing.amount_due(client, billing.load_ledger(client["username"]))
    return (round(due / shared.HOURLY_RATE, 2) if shared.HOURLY_RATE else 0), due


# ── Portal pages ──────────────────────────────────────────────────────────────

@portal_client_bp.route("/client-portal")
@require_client
def client_portal():
    client = load_client(session["username"])
    if client and client.get("must_change_password"):
        return redirect(url_for("portal_client.client_change_password"))
    ledger = billing.load_ledger(session["username"])
    return render_template(
        "client_portal.html", client=client,
        billed_hours=billing.billed_hours(ledger),
        has_new_statement=billing.client_billing_view(client, ledger)["has_new_statement"],
    )


@portal_client_bp.route("/client-portal/change-password", methods=["GET", "POST"])
@require_client
def client_change_password():
    error = None
    if request.method == "POST":
        new_pw  = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if len(new_pw) < MIN_PASSWORD_LENGTH:
            error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif new_pw != confirm:
            error = "Passwords do not match."
        elif new_pw == "password":
            error = "Please choose a password different from the temporary one."
        else:
            client = load_client(session["username"])
            client["password"]             = hash_password(new_pw)
            client["must_change_password"] = False
            save_client(client)
            return redirect(url_for("portal_client.client_portal"))
    return render_template("change_password.html", error=error)


# ── Messaging ─────────────────────────────────────────────────────────────────

@portal_client_bp.route("/portal/client/message", methods=["POST"])
@require_client
def client_send_message():
    data = request.get_json()
    text = (data or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "Message cannot be empty."}), 400

    # Two short atomic updates instead of one load...(AI call)...save: the AI
    # call can take several seconds, and a plain load/save spanning it would
    # silently drop anything written to this client in between (an attorney
    # reply, a second message) because the save at the end only has the copy
    # read at the start. See update_client_atomic's docstring.
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _add_client_message(c):
        c.setdefault("messages", []).append({"from": "client", "date": now, "text": text})
        c["last_communication"] = date.today().isoformat()

    client = shared.update_client_atomic(session["username"], _add_client_message)
    if not client:
        return jsonify({"error": "Account not found."}), 404

    # Generate AI reply
    ai_reply = None
    try:
        attorney_key     = client.get("assigned_attorney", "")
        attorney_display = ATTORNEYS.get(attorney_key, {}).get("display", "your attorney")
        history          = client["messages"][-10:]
        system_prompt = (
            f"You are the MT Legal Assistant, responding on behalf of {attorney_display}.\n\n"
            f"Client: {client.get('client_name', '')}\n"
            f"Case Type: {client.get('case_type', '')}\n"
            f"Legal Issue: {client.get('legal_issue', '')}\n\n"
            "Provide helpful, professional responses. Do NOT give specific legal advice or make "
            "promises about case outcomes. Remind clients messages are reviewed by their attorney. "
            "Sign every response as: \u2014 MT Legal Assistant. Keep responses to 2-4 sentences."
        )
        turns = [
            {"role": "user" if m["from"] == "client" else "assistant", "content": m["text"]}
            for m in history
        ]
        ai = get_anthropic_client()
        resp = ai.messages.create(model=MODEL, max_tokens=300,
                                   system=system_prompt, messages=turns)
        ai_reply = resp.content[0].text

        def _add_ai_reply(c):
            c.setdefault("messages", []).append({
                "from": "ai",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "text": ai_reply,
            })
            c.setdefault("billing_log", []).append({
                "date":     date.today().isoformat(),
                "hours":    0.1,
                "note":     "AI assistant response \u2014 " + text[:60] + ("..." if len(text) > 60 else ""),
                "type":     "ai_message",
                "category": "Phone/Email",
            })
            recalc_hours(c)
            c["last_communication"] = date.today().isoformat()

        shared.update_client_atomic(session["username"], _add_ai_reply)
    except Exception:
        pass  # AI failure is non-fatal

    result = {"success": True}
    if ai_reply:
        result["ai_reply"] = ai_reply
    return jsonify(result)


# ── Billing ───────────────────────────────────────────────────────────────────

@portal_client_bp.route("/portal/client/billing")
@require_client
def client_billing():
    client = load_client(session["username"])
    if not client:
        return jsonify({"error": "Client not found"}), 404
    username = session["username"]
    # Compute the response before marking statements seen.
    payload = {
        **billing.client_billing_view(client, billing.load_ledger(username)),
        "card_enabled":   bool(shared.STRIPE_SECRET_KEY),
        "crypto_enabled": bool(shared.COINBASE_COMMERCE_API_KEY),
    }
    if payload["has_new_statement"]:
        # Record the newest statement shown (not "now"), so a statement issued
        # while this request was running is still flagged as new next time.
        shared.update_client_field_atomic(
            username, "billing_seen_at", payload["statements"][0]["issued_at"])
    return jsonify(payload)


# ── Payments ──────────────────────────────────────────────────────────────────

@portal_client_bp.route("/portal/client/payment/stripe", methods=["POST"])
@require_client
def client_payment_stripe():
    username = session["username"]
    client   = load_client(username)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    if not shared.STRIPE_SECRET_KEY:
        return jsonify({
            "error": "Card payments are not set up yet. Please contact the office to pay by card."
        }), 503
    hours_owed, balance_due = _balance_for(client)
    if balance_due <= 0:
        return jsonify({"error": "No balance due"}), 400

    stripe.api_key = shared.STRIPE_SECRET_KEY
    base = request.host_url.rstrip("/")
    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Legal Services \u2014 Statement balance",
                    },
                    "unit_amount": int(balance_due * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            metadata={"client_username": username},
            success_url=f"{base}/client-portal?tab=billing&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/client-portal?tab=billing",
        )
    except Exception as exc:
        return jsonify({"error": f"Could not start card payment: {exc}"}), 502
    return jsonify({"checkout_url": checkout.url})


@portal_client_bp.route("/webhooks/stripe", methods=["POST"])
def webhook_stripe():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    if not shared.STRIPE_WEBHOOK_SECRET:
        # Without a signing secret any caller could forge a paid invoice.
        return jsonify({"error": "Webhook not configured"}), 503
    try:
        event = stripe.Webhook.construct_event(payload, sig, shared.STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400
    if event.type == "checkout.session.completed":
        obj         = event.data.object
        username    = (obj.metadata or {}).get("client_username")
        amount_paid = round(obj.amount_total / 100, 2)
        _apply_payment(username, amount_paid, "stripe", obj.id)
    return jsonify({"received": True})


@portal_client_bp.route("/portal/client/payment/verify", methods=["POST"])
@require_client
def client_payment_verify():
    """Confirm a Stripe checkout after the browser returns to the portal.

    Webhooks never arrive when the app runs on localhost, so the redirect is the
    only signal that a payment succeeded. _apply_payment is idempotent per
    session id, so this is safe to run alongside the webhook.
    """
    session_id = (request.get_json() or {}).get("session_id", "").strip()
    if not session_id or not shared.STRIPE_SECRET_KEY:
        return jsonify({"credited": False})
    stripe.api_key = shared.STRIPE_SECRET_KEY
    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return jsonify({"credited": False})
    if getattr(checkout, "payment_status", "") != "paid":
        return jsonify({"credited": False})
    username = (getattr(checkout, "metadata", None) or {}).get("client_username")
    if username != session["username"]:
        return jsonify({"credited": False})
    credited = _apply_payment(
        username, round(checkout.amount_total / 100, 2), "stripe", checkout.id
    )
    return jsonify({"credited": bool(credited)})


@portal_client_bp.route("/portal/client/payment/coinbase", methods=["POST"])
@require_client
def client_payment_coinbase():
    username = session["username"]
    client   = load_client(username)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    if not shared.COINBASE_COMMERCE_API_KEY:
        return jsonify({
            "error": "Crypto payments are not set up yet. Please contact the office."
        }), 503
    hours_owed, balance_due = _balance_for(client)
    if balance_due <= 0:
        return jsonify({"error": "No balance due"}), 400

    base = request.host_url.rstrip("/")
    try:
        resp = _http.post(
            "https://api.commerce.coinbase.com/charges",
            headers={
                "X-CC-Api-Key": shared.COINBASE_COMMERCE_API_KEY,
                "X-CC-Version": "2018-03-22",
                "Content-Type": "application/json",
            },
            json={
                "name":         "Legal Services \u2014 Statement balance",
                "description":  "Legal Services \u2014 Statement balance",
                "pricing_type": "fixed_price",
                "local_price":  {"amount": f"{balance_due:.2f}", "currency": "USD"},
                "metadata":     {"client_username": username},
                "redirect_url": f"{base}/client-portal?tab=billing&paid=1",
                "cancel_url":   f"{base}/client-portal?tab=billing",
            },
            timeout=20,
        )
    except Exception as exc:
        return jsonify({"error": f"Could not reach the crypto payment provider: {exc}"}), 502
    if not resp.ok:
        return jsonify({"error": "Failed to create Coinbase charge"}), 502
    return jsonify({"hosted_url": resp.json()["data"]["hosted_url"]})


@portal_client_bp.route("/webhooks/coinbase", methods=["POST"])
def webhook_coinbase():
    payload = request.get_data()
    sig     = request.headers.get("X-CC-Webhook-Signature", "")
    secret  = shared.COINBASE_COMMERCE_WEBHOOK_SECRET
    if not secret:
        # An empty secret makes the HMAC below trivially forgeable.
        return jsonify({"error": "Webhook not configured"}), 503
    expected = _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(sig, expected):
        return jsonify({"error": "Invalid signature"}), 400
    body  = request.get_json(force=True, silent=True) or {}
    event = body.get("event", {})
    if event.get("type") == "charge:confirmed":
        d           = event.get("data", {})
        username    = (d.get("metadata") or {}).get("client_username")
        amount_paid = float((d.get("pricing", {}).get("local", {}).get("amount") or 0))
        _apply_payment(username, amount_paid, "coinbase", d.get("code", ""))
    return jsonify({"received": True})


# ── Documents ─────────────────────────────────────────────────────────────────

@portal_client_bp.route("/portal/client/documents")
@require_client
def client_list_documents():
    username = session["username"]
    result   = {}
    for cat in DOCS_CATEGORIES:
        cat_dir = CLIENT_FILES_DIR / username / "documents" / cat
        files   = []
        if cat_dir.exists():
            for f in sorted(cat_dir.iterdir()):
                if f.is_file():
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    files.append({
                        "name":     f.name,
                        "size":     st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                        "category": cat,
                    })
        result[cat] = files
    return jsonify({"categories": DOCS_CATEGORIES, "files": result})


@portal_client_bp.route("/portal/client/document/<category>/<filename>")
@require_client
def client_serve_document(category, filename):
    if category not in DOCS_CATEGORIES:
        return "Invalid category.", 400
    username  = session["username"]
    safe_name = secure_filename(filename)
    if not safe_name:
        return "File not found.", 404
    path = CLIENT_FILES_DIR / username / "documents" / category / safe_name
    if not path.exists():
        return "File not found.", 404
    return send_file(str(path), as_attachment=True, download_name=safe_name)
