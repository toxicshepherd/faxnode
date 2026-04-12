"""FaxNode – Flask App."""
import json
import os
import queue
import threading
from pathlib import Path
from flask import (
    Flask, Response, render_template, request, jsonify,
    redirect, url_for, send_file, abort
)
import db
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


def is_setup_done():
    """Pruefen ob die Ersteinrichtung abgeschlossen ist."""
    env_file = Path(config.BASE_DIR) / ".env"
    return env_file.exists() and os.path.getsize(env_file) > 0

# --- SSE ---

_sse_listeners: list[queue.Queue] = []
_sse_lock = threading.Lock()


def broadcast(event_type: str, data: dict):
    """SSE-Event an alle verbundenen Clients senden."""
    payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    dead = []
    with _sse_lock:
        for q in _sse_listeners:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_listeners.remove(q)


@app.route("/events")
def events():
    """SSE-Stream fuer Live-Updates."""
    def stream():
        q = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_listeners.append(q)
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    payload = q.get(timeout=30)
                    yield payload
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_listeners:
                    _sse_listeners.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# --- Setup Wizard ---

@app.route("/setup")
def setup():
    if is_setup_done():
        return redirect(url_for("fax_list"))
    return render_template("setup.html")


@app.route("/api/setup/test-dir", methods=["POST"])
def api_setup_test_dir():
    data = request.get_json()
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"ok": False, "error": "Pfad darf nicht leer sein"})
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": "Verzeichnis existiert nicht"})
    try:
        files = [f for f in os.listdir(path) if f.lower().endswith(".pdf")]
        return jsonify({"ok": True, "pdf_count": len(files)})
    except PermissionError:
        return jsonify({"ok": False, "error": "Keine Leseberechtigung"})


@app.route("/api/setup/test-printers")
def api_setup_test_printers():
    try:
        from printer import get_printers
        printers = get_printers()
        return jsonify({"ok": True, "printers": list(printers.keys())})
    except Exception as e:
        return jsonify({"ok": False, "printers": [], "error": str(e)})


@app.route("/api/setup/save", methods=["POST"])
def api_setup_save():
    data = request.get_json()
    fax_dir = data.get("fax_dir", "").strip()
    if not fax_dir or not os.path.isdir(fax_dir):
        return jsonify({"ok": False, "error": "Ungueltiges Fax-Verzeichnis"})

    # .env schreiben
    env_path = Path(config.BASE_DIR) / ".env"
    lines = [
        f"FAX_WATCH_DIR={fax_dir}",
        f"SECRET_KEY={config.SECRET_KEY}",
    ]
    env_path.write_text("\n".join(lines) + "\n")

    # Config im Speicher aktualisieren
    config.FAX_WATCH_DIR = fax_dir

    # DB initialisieren und Hintergrund-Services starten
    db.init_db()
    start_background_services()

    return jsonify({"ok": True})


# --- Seiten ---

@app.route("/")
def index():
    if not is_setup_done():
        return redirect(url_for("setup"))
    return redirect(url_for("fax_list"))


