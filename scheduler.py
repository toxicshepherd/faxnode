"""FaxNode – Scheduler fuer Auto-Archiv und Auto-Delete."""
import os
import threading
import logging
import schedule
import time

import config
import db

logger = logging.getLogger(__name__)


def auto_archive():
    """Faxe automatisch archivieren."""
    with db.db_connection() as conn:
        # Regel 1: Erledigte Faxe nach X Tagen
        c1 = conn.execute(
            """UPDATE faxes
               SET archived = 1, archived_at = CURRENT_TIMESTAMP
               WHERE archived = 0
               AND status = 'erledigt'
               AND received_at < datetime('now', ?)""",
            (f"-{config.ARCHIVE_AFTER_DAYS} days",)
        )
        # Regel 2: Alle uebrigen Faxe nach Y Tagen, unabhaengig vom Status
        c2 = conn.execute(
            """UPDATE faxes
               SET archived = 1, archived_at = CURRENT_TIMESTAMP
               WHERE archived = 0
               AND status != 'erledigt'
               AND received_at < datetime('now', ?)""",
            (f"-{config.FORCE_ARCHIVE_AFTER_DAYS} days",)
        )
        total = c1.rowcount + c2.rowcount
        if total > 0:
            logger.info("Auto-Archiv: %d Faxe archiviert", total)
        else:
            logger.debug("Auto-Archiv: keine Faxe zum Archivieren")


def auto_delete():
    """Archivierte Faxe nach X Tagen loeschen."""
    with db.db_connection() as conn:
        rows = conn.execute(
            """SELECT id, file_path FROM faxes
               WHERE archived = 1
               AND received_at < datetime('now', ?)""",
            (f"-{config.DELETE_AFTER_DAYS} days",)
        ).fetchall()

        deleted_ids = []
        for row in rows:
            try:
                if os.path.exists(row["file_path"]):
                    os.remove(row["file_path"])
                    logger.info("Datei geloescht: %s", row["file_path"])
                deleted_ids.append(row["id"])
            except OSError as e:
                # Bei Datei-Loeschfehler: DB-Record behalten
                logger.warning("Datei konnte nicht geloescht werden: %s (%s)", row["file_path"], e)

        # Nur erfolgreich geloeschte Dateien aus DB entfernen
        if deleted_ids:
            placeholders = ",".join("?" * len(deleted_ids))
            conn.execute(f"DELETE FROM faxes WHERE id IN ({placeholders})", deleted_ids)
            logger.info("Auto-Delete: %d Faxe geloescht", len(deleted_ids))


def _scheduler_loop():
    """Scheduler-Thread: fuehrt geplante Aufgaben aus."""
    # Um 30 Minuten versetzen, damit die beiden Jobs nicht zeitgleich
    # dieselbe DB-Verbindung blockieren.
    schedule.every().hour.at(":00").do(auto_archive)
    schedule.every().hour.at(":30").do(auto_delete)

    # Einmal direkt beim Start ausfuehren
    try:
        auto_archive()
        auto_delete()
    except Exception as e:
        logger.error("Fehler beim initialen Scheduler-Lauf: %s", e)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error("Scheduler-Fehler: %s", e)
        time.sleep(60)


def start_scheduler():
    """Scheduler-Thread starten."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    thread.start()
    logger.info("Scheduler gestartet (Auto-Archiv: %d Tage, Auto-Delete: %d Tage)",
                config.ARCHIVE_AFTER_DAYS, config.DELETE_AFTER_DAYS)
