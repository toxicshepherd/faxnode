"""FaxNode – Flask App."""
import json
import queue
import threading
from flask import (
    Flask, Response, render_template, request, jsonify,
    redirect, url_for, send_file, abort
)
import db
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

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


# --- Seiten ---

@app.route("/")
def index():
    return redirect(url_for("fax_list"))


@app.route("/faxe")
def fax_list():
    status_filter = request.args.get("status")
    search = request.args.get("q")
    faxes = db.get_faxes(status=status_filter, archived=0, search=search)
    counts = db.get_fax_count_by_status(archived=0)
    total = sum(counts.values())
    return render_template(
        "index.html",
        faxes=faxes,
        counts=counts,
        total=total,
        current_status=status_filter,
        search=search or "",
        statuses=config.FAX_STATUSES,
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
    )


@app.route("/archiv")
def archive():
    search = request.args.get("q")
    faxes = db.get_faxes(archived=1, search=search)
    return render_template("archive.html", faxes=faxes, search=search or "")


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


@app.route("/api/adressbuch", methods=["POST"])
def api_upsert_address():
    data = request.get_json()
    phone = data.get("phone_number", "").strip()
    name = data.get("name", "").strip()
    notes = data.get("notes", "").strip()
    if not phone or not name:
        return jsonify({"error": "Nummer und Name sind Pflichtfelder"}), 400
    db.upsert_address(phone, name, notes)
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
    start_background_services()


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