@app.route("/faxe")
def fax_list():
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    search = request.args.get("q")
    page = max(1, int(request.args.get("page", 1)))
    per_page = 30
    offset = (page - 1) * per_page
    faxes = db.get_faxes(status=status_filter, category=category_filter, archived=0, search=search, limit=per_page, offset=offset)
    counts = db.get_fax_count_by_status(archived=0)
    cat_counts = db.get_fax_count_by_category(archived=0)
    total = sum(counts.values())
    unread = counts.get("neu", 0)
    # Gesamtzahl fuer Pagination berechnen
    if status_filter:
        filtered_total = counts.get(status_filter, 0)
    elif category_filter:
        filtered_total = cat_counts.get(category_filter, 0)
    else:
        filtered_total = total
    total_pages = max(1, (filtered_total + per_page - 1) // per_page)
    return render_template(
        "index.html",
        faxes=faxes,
        counts=counts,
        cat_counts=cat_counts,
        total=total,
        unread=unread,
        current_status=status_filter,
        current_category=category_filter,
        search=search or "",
        statuses=config.FAX_STATUSES,
        categories=config.FAX_CATEGORIES,
        page=page,
        total_pages=total_pages,
    )


@app.route("/faxe/<int:fax_id>")
def fax_detail(fax_id):
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    notes = db.get_notes(fax_id)
    return render_template(
        "fax_detail.html",
        fax=fax,
        notes=notes,
        statuses=config.FAX_STATUSES,
        categories=config.FAX_CATEGORIES,
    )


@app.route("/archiv")
def archive():
    search = request.args.get("q")
    page = max(1, int(request.args.get("page", 1)))
    per_page = 30
    offset = (page - 1) * per_page
    faxes = db.get_faxes(archived=1, search=search, limit=per_page, offset=offset)
    archive_total = db.get_archive_count(search=search)
    total_pages = max(1, (archive_total + per_page - 1) // per_page)
    return render_template("archive.html", faxes=faxes, search=search or "", page=page, total_pages=total_pages)


@app.route("/adressbuch")
def address_book():
    entries = db.get_address_book()
    return render_template("address_book.html", entries=entries)


@app.route("/einstellungen")
def settings():
    rules = db.get_print_rules()
    printers = {}
    try:
        from printer import get_printers
        printers = get_printers()
    except Exception:
        pass
    return render_template("settings.html", rules=rules, printers=printers)


# --- API ---

@app.route("/api/fax/<int:fax_id>/status", methods=["POST"])
def api_update_status(fax_id):
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in config.FAX_STATUSES:
        return jsonify({"error": "Ungueltiger Status"}), 400
    db.update_fax_status(fax_id, new_status)
    fax = db.get_fax(fax_id)
    broadcast("status_changed", {
        "fax_id": fax_id,
        "status": new_status,
        "status_label": config.FAX_STATUSES[new_status],
        "sender_name": fax["sender_name"] or fax["phone_number"],
    })
    return jsonify({"ok": True, "status": new_status})


@app.route("/api/fax/<int:fax_id>/notiz", methods=["POST"])
def api_add_note(fax_id):
    data = request.get_json()
    author = data.get("author", "Mitarbeiter").strip() or "Mitarbeiter"
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Nachricht darf nicht leer sein"}), 400
    note_id = db.add_note(fax_id, author, message)
    broadcast("note_added", {
        "fax_id": fax_id,
        "note_id": note_id,
        "author": author,
        "message": message,
    })
    return jsonify({"ok": True, "note_id": note_id})


@app.route("/api/fax/<int:fax_id>/pdf")
def api_serve_pdf(fax_id):
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    return send_file(fax["file_path"], mimetype="application/pdf")


@app.route("/api/fax/<int:fax_id>/drucken", methods=["POST"])
def api_print_fax(fax_id):
    data = request.get_json()
    printer_name = data.get("printer")
    copies = int(data.get("copies", 1))
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    try:
        from printer import print_fax
        print_fax(fax["file_path"], printer_name, copies)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/drucker")
def api_list_printers():
    try:
        from printer import get_printers
        printers = get_printers()
        return jsonify(printers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/fax/<int:fax_id>/kategorie", methods=["POST"])
def api_update_category(fax_id):
    data = request.get_json()
    category = data.get("category")
    if category not in config.FAX_CATEGORIES:
        return jsonify({"error": "Ungueltige Kategorie"}), 400
    db.update_fax_category(fax_id, category)
    fax = db.get_fax(fax_id)
    broadcast("category_changed", {
        "fax_id": fax_id,
        "category": category,
        "category_label": config.FAX_CATEGORIES[category],
    })
    return jsonify({"ok": True, "category": category})


@app.route("/api/fax/<int:fax_id>/thumbnail")
def api_serve_thumbnail(fax_id):
    fax = db.get_fax(fax_id)
    if not fax or not fax["thumbnail_path"]:
        abort(404)
    return send_file(fax["thumbnail_path"], mimetype="image/png")


@app.route("/api/faxe")
def api_fax_list():
    """JSON-API fuer Infinite Scroll."""
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    search = request.args.get("q")
    page = max(1, int(request.args.get("page", 1)))
    per_page = 30
    offset = (page - 1) * per_page
    faxes = db.get_faxes(status=status_filter, category=category_filter, archived=0, search=search, limit=per_page, offset=offset)
    return jsonify([dict(f) for f in faxes])


@app.route("/api/unread")
def api_unread_count():
    return jsonify({"count": db.get_unread_count()})


@app.route("/statistik")
def statistics():
    overview = db.get_stats_overview()
    per_week = db.get_stats_faxes_per_week()
    top_senders = db.get_stats_top_senders()
    cat_stats = db.get_stats_categories()
    return render_template(
        "statistics.html",
        overview=overview,
        per_week=per_week,
        top_senders=top_senders,
        cat_stats=cat_stats,
        categories=config.FAX_CATEGORIES,
    )


@app.route("/api/adressbuch", methods=["POST"])
def api_upsert_address():
    data = request.get_json()
    phone = data.get("phone_number", "").strip()
    name = data.get("name", "").strip()
    default_category = data.get("default_category", "sonstiges")
    notes = data.get("notes", "").strip()
    if not phone or not name:
        return jsonify({"error": "Nummer und Name sind Pflichtfelder"}), 400
    db.upsert_address(phone, name, default_category, notes)
    return jsonify({"ok": True})


@app.route("/api/adressbuch/<int:address_id>", methods=["DELETE"])
def api_delete_address(address_id):
    db.delete_address(address_id)
    return jsonify({"ok": True})


@app.route("/api/druckregel", methods=["POST"])
def api_upsert_print_rule():
    data = request.get_json()
    phone = data.get("phone_number", "").strip()
    printer = data.get("printer_name", "").strip()
    copies = int(data.get("copies", 1))
    if not phone or not printer:
        return jsonify({"error": "Nummer und Drucker sind Pflichtfelder"}), 400
    rule_id = db.upsert_print_rule(phone, printer, copies)
    return jsonify({"ok": True, "rule_id": rule_id})


@app.route("/api/druckregel/<int:rule_id>", methods=["DELETE"])
def api_delete_print_rule(rule_id):
    db.delete_print_rule(rule_id)
    return jsonify({"ok": True})


# --- Startup ---

_background_started = False


def start_background_services():
    """Hintergrund-Services starten (Watcher, OCR, Scheduler)."""
    global _background_started
    if _background_started:
        return
    _background_started = True

    from watcher import start_watcher
    from ocr import start_ocr_worker
    from scheduler import start_scheduler

    start_watcher(broadcast)
    start_ocr_worker(broadcast)
    start_scheduler()


with app.app_context():
    db.init_db()
    if is_setup_done():
        start_background_services()


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
