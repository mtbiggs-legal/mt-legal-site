"""blueprints/firm_admin.py — Firm Admin tab: compliance deadlines, reminders, records."""

from flask import Blueprint, jsonify, request, session

from shared import require_attorney
from services import firm_admin

firm_admin_bp = Blueprint("firm_admin", __name__)


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _ok():
    return jsonify({"success": True, **firm_admin.overview()})


@firm_admin_bp.route("/portal/attorney/firm-admin")
@require_attorney
def firm_admin_get():
    try:
        return jsonify(firm_admin.overview())
    except firm_admin.AdminError as exc:
        return jsonify({"error": str(exc)}), 500


@firm_admin_bp.route("/portal/attorney/firm-admin/complete", methods=["POST"])
@require_attorney
def firm_admin_complete():
    d = _body()
    try:
        firm_admin.complete(str(d.get("id") or ""), str(d.get("due") or ""), session["username"],
                            d.get("amount"), d.get("confirmation"), d.get("note"),
                            str(d.get("completed_on") or ""))
    except firm_admin.AdminError as exc:
        return jsonify({"error": str(exc)}), 400
    return _ok()


@firm_admin_bp.route("/portal/attorney/firm-admin/record/delete", methods=["POST"])
@require_attorney
def firm_admin_delete_record():
    try:
        firm_admin.delete_record(str(_body().get("record_id") or ""))
    except firm_admin.AdminError as exc:
        return jsonify({"error": str(exc)}), 400
    return _ok()


@firm_admin_bp.route("/portal/attorney/firm-admin/item", methods=["POST"])
@require_attorney
def firm_admin_save_item():
    try:
        firm_admin.save_obligation(_body())
    except firm_admin.AdminError as exc:
        return jsonify({"error": str(exc)}), 400
    return _ok()


@firm_admin_bp.route("/portal/attorney/firm-admin/item/delete", methods=["POST"])
@require_attorney
def firm_admin_delete_item():
    try:
        firm_admin.delete_obligation(str(_body().get("id") or ""))
    except firm_admin.AdminError as exc:
        return jsonify({"error": str(exc)}), 400
    return _ok()
