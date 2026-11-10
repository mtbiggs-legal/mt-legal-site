// attorney_documents.js: A client's documents: list, upload, delete, preview.
// Split out of attorney_portal.js; loaded right after it (see attorney_portal.html),
// and like it, defines global functions the templates call.

// ── Document management ───────────────────────────────────────────────────────
var _docCategory = "Intake";

function setDocCategory(cat, btn) {
  _docCategory = cat;
  document.querySelectorAll(".doc-cat-tab").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  document.getElementById("doc-drop-label").textContent = `Drop files here for "${cat}"`;
  document.getElementById("doc-list-title").textContent = cat;
  loadDocumentList();
}

function loadDocumentList() {
  if (!_currentClient) return;
  document.getElementById("doc-file-list").innerHTML =
    '<p class="doc-empty" style="color:var(--gray-3)">Loading…</p>';
  fetch("/portal/attorney/documents/" + encodeURIComponent(_currentClient.username))
    .then(r => r.json())
    .then(d => renderDocList(d.files[_docCategory] || []));
}

function renderDocList(files) {
  const wrap  = document.getElementById("doc-file-list");
  const count = document.getElementById("doc-file-count");
  count.textContent = files.length ? files.length + " file" + (files.length > 1 ? "s" : "") : "";
  if (!files.length) {
    _show(wrap, _el("p", {className: "doc-empty"}, "No files in this category yet. Drag & drop above to upload."));
    return;
  }
  const u   = encodeURIComponent(_currentClient.username);
  const cat = encodeURIComponent(_docCategory);
  _show(wrap, files.map(f => {
    const name = f.name;
    const ext  = (name.split(".").pop() || "").toLowerCase();
    const fn   = encodeURIComponent(name);
    return _el("div", {className: "doc-file-row"},
      _el("div", {className: "doc-file-icon"}, docIcon(name)),
      _el("div", {className: "doc-file-name"}, name),
      _el("div", {className: "doc-file-meta"}, f.modified + " · " + fmtBytes(f.size)),
      _el("div", {className: "doc-file-actions"},
        _el("button", {type: "button", className: "doc-btn", title: "Preview",
                       onclick: () => previewDocument(name, ext)}, "👁 Preview"),
        _el("a", {className: "doc-btn", title: "Download",
                  href: "/portal/attorney/document/" + u + "/" + cat + "/" + fn}, "↓ Download"),
        _docCategory === "Scheduling Orders"
          ? _el("button", {type: "button", className: "doc-btn", title: "Read dates",
                           onclick: () => openSchedReview(name)}, "📅 Read dates")
          : null,
        window.esignSignable && esignSignable(name) && _docCategory !== "Signed Documents"
          ? _el("button", {type: "button", className: "doc-btn", title: "Send for e-signature",
                           onclick: () => openEsign(name)}, "✍ Sign")
          : null,
        window.openFiling && (ext === "pdf" || ext === "txt") &&
          _docCategory !== "Filing Packages" && _docCategory !== "Signed Documents"
          ? _el("button", {type: "button", className: "doc-btn", title: "Prepare a filing package",
                           onclick: () => openFiling(name)}, "⚖ Prepare filing")
          : null,
        _el("button", {type: "button", className: "doc-btn doc-btn-del", title: "Delete",
                       onclick: () => deleteDocument(name)}, "🗑 Delete")));
  }));
}

// ── Document preview ──────────────────────────────────────────────────────────
function previewDocument(filename, ext) {
  if (!_currentClient) return;
  const u   = encodeURIComponent(_currentClient.username);
  const cat = encodeURIComponent(_docCategory);
  const fn  = encodeURIComponent(filename);
  const previewUrl  = `/portal/attorney/preview/${u}/${cat}/${fn}`;
  const downloadUrl = `/portal/attorney/document/${u}/${cat}/${fn}`;

  document.getElementById("doc-preview-title").textContent = filename;
  document.getElementById("doc-preview-dl").href = downloadUrl;

  const body   = document.getElementById("doc-preview-body");
  const images = ["jpg","jpeg","png","gif","bmp","webp"];
  const texts  = ["txt","rtf"];

  if (ext === "pdf" || ext === "html") {
    body.innerHTML = `<iframe src="${previewUrl}" title="${escHtml(filename)}"></iframe>`;
  } else if (ext === "docx") {
    const docxUrl = previewUrl.replace("/preview/", "/docx-preview/");
    body.innerHTML = `<iframe src="${docxUrl}" title="${escHtml(filename)}"></iframe>`;
  } else if (images.includes(ext)) {
    body.innerHTML = `<img src="${previewUrl}" alt="${escHtml(filename)}" />`;
  } else if (texts.includes(ext)) {
    body.innerHTML = `<pre style="color:var(--gray-3)">Loading…</pre>`;
    fetch(previewUrl).then(r => r.text()).then(text => {
      body.innerHTML = `<pre>${escHtml(text)}</pre>`;
    });
  } else {
    body.innerHTML = `
      <div class="doc-preview-no-support">
        <div style="font-size:3.5rem;margin-bottom:.75rem">${docIcon(filename)}</div>
        <div style="font-family:Georgia,serif;font-size:1.05rem;font-weight:bold;color:var(--navy);margin-bottom:.5rem">
          ${escHtml(filename)}
        </div>
        <div style="font-family:Arial,sans-serif;font-size:.88rem;color:var(--gray-3);margin-bottom:1.5rem">
          Browser preview is not available for .${ext} files.
        </div>
        <a href="${downloadUrl}" class="btn btn-primary">↓ Download to View</a>
      </div>`;
  }

  document.getElementById("doc-preview-overlay").style.display = "flex";
}

