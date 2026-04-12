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
    """Erledigte Faxe nach X Tagen archivieren."""
    with db.db_connection() as conn:
        cursor = conn.execute(
            """UPDATE faxes
               SET archived = 1, archived_at = CURRENT_TIMESTAMP
               WHERE archived = 0
               AND status = 'erledigt'
               AND received_at < datetime('now', ?)""",
            (f"-{config.ARCHIVE_AFTER_DAYS} days",)
        )
        if cursor.rowcount > 0:
            logger.info("Auto-Archiv: %d Faxe archiviert", cursor.rowcount)


def auto_delete():
    """Archivierte Faxe nach X Tagen loeschen."""
    with db.db_connection() as conn:
        # Zuerst Dateipfade holen
        rows = conn.execute(
            """SELECT id, file_path FROM faxes
               WHERE archived = 1
               AND received_at < datetime('now', ?)""",
            (f"-{config.DELETE_AFTER_DAYS} days",)
        ).fetchall()

        for row in rows:
            # PDF loeschen (optional, falls Datei noch existiert)
            try:
                if os.path.exists(row["file_path"]):
                    os.remove(row["file_path"])
                    logger.info("Datei geloescht: %s", row["file_path"])
            except OSError as e:
                logger.warning("Datei konnte nicht geloescht werden: %s (%s)", row["file_path"], e)

        # DB-Eintraege loeschen
        if rows:
            conn.execute(
                """DELETE FROM faxes
                   WHERE archived = 1
                   AND received_at < datetime('now', ?)""",
                (f"-{config.DELETE_AFTER_DAYS} days",)
            )
            logger.info("Auto-Delete: %d Faxe geloescht", len(rows))


def _scheduler_loop():
    """Scheduler-Thread: fuehrt geplante Aufgaben aus."""
    schedule.every().hour.do(auto_archive)
    schedule.every().hour.do(auto_delete)

    # Einmal direkt beim Start ausfuehren
    auto_archive()
    auto_delete()

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_scheduler():
    """Scheduler-Thread starten."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    thread.start()
    logger.info("Scheduler gestartet (Auto-Archiv: %d Tage, Auto-Delete: %d Tage)",
                config.ARCHIVE_AFTER_DAYS, config.DELETE_AFTER_DAYS)
