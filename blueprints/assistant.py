"""blueprints/assistant.py — chat routes for the attorney portal assistant.

The browser keeps no history: the conversation id lives in the Flask session
and the conversation itself in services/assistant.py. Action tools come back
as pending cards; /confirm runs the ones the attorney approves.
"""

from flask import Blueprint, jsonify, request, session

from services import assistant
from shared import require_attorney

assistant_bp = Blueprint("assistant", __name__)

_SESSION_KEY = "assistant_conversation"


def _conversation(create=True):
    conv = assistant.get_conversation(session.get(_SESSION_KEY, ""), session["username"], create=create)
    session[_SESSION_KEY] = conv["id"]
    return conv


@assistant_bp.route("/portal/attorney/assistant/history")
@require_attorney
def assistant_history():
    try:
        conv = _conversation(create=False)
    except assistant.AssistantError:
        return jsonify({"messages": [], "pending": []})
    return jsonify(assistant.history_for_display(conv))


@assistant_bp.route("/portal/attorney/assistant/message", methods=["POST"])
@require_attorney
def assistant_message():
    data = request.get_json() or {}
    try:
        out = assistant.send_message(_conversation(), data.get("text", ""))
    except assistant.AssistantError as exc:
        return jsonify({"error": str(exc)}), 400
    except ValueError as exc:          # get_anthropic_client: no API key
        return jsonify({"error": str(exc)}), 503
    return jsonify({"success": True, **out})


@assistant_bp.route("/portal/attorney/assistant/confirm", methods=["POST"])
@require_attorney
def assistant_confirm():
    data = request.get_json() or {}
    decisions = data.get("decisions")
    if not isinstance(decisions, dict):
        return jsonify({"error": "decisions must map each action id to true or false."}), 400
    try:
        out = assistant.confirm(_conversation(create=False), decisions)
    except assistant.AssistantError as exc:
        return jsonify({"error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify({"success": True, **out})


@assistant_bp.route("/portal/attorney/assistant/reset", methods=["POST"])
@require_attorney
def assistant_reset():
    assistant.reset_conversation(session.pop(_SESSION_KEY, ""))
    return jsonify({"success": True})
