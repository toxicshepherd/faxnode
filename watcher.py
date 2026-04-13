"""FaxNode – File Watcher fuer NAS-Verzeichnis."""
import os
import re
import threading
import time
import logging
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import config
import db

logger = logging.getLogger(__name__)

_broadcast = None
_ocr_queue = None
_known_files: set[str] = set()
_known_files_lock = threading.Lock()


def _wait_for_stable_file(file_path, interval=1, max_wait=30):
    """Warten bis die Dateigrösse stabil ist (Schreibvorgang abgeschlossen)."""
    last_size = -1
    waited = 0
    while waited < max_wait:
        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            time.sleep(interval)
            waited += interval
            continue
        if current_size == last_size and current_size > 0:
            return True
        last_size = current_size
        time.sleep(interval)
        waited += interval
    return False


class FaxHandler(FileSystemEventHandler):
    """Reagiert auf neue PDF-Dateien im NAS-Verzeichnis."""

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith('.pdf'):
            if _wait_for_stable_file(event.src_path):
                process_file(event.src_path)
            else:
                logger.warning("Datei wurde nicht vollstaendig geschrieben: %s", event.src_path)

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith('.pdf'):
            if _wait_for_stable_file(event.dest_path):
                process_file(event.dest_path)
            else:
                logger.warning("Datei wurde nicht vollstaendig geschrieben: %s", event.dest_path)


def parse_filename(filename):
    """FritzBox Dateiname parsen: DD.MM.YY_HH.MM_Telefax.RUFNUMMER.pdf"""
    match = re.match(config.FAX_FILENAME_PATTERN, filename)
    if not match:
        return None
    day, month, year, hour, minute, phone = match.groups()
    try:
        received = datetime(2000 + int(year), int(month), int(day), int(hour), int(minute))
    except ValueError:
        return None
    return {
        "received_at": received.strftime("%Y-%m-%d %H:%M:%S"),
        "phone_number": phone,
    }


def process_file(file_path):
    """Eine neue Fax-PDF verarbeiten (aufgerufen von Watchdog)."""
    filename = os.path.basename(file_path)

    # Schon bekannt? Dann ueberspringen (Polling hat es bereits verarbeitet)
    with _known_files_lock:
        if filename in _known_files:
            return
        _known_files.add(filename)

    parsed = parse_filename(filename)
    if not parsed:
        logger.warning("Dateiname passt nicht zum FritzBox-Format: %s", filename)
        return

    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        pass

    # Auto-Kategorie aus Adressbuch
    entry = db.get_address_entry(parsed["phone_number"])
    category = entry["default_category"] if entry else "sonstiges"

    fax_id = db.insert_fax(
        filename=filename,
        phone_number=parsed["phone_number"],
        received_at=parsed["received_at"],
        file_path=file_path,
        file_size=file_size,
        category=category,
    )

    if fax_id is None:
        return  # Bereits in DB

    logger.info("Neues Fax: %s von %s (Kategorie: %s)", filename, parsed["phone_number"], category)

    # OCR einreihen
    if _ocr_queue is not None:
        _ocr_queue.put(fax_id)

    # Auto-Print pruefen
    _check_auto_print(fax_id, parsed["phone_number"], file_path)

    # SSE broadcast
    if _broadcast:
        sender_name = entry["name"] if entry else None
        _broadcast("new_fax", {
            "id": fax_id,
            "phone_number": parsed["phone_number"],
            "sender_name": sender_name or parsed["phone_number"],
            "received_at": parsed["received_at"],
            "filename": filename,
        })


def _check_auto_print(fax_id, phone_number, file_path):
    """Auto-Print Regeln pruefen und ggf. drucken."""
    rules = db.get_print_rules_for_number(phone_number)
    for rule in rules:
        try:
            from printer import print_fax
            # address_book hat "print_copies", print_rules hat "copies"
            copies = rule.get("print_copies") or rule.get("copies") or 1
            printer_name = rule["printer_name"]
            print_fax(file_path, printer_name, copies)
            logger.info("Auto-Print: Fax %d an %s (%d Kopien)",
                        fax_id, printer_name, copies)
        except Exception as e:
            logger.error("Auto-Print fehlgeschlagen: %s", e)


