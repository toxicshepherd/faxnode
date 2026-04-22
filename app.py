"""FaxNode – Flask App."""
import ipaddress
import json
import logging
import os
from datetime import datetime
import queue
import re
import socket
import subprocess
import threading
from pathlib import Path
from flask import (
    Flask, Response, render_template, request, jsonify,
    redirect, url_for, send_file, abort
)
import db
import config

logger = logging.getLogger(__name__)


def safe_int(value, default=1, minimum=1, maximum=None):
    """Sicher einen Wert in int konvertieren."""
    try:
        v = int(value)
        v = max(minimum, v)
        if maximum is not None:
            v = min(maximum, v)
        return v
    except (ValueError, TypeError):
        return default

from compat import get_printer_service, get_nas_service, get_network_service


def _is_valid_ip(ip: str) -> bool:
    """IP-Adresse strikt validieren (nur IPv4, keine reservierten Adressen)."""
    try:
        addr = ipaddress.IPv4Address(ip)
        return not addr.is_loopback and not addr.is_unspecified
    except (ipaddress.AddressValueError, ValueError):
        return False

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

_static_dir = Path(__file__).parent / "static"


@app.context_processor
def inject_static_version():
    def static_v(filename):
        try:
            mtime = int((_static_dir / filename).stat().st_mtime)
        except OSError:
            mtime = 0
        return url_for("static", filename=filename) + f"?v={mtime}"
    return {"static_v": static_v}


@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/"):
        # Thumbnails und PDFs sind per fax_id unveraenderlich → aggressiv cachen.
        if "/thumbnail" in request.path or "/pdf" in request.path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/favicon.ico")
def favicon():
    return send_file(_static_dir / "favicon.ico", mimetype="image/x-icon")


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Nicht gefunden"}), 404


@app.errorhandler(500)
def server_error(e):
    logger.error("Interner Fehler: %s", e)
    return jsonify({"error": "Interner Serverfehler"}), 500


