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


class FaxHandler(FileSystemEventHandler):
    """Reagiert auf neue PDF-Dateien im NAS-Verzeichnis."""

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith('.pdf'):
            # Kurz warten bis die Datei vollstaendig geschrieben wurde
            time.sleep(1)
            process_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith('.pdf'):
            time.sleep(1)
            process_file(event.dest_path)


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
    """Eine neue Fax-PDF verarbeiten."""
    filename = os.path.basename(file_path)
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


def sync_directory():
    """Verzeichnis scannen und fehlende Dateien nachindizieren."""
    watch_dir = config.FAX_WATCH_DIR
    if not os.path.isdir(watch_dir):
        logger.warning("FAX_WATCH_DIR existiert nicht: %s", watch_dir)
        return

    count = 0
    for filename in os.listdir(watch_dir):
        if filename.lower().endswith('.pdf'):
            file_path = os.path.join(watch_dir, filename)
            parsed = parse_filename(filename)
            if parsed:
                entry = db.get_address_entry(parsed["phone_number"])
                category = entry["default_category"] if entry else "sonstiges"
                fax_id = db.insert_fax(
                    filename=filename,
                    phone_number=parsed["phone_number"],
                    received_at=parsed["received_at"],
                    file_path=file_path,
                    file_size=os.path.getsize(file_path),
                    category=category,
                )
                if fax_id and _ocr_queue is not None:
                    _ocr_queue.put(fax_id)
                    count += 1

    if count > 0:
        logger.info("Sync: %d neue Faxe nachindiziert", count)


def _polling_loop():
    """Polling-Fallback fuer NAS-Mounts (inotify geht nicht auf CIFS/NFS)."""
    while True:
        try:
            sync_directory()
        except Exception as e:
            logger.error("Polling-Fehler: %s", e)
        time.sleep(config.POLL_INTERVAL)


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

    # Erst synchronisieren
    sync_directory()

    watch_dir = config.FAX_WATCH_DIR

    # Watchdog Observer (funktioniert ggf. nicht auf NFS/CIFS)
    if os.path.isdir(watch_dir):
        try:
            observer = Observer()
            observer.schedule(FaxHandler(), watch_dir, recursive=False)
            observer.daemon = True
            observer.start()
            logger.info("Watchdog Observer gestartet: %s", watch_dir)
        except Exception as e:
            logger.warning("Watchdog konnte nicht gestartet werden: %s", e)

    # Polling-Fallback immer starten
    poll_thread = threading.Thread(target=_polling_loop, daemon=True, name="fax-poller")
    poll_thread.start()
    logger.info("Polling-Fallback gestartet (alle %ds)", config.POLL_INTERVAL)