function closeDocPreview(e) {
  if (e && e.target !== document.getElementById("doc-preview-overlay")) return;
  document.getElementById("doc-preview-overlay").style.display = "none";
  // Clear iframe/img src to stop loading
  document.getElementById("doc-preview-body").innerHTML = "";
}

function docIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (ext === "pdf")                             return "📄";
  if (["doc","docx"].includes(ext))              return "📝";
  if (["xls","xlsx"].includes(ext))              return "📊";
  if (["ppt","pptx"].includes(ext))              return "📋";
  if (["jpg","jpeg","png","gif","bmp","webp"].includes(ext)) return "🖼";
  if (ext === "txt" || ext === "rtf")            return "📃";
  if (ext === "html")                            return "🗒";
  return "📎";
}

function fmtBytes(b) {
  if (b < 1024)      return b + " B";
  if (b < 1048576)   return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function deleteDocument(filename) {
  if (!_currentClient) return;
  if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
  fetch("/portal/attorney/delete-document", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      username: _currentClient.username,
      category: _docCategory,
      filename,
    }),
  }).then(r => r.json()).then(d => {
    if (d.success) loadDocumentList();
    else alert("Error: " + d.error);
  });
}

function initDocDropZone() {
  const zone  = document.getElementById("doc-drop-zone");
  const input = document.getElementById("doc-file-input");
  if (!zone) return;
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", ()  => zone.classList.remove("drag-over"));
  zone.addEventListener("dragend",   ()  => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    if (!_currentClient) { alert("Please select a client first."); return; }
    uploadFiles(e.dataTransfer.files);
  });
  zone.addEventListener("click", e => {
    if (e.target === input) return;
    if (!_currentClient) { alert("Please select a client first."); return; }
    input.value = "";
    input.click();
  });
}

function uploadFiles(files) {
  if (!_currentClient || !files || !files.length) return;
  const progress = document.getElementById("doc-upload-progress");
  const list = Array.from(files);
  let done = 0;
  let lastSchedFile = null;
  const total = list.length;

  function next() {
    if (!list.length) {
      progress.textContent = total === 1
        ? "Upload complete."
        : `${done} file${done > 1 ? "s" : ""} uploaded.`;
      setTimeout(() => { progress.textContent = ""; }, 3000);
      loadDocumentList();
      if (window.openSchedReview && lastSchedFile) openSchedReview(lastSchedFile);
      // Refresh billing log and case overview with auto-billed entries
      if (_currentClient) {
        populateBillingLog(_currentClient);
        populateOverview(_currentClient);
      }
      return;
    }
    const file = list.shift();
    progress.textContent = `Uploading "${file.name}" (${done + 1} of ${total})…`;
    const form = new FormData();
    form.append("username", _currentClient.username);
    form.append("category", _docCategory);
    form.append("file", file);
    fetch("/portal/attorney/upload-document", { method: "POST", body: form })
      .then(r => r.json())
      .then(d => {
        if (!d.success) { alert("Upload failed: " + (d.error || "unknown error")); }
        if (d.success && _docCategory === "Scheduling Orders" && d.file && d.file.name) lastSchedFile = d.file.name;
        // Accumulate auto-billing entries into the in-memory client
        if (d.billing_entry && _currentClient) {
          _currentClient.billing_log = _currentClient.billing_log || [];
          _currentClient.billing_log.push(d.billing_entry);
          if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
        }
        done++;
        next();
      })
      .catch(err => { progress.textContent = "Upload error: " + err.message; });
  }
  next();
}