def is_setup_done():
    """Pruefen ob die Ersteinrichtung abgeschlossen ist.

    Prueft ob FAX_WATCH_DIR explizit in .env gesetzt wurde (nicht nur Default).
    Vermeidet os.path.isdir() auf potentiell stale CIFS-Mounts, da diese den
    gesamten Prozess minutenlang blockieren koennen.
    """
    if not config.FAX_WATCH_DIR:
        return False
    env_path = os.path.join(config.BASE_DIR, ".env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("FAX_WATCH_DIR="):
                    return True
    except FileNotFoundError:
        pass
    return False

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
        import time as _time
        q = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_listeners.append(q)
        # Maximale Verbindungsdauer (5 Min). Der Client (EventSource)
        # verbindet sich danach automatisch neu.  Verhindert Zombie-
        # Verbindungen, die Gunicorn-Threads blockieren.
        max_age = 300  # Sekunden
        start = _time.monotonic()
        try:
            yield "event: connected\ndata: {}\n\n"
            while _time.monotonic() - start < max_age:
                try:
                    payload = q.get(timeout=5)
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


# --- CA-Zertifikat ---

@app.route("/api/ca-cert")
def api_ca_cert():
    """Oeffentliches CA-Zertifikat zum Download bereitstellen."""
    ca_path = config.CA_CERT
    if not os.path.isfile(ca_path):
        abort(404)
    return send_file(
        ca_path,
        mimetype="application/x-pem-file",
        as_attachment=True,
        download_name="faxnode-ca.crt",
    )


# --- Setup Wizard ---

@app.route("/setup")
def setup():
    if is_setup_done():
        return redirect(url_for("fax_list"))
    return render_template("setup.html")


@app.route("/api/setup/scan-network", methods=["POST"])
def api_setup_scan_network():
    """Gateway und gaengige NAS-IPs nach SMB scannen."""
    try:
        nas = get_nas_service()
        found = nas.scan_network_for_smb()
        return jsonify({"ok": True, "hosts": found})
    except Exception as e:
        logger.warning("Netzwerk-Scan fehlgeschlagen: %s", e)
        return jsonify({"ok": True, "hosts": [], "error": "Netzwerk-Scan fehlgeschlagen"})


@app.route("/api/setup/list-shares", methods=["POST"])
def api_setup_list_shares():
    """SMB-Freigaben eines Hosts auflisten."""
    data = request.get_json()
    ip = data.get("ip", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not ip or not username:
        return jsonify({"ok": False, "error": "IP und Benutzername erforderlich"})
    if not _is_valid_ip(ip):
        return jsonify({"ok": False, "error": "Ungueltige IP-Adresse"})
    try:
        nas = get_nas_service()
        shares = nas.list_shares(ip, username, password)
        if not shares:
            return jsonify({"ok": False, "error": "Keine Freigaben gefunden oder Zugangsdaten falsch"})
        return jsonify({"ok": True, "shares": shares})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Zeitueberschreitung — Host nicht erreichbar"})
    except Exception as e:
        logger.warning("Freigaben-Abfrage fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Freigaben konnten nicht abgefragt werden"})


@app.route("/api/setup/browse-share", methods=["POST"])
def api_setup_browse_share():
    """Verzeichnisse in einer SMB-Freigabe auflisten."""
    data = request.get_json()
    ip = data.get("ip", "").strip()
    share = data.get("share", "").strip()
    path = data.get("path", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not _is_valid_ip(ip):
        return jsonify({"ok": False, "error": "Ungueltige IP-Adresse"})
    if not share or not re.match(r"^[\w.\- ]+$", share):
        return jsonify({"ok": False, "error": "Ungueltiger Freigabename"})
    if path and not re.match(r"^[\w./ \\-]+$", path):
        return jsonify({"ok": False, "error": "Ungueltiger Pfad"})
    try:
        nas = get_nas_service()
        result = nas.browse_share(ip, share, path, username, password)
        return jsonify({"ok": True, **result})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Zeitueberschreitung"})
    except Exception as e:
        logger.warning("Freigabe-Browse fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Freigabe konnte nicht durchsucht werden"})


@app.route("/api/setup/mount-nas", methods=["POST"])
def api_setup_mount_nas():
    """NAS-Verbindung einrichten (mount auf Linux, UNC auf Windows)."""
    data = request.get_json()
    ip = data.get("ip", "").strip()
    share = data.get("share", "").strip()
    path = data.get("path", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not _is_valid_ip(ip):
        return jsonify({"ok": False, "error": "Ungueltige IP-Adresse"})
    if not share or not re.match(r"^[\w.\- ]+$", share):
        return jsonify({"ok": False, "error": "Ungueltiger Freigabename"})
    try:
        nas = get_nas_service()
        result = nas.connect_nas(ip, share, path, username, password)
        if not result.get("ok"):
            return jsonify(result)
        return jsonify(result)
    except Exception as e:
        logger.warning("NAS-Verbindung fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "NAS-Verbindung fehlgeschlagen"})


@app.route("/api/setup/discover-printers", methods=["POST"])
def api_setup_discover_printers():
    """Netzwerkdrucker suchen."""
    try:
        printers = get_printer_service().discover_printers()
        return jsonify({"ok": True, "printers": printers})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "printers": [], "error": "Suche dauert zu lange — evtl. keine Netzwerkdrucker erreichbar"})
    except Exception as e:
        logger.warning("Drucker-Erkennung fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "printers": [], "error": "Drucker-Erkennung fehlgeschlagen"})


@app.route("/api/setup/add-printer", methods=["POST"])
def api_setup_add_printer():
    """Drucker einrichten."""
    data = request.get_json()
    name = data.get("name", "").strip()
    uri = data.get("uri", "").strip()
    if not name or not uri:
        return jsonify({"ok": False, "error": "Name und URI erforderlich"})
    try:
        ok, result = get_printer_service().add_printer(name, uri)
        if not ok:
            return jsonify({"ok": False, "error": result})
        return jsonify({"ok": True, "name": result})
    except Exception as e:
        logger.warning("Drucker-Einrichtung fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Drucker konnte nicht eingerichtet werden"})


@app.route("/api/setup/test-printers")
def api_setup_test_printers():
    """Bereits in CUPS eingerichtete Drucker auflisten."""
    try:
        from printer import get_printers
        printers = get_printers()
        return jsonify({"ok": True, "printers": list(printers.keys())})
    except Exception as e:
        logger.warning("Drucker-Liste fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "printers": [], "error": "Drucker konnten nicht abgefragt werden"})


@app.route("/api/setup/save", methods=["POST"])
def api_setup_save():
    data = request.get_json()
    fax_dir = data.get("fax_dir", "").strip()
    if not fax_dir or not os.path.isdir(fax_dir):
        return jsonify({"ok": False, "error": "Ungueltiges Fax-Verzeichnis"})
    # Newlines in fax_dir blockieren (.env-Injection)
    if "\n" in fax_dir or "\r" in fax_dir:
        return jsonify({"ok": False, "error": "Ungueltiges Fax-Verzeichnis"})

    # .env mit Merge-Logik schreiben (bestehende Keys bewahren)
    env_path = Path(config.BASE_DIR) / ".env"
    with _env_lock:
        existing = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key = line.split("=", 1)[0]
                    existing[key] = line
        existing["FAX_WATCH_DIR"] = f"FAX_WATCH_DIR={fax_dir}"
        existing["SECRET_KEY"] = f"SECRET_KEY={config.SECRET_KEY}"
        env_path.write_text("\n".join(existing.values()) + "\n")

    # Config im Speicher aktualisieren
    config.FAX_WATCH_DIR = fax_dir

    # DB initialisieren und Hintergrund-Services starten (nur im primaeren Worker)
    db.init_db()
    if _is_primary:
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
    page = safe_int(request.args.get("page", 1), default=1)
    per_page = 30
    offset = (page - 1) * per_page
    faxes = db.get_faxes(status=status_filter, category=category_filter, archived=0, search=search, limit=per_page, offset=offset)
    counts, cat_counts = db.get_fax_counts(archived=0)
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
        default_printer=config.DEFAULT_PRINTER,
    )


@app.route("/archiv")
def archive():
    search = request.args.get("q")
    page = safe_int(request.args.get("page", 1), default=1)
    per_page = 30
    offset = (page - 1) * per_page
    faxes = db.get_faxes(archived=1, search=search, limit=per_page, offset=offset)
    archive_total = db.get_archive_count(search=search)
    total_pages = max(1, (archive_total + per_page - 1) // per_page)
    return render_template("archive.html", faxes=faxes, search=search or "", page=page, total_pages=total_pages)


@app.route("/adressbuch")
def address_book():
    entries = db.get_address_book()
    printers = {}
    try:
        from printer import get_printers
        printers = get_printers()
    except Exception as e:
        logger.debug("Drucker konnten nicht geladen werden: %s", e)
    return render_template("address_book.html", entries=entries, printers=printers, categories=config.FAX_CATEGORIES, default_printer=config.DEFAULT_PRINTER)


@app.route("/einstellungen")
def settings():
    printers = {}
    try:
        from printer import get_printers
        printers = get_printers()
    except Exception as e:
        logger.debug("Drucker konnten nicht geladen werden: %s", e)
    return render_template(
        "settings.html",
        printers=printers,
        categories=config.FAX_CATEGORIES,
        archive_days=config.ARCHIVE_AFTER_DAYS,
        force_archive_days=config.FORCE_ARCHIVE_AFTER_DAYS,
        delete_days=config.DELETE_AFTER_DAYS,
        fax_watch_dir=config.FAX_WATCH_DIR,
        database_path=config.DATABASE,
        default_printer=config.DEFAULT_PRINTER,
    )


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
    if not fax or not os.path.isfile(fax["file_path"]):
        abort(404)
    return send_file(fax["file_path"], mimetype="application/pdf")


@app.route("/api/fax/<int:fax_id>/drucken", methods=["POST"])
def api_print_fax(fax_id):
    data = request.get_json()
    printer_name = data.get("printer", "").strip() if data.get("printer") else None
    if not printer_name:
        return jsonify({"error": "Drucker ist erforderlich"}), 400
    copies = safe_int(data.get("copies", 1), default=1, maximum=50)
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    try:
        from printer import print_fax
        print_fax(fax["file_path"], printer_name, copies)
        db.record_print_event(fax_id, printer_name)
        broadcast("fax_printed", {
            "fax_id": fax_id,
            "printer": printer_name,
            "printed_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        })
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Druckfehler fuer Fax %d: %s", fax_id, e)
        return jsonify({"error": "Druckauftrag fehlgeschlagen"}), 500


@app.route("/api/drucker")
def api_list_printers():
    try:
        from printer import get_printers
        printers = get_printers()
        return jsonify(printers)
    except Exception as e:
        logger.warning("Drucker-Abfrage fehlgeschlagen: %s", e)
        return jsonify({"error": "Drucker konnten nicht abgefragt werden"}), 500


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
    page = safe_int(request.args.get("page", 1), default=1)
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
    auto_print = 1 if data.get("auto_print") else 0
    printer_name = data.get("printer_name", "").strip() or None
    print_copies = safe_int(data.get("print_copies", 1), default=1, maximum=50)
    if not phone or not name:
        return jsonify({"error": "Nummer und Name sind Pflichtfelder"}), 400
    db.upsert_address(phone, name, default_category, notes, auto_print, printer_name, print_copies)
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
    copies = safe_int(data.get("copies", 1), default=1, maximum=50)
    if not phone or not printer:
        return jsonify({"error": "Nummer und Drucker sind Pflichtfelder"}), 400
    rule_id = db.upsert_print_rule(phone, printer, copies)
    return jsonify({"ok": True, "rule_id": rule_id})


@app.route("/api/druckregel/<int:rule_id>", methods=["DELETE"])
def api_delete_print_rule(rule_id):
    db.delete_print_rule(rule_id)
    return jsonify({"ok": True})


# --- Drucker-Verwaltung ---

@app.route("/api/drucker/suchen", methods=["POST"])
def api_discover_printers():
    """Netzwerkdrucker suchen."""
    try:
        printers = get_printer_service().discover_printers()
        return jsonify({"ok": True, "printers": printers})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "printers": [], "error": "Suche dauert zu lange"})
    except Exception as e:
        logger.warning("Drucker-Suche fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "printers": [], "error": "Drucker-Suche fehlgeschlagen"})


@app.route("/api/drucker/hinzufuegen", methods=["POST"])
def api_add_printer():
    """Drucker einrichten."""
    data = request.get_json()
    name = data.get("name", "").strip()
    uri = data.get("uri", "").strip()
    if not name or not uri:
        return jsonify({"ok": False, "error": "Name und URI erforderlich"})
    try:
        ok, result = get_printer_service().add_printer(name, uri)
        if not ok:
            return jsonify({"ok": False, "error": result})
        return jsonify({"ok": True, "name": result})
    except Exception as e:
        logger.warning("Drucker-Einrichtung fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Drucker konnte nicht eingerichtet werden"})


@app.route("/api/drucker/<name>", methods=["DELETE"])
def api_remove_printer(name):
    """Drucker entfernen."""
    try:
        ok, error = get_printer_service().remove_printer(name)
        if not ok:
            return jsonify({"ok": False, "error": error})
        return jsonify({"ok": True})
    except Exception as e:
        logger.warning("Drucker-Entfernung fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Drucker konnte nicht entfernt werden"})


@app.route("/api/drucker/<name>/test", methods=["POST"])
def api_test_printer(name):
    """Testseite an Drucker senden."""
    try:
        ok, error = get_printer_service().test_printer(name)
        if not ok:
            return jsonify({"ok": False, "error": error})
        return jsonify({"ok": True})
    except Exception as e:
        logger.warning("Testseite fehlgeschlagen: %s", e)
        return jsonify({"ok": False, "error": "Testseite konnte nicht gesendet werden"})


# --- Einstellungen API ---

@app.route("/api/einstellungen/kategorie", methods=["POST"])
def api_add_category():
    data = request.get_json()
    key = data.get("key", "").strip().lower()
    label = data.get("label", "").strip()
    if not key or not label:
        return jsonify({"ok": False, "error": "Kurzname und Anzeigename erforderlich"})
    if key in config.FAX_CATEGORIES:
        return jsonify({"ok": False, "error": "Kategorie existiert bereits"})
    config.FAX_CATEGORIES[key] = label
    _save_custom_categories()
    return jsonify({"ok": True})


@app.route("/api/einstellungen/kategorie/<key>", methods=["DELETE"])
def api_delete_category(key):
    defaults = {"rezept", "bestellung", "lieferschein", "rueckruf", "sonstiges"}
    if key in defaults:
        return jsonify({"ok": False, "error": "Standard-Kategorien koennen nicht geloescht werden"})
    config.FAX_CATEGORIES.pop(key, None)
    _save_custom_categories()
    return jsonify({"ok": True})


@app.route("/api/einstellungen/archiv", methods=["POST"])
def api_save_archive_settings():
    data = request.get_json()
    archive_days = safe_int(data.get("archive_days", 7), default=7, minimum=1, maximum=365)
    force_archive_days = safe_int(data.get("force_archive_days", 30), default=30, minimum=1, maximum=365)
    delete_days = safe_int(data.get("delete_days", 90), default=90, minimum=30, maximum=3650)
    config.ARCHIVE_AFTER_DAYS = archive_days
    config.FORCE_ARCHIVE_AFTER_DAYS = force_archive_days
    config.DELETE_AFTER_DAYS = delete_days
    _save_env_settings()
    return jsonify({"ok": True})


@app.route("/api/einstellungen/standarddrucker")
def api_get_default_printer():
    """Aktuellen Standarddrucker abfragen."""
    return jsonify({"printer": config.DEFAULT_PRINTER})


@app.route("/api/einstellungen/standarddrucker", methods=["POST"])
def api_save_default_printer():
    """Standarddrucker festlegen."""
    data = request.get_json()
    printer_name = data.get("printer", "").strip()
    if printer_name:
        try:
            from printer import get_printers
            printers = get_printers()
            if printer_name not in printers:
                return jsonify({"ok": False, "error": "Drucker nicht gefunden"})
        except Exception:
            pass
    config.DEFAULT_PRINTER = printer_name
    _save_env_settings()
    return jsonify({"ok": True})


@app.route("/api/fax/<int:fax_id>/archivieren", methods=["POST"])
def api_archive_fax(fax_id):
    """Fax manuell archivieren."""
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    db.archive_fax(fax_id)
    broadcast("fax_archived", {
        "fax_id": fax_id,
        "sender_name": fax["sender_name"] or fax["phone_number"],
    })
    return jsonify({"ok": True})


@app.route("/api/fax/<int:fax_id>/wiederherstellen", methods=["POST"])
def api_unarchive_fax(fax_id):
    """Fax aus dem Archiv wiederherstellen."""
    fax = db.get_fax(fax_id)
    if not fax:
        abort(404)
    db.unarchive_fax(fax_id)
    broadcast("fax_unarchived", {
        "fax_id": fax_id,
        "sender_name": fax["sender_name"] or fax["phone_number"],
    })
    return jsonify({"ok": True})


def _save_custom_categories():
    """Benutzerdefinierte Kategorien in Datei speichern."""
    defaults = {"rezept", "bestellung", "lieferschein", "rueckruf", "sonstiges"}
    custom = {k: v for k, v in config.FAX_CATEGORIES.items() if k not in defaults}
    cat_file = Path(config.BASE_DIR) / "data" / "categories.json"
    cat_file.parent.mkdir(parents=True, exist_ok=True)
    cat_file.write_text(json.dumps(custom, ensure_ascii=False))


def _load_custom_categories():
    """Benutzerdefinierte Kategorien laden."""
    cat_file = Path(config.BASE_DIR) / "data" / "categories.json"
    if cat_file.exists():
        custom = json.loads(cat_file.read_text())
        config.FAX_CATEGORIES.update(custom)


_env_lock = threading.Lock()


def _save_env_settings():
    """Archiv-Einstellungen in .env speichern."""
    env_path = Path(config.BASE_DIR) / ".env"
    with _env_lock:
        lines = []
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if not line.startswith(("ARCHIVE_AFTER_DAYS=", "FORCE_ARCHIVE_AFTER_DAYS=", "DELETE_AFTER_DAYS=", "DEFAULT_PRINTER=")):
                    lines.append(line)
        lines.append(f"ARCHIVE_AFTER_DAYS={config.ARCHIVE_AFTER_DAYS}")
        lines.append(f"FORCE_ARCHIVE_AFTER_DAYS={config.FORCE_ARCHIVE_AFTER_DAYS}")
        lines.append(f"DELETE_AFTER_DAYS={config.DELETE_AFTER_DAYS}")
        lines.append(f"DEFAULT_PRINTER={config.DEFAULT_PRINTER}")
        env_path.write_text("\n".join(lines) + "\n")


# --- UDP Discovery ---

DISCOVERY_PORT = 9742  # Fester Discovery-Port, unabhaengig vom Web-Port


def _discovery_responder():
    """UDP-Discovery: Antwortet auf Broadcast-Anfragen von Clients."""
    import logging
    logger = logging.getLogger(__name__)
    discovery_port = DISCOVERY_PORT
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", discovery_port))
        logger.info("UDP-Discovery lauscht auf Port %d", discovery_port)
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == b"FAXNODE_DISCOVER":
                    response = json.dumps({
                        "service": "faxnode",
                        "port": config.PORT,
                        "hostname": socket.gethostname(),
                        "version": "1.1",
                    }, ensure_ascii=False).encode()
                    sock.sendto(response, addr)
            except Exception as e:
                logger.warning("UDP-Discovery Paket-Fehler: %s", e)
    except Exception as e:
        logger.error("UDP-Discovery konnte nicht gestartet werden: %s", e)


# --- Startup ---

_background_started = False
_background_lock = threading.Lock()


def start_background_services():
    """Hintergrund-Services starten (Watcher, OCR, Scheduler, Discovery)."""
    global _background_started
    with _background_lock:
        if _background_started:
            return
        _background_started = True

    from watcher import start_watcher
    from ocr import start_ocr_worker
    from scheduler import start_scheduler

    start_watcher(broadcast)
    start_ocr_worker(broadcast)
    start_scheduler()


# Background-Services nur einmal starten (nicht in jedem Gunicorn-Worker).
# Auf Linux (Gunicorn, multi-process): fcntl-Lock stellt sicher, dass nur
# ein Worker die Services startet.  Auf Windows (Waitress, single-process):
# immer primary — kein Lock noetig.
_bg_lock_fd = None  # Module-level: haelt den Lock solange der Prozess lebt

def _try_acquire_bg_lock():
    """Versuche exklusiven Lock zu bekommen. Auf Windows immer True."""
    global _bg_lock_fd
    try:
        import fcntl
        lock_path = os.path.join(os.path.dirname(config.DATABASE), ".bg_services.lock")
        _bg_lock_fd = open(lock_path, "w")
        fcntl.flock(_bg_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except ImportError:
        # Windows: kein fcntl, kein Gunicorn-Fork → immer primary
        return True
    except (OSError, IOError):
        return False

_is_primary = _try_acquire_bg_lock()

with app.app_context():
    db.init_db()
    _load_custom_categories()
    if _is_primary:
        _discovery_thread = threading.Thread(
            target=_discovery_responder, daemon=True, name="udp-discovery")
        _discovery_thread.start()
        if is_setup_done():
            start_background_services()


if __name__ == "__main__":
    ssl_ctx = None
    cert_dir = Path(config.CERT_DIR)
    if (cert_dir / "server.crt").exists() and (cert_dir / "server.key").exists():
        ssl_ctx = (str(cert_dir / "server.crt"), str(cert_dir / "server.key"))
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True, ssl_context=ssl_ctx)
