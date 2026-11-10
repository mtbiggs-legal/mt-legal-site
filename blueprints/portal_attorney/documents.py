"""blueprints/portal_attorney/documents.py — Client documents: list, upload, delete, download, preview."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


@portal_attorney_bp.route("/portal/attorney/documents/<username>")
@require_attorney
def list_documents(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    log_access_atomic(client["username"], "view_documents")
    uname  = client["username"]
    result = {}
    for cat in DOCS_CATEGORIES:
        cat_dir = shared.CLIENT_FILES_DIR / uname / "documents" / cat
        files   = []
        if uname and cat_dir.exists():
            for f in sorted(cat_dir.iterdir()):
                if f.is_file():
                    st = f.stat()
                    files.append({
                        "name":     f.name,
                        "size":     client_files.plain_size(f),
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                        "category": cat,
                    })
        result[cat] = files
    return jsonify({"categories": DOCS_CATEGORIES, "files": result})


@portal_attorney_bp.route("/portal/attorney/upload-document", methods=["POST"])
@require_attorney
def upload_document():
    username = safe_username(request.form.get("username", ""))
    category = request.form.get("category", "Other").strip()
    if category not in DOCS_CATEGORIES:
        category = "Other"
    if not username:
        return jsonify({"error": "Username required."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        return jsonify({"error": f"File type '{ext}' not allowed."}), 400
    dest = client_files.save_upload(file, username, category)
    st   = dest.stat()

    client = load_client(client["username"])
    if client is None:
        return jsonify({"error": "Client not found."}), 404
    entry = billing.auto_entry(
        date=datetime.now().strftime("%Y-%m-%d"), hours=0.1,
        note=f"{category} — \"{dest.name}\" uploaded.",
        type="document_upload", category="Filing")
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    _log_access(client, "document_upload", f"{category}/{dest.name}")
    save_client(client)
    _log_activity(username, "document_upload", f"{category} — \"{dest.name}\" uploaded.")
    billing_entry = entry
    total_hours   = client["hours_billed"]

    return jsonify({
        "success": True,
        "file": {
            "name":     dest.name,
            "size":     client_files.plain_size(dest),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
            "category": category,
        },
        "billing_entry": billing_entry,
        "total_hours":   total_hours,
    })


@portal_attorney_bp.route("/portal/attorney/delete-document", methods=["POST"])
@require_attorney
def delete_document():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    category = data.get("category", "").strip()
    filename = data.get("filename", "").strip()
    if not all([username, category, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return jsonify({"error": "File not found."}), 404
    safe_name = path.name
    path.unlink()
    _log_access(client, "document_delete", f"{category}/{safe_name}")
    save_client(client)
    _log_activity(username, "document_delete", f"{category} — \"{safe_name}\" deleted.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/document/<username>/<category>/<filename>")
@require_attorney
def serve_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "download_document", f"{category}/{path.name}")
    return client_files.send(path, as_attachment=True)


@portal_attorney_bp.route("/portal/attorney/preview/<username>/<category>/<filename>")
@require_attorney
def preview_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    return client_files.send(path, as_attachment=False)


@portal_attorney_bp.route("/portal/attorney/docx-preview/<username>/<category>/<filename>")
@require_attorney
def docx_preview(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    if not MAMMOTH_AVAILABLE:
        return "mammoth not installed — run: python -m pip install mammoth", 503
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    try:
        import io
        import mammoth
        result = mammoth.convert_to_html(io.BytesIO(client_files.read_bytes(path)))
    except Exception:
        current_app.logger.exception("DOCX preview failed")
        return "Could not convert this document for preview. Download it instead.", 500
    # An uploaded Word file is untrusted: keep only safe markup, then serve it
    # in the same script-free sandbox as other HTML documents.
    return client_files.send_html(html_document(path.name, result.value), path.name)