def sync_directory(initial=False):
    """Verzeichnis scannen und neue Dateien verarbeiten.

    Beim initialen Lauf werden alle Dateien in die DB nachindiziert.
    Beim schnellen Polling werden nur neue Dateien (nicht in _known_files) verarbeitet.
    """
    watch_dir = config.FAX_WATCH_DIR
    if not os.path.isdir(watch_dir):
        logger.warning("FAX_WATCH_DIR existiert nicht: %s", watch_dir)
        return

    try:
        current_files = {f for f in os.listdir(watch_dir) if f.lower().endswith('.pdf')}
    except OSError as e:
        logger.error("Verzeichnis konnte nicht gelesen werden: %s", e)
        return

    with _known_files_lock:
        new_files = current_files - _known_files

    if not new_files and not initial:
        return

    count = 0
    for filename in (current_files if initial else new_files):
        file_path = os.path.join(watch_dir, filename)
        parsed = parse_filename(filename)
        if not parsed:
            continue

        # Bei neuem Fax: warten bis Datei fertig geschrieben ist
        if not initial and filename in new_files:
            if not _wait_for_stable_file(file_path, interval=0.5, max_wait=15):
                logger.warning("Datei nicht vollstaendig: %s — wird beim naechsten Poll erneut versucht", filename)
                continue

        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            continue

        entry = db.get_address_entry(parsed["phone_number"])
        category = entry["default_category"] if entry else "sonstiges"
        fax_id = db.insert_fax(
            filename=filename,
            phone_number=parsed["phone_number"],
            received_at=parsed["received_at"],
            file_path=file_path,
            file_size=file_size,
            category=category,
        )

        # In known-Set aufnehmen
        with _known_files_lock:
            _known_files.add(filename)

        if fax_id is None:
            continue  # Bereits in DB

        count += 1
        if _ocr_queue is not None:
            _ocr_queue.put(fax_id)

        # Nur bei neuen Faxen (nicht beim initialen Sync): Benachrichtigung + Auto-Print
        if not initial:
            logger.info("Neues Fax: %s von %s (Kategorie: %s)", filename, parsed["phone_number"], category)
            _check_auto_print(fax_id, parsed["phone_number"], file_path)
            if _broadcast:
                sender_name = entry["name"] if entry else None
                _broadcast("new_fax", {
                    "id": fax_id,
                    "phone_number": parsed["phone_number"],
                    "sender_name": sender_name or parsed["phone_number"],
                    "received_at": parsed["received_at"],
                    "filename": filename,
                })

    # Auch entfernte Dateien aus dem known-Set streichen
    with _known_files_lock:
        _known_files.intersection_update(current_files)

    if count > 0:
        logger.info("Sync: %d neue Faxe %s", count, "nachindiziert" if initial else "erkannt")


# Schnelles Polling: Standard 2 Sekunden
FAST_POLL_INTERVAL = int(os.environ.get("FAST_POLL_INTERVAL", "2"))


def _polling_loop():
    """Schnelles Polling fuer NAS-Mounts (inotify geht nicht auf CIFS/NFS)."""
    while True:
        try:
            sync_directory()
        except Exception as e:
            logger.error("Polling-Fehler: %s", e)
        time.sleep(FAST_POLL_INTERVAL)


def start_watcher(broadcast_fn):
    """File Watcher starten."""
    global _broadcast
    _broadcast = broadcast_fn

    # OCR-Queue holen
    global _ocr_queue
    try:
        from ocr import ocr_queue
        _ocr_queue = ocr_queue
    except ImportError:
        logger.warning("OCR-Modul konnte nicht importiert werden — OCR deaktiviert")

    # Initialer Sync: alle bestehenden Dateien erfassen und in _known_files aufnehmen
    sync_directory(initial=True)

    watch_dir = config.FAX_WATCH_DIR

    # Watchdog Observer (funktioniert ggf. nicht auf NFS/CIFS, aber schadet nicht)
    if os.path.isdir(watch_dir):
        try:
            observer = Observer()
            observer.schedule(FaxHandler(), watch_dir, recursive=False)
            observer.daemon = True
            observer.start()
            logger.info("Watchdog Observer gestartet: %s", watch_dir)
        except Exception as e:
            logger.warning("Watchdog konnte nicht gestartet werden: %s", e)

    # Schnelles Polling (alle 2s) — Haupt-Erkennungsmechanismus fuer CIFS/NFS
    poll_thread = threading.Thread(target=_polling_loop, daemon=True, name="fax-poller")
    poll_thread.start()
    logger.info("Schnelles Polling gestartet (alle %ds)", FAST_POLL_INTERVAL)
