"""FaxNode – SQLite Datenbank-Layer."""
import sqlite3
import os
from contextlib import contextmanager
from config import DATABASE


def _escape_like(value: str) -> str:
    """LIKE-Wildcards escapen (%, _, \\)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sanitize_fts_query(query: str) -> str:
    """FTS5-Metazeichen escapen fuer sichere MATCH-Queries.

    Wrapt jeden Term in Anfuehrungszeichen, sodass FTS5-Operatoren
    (AND, OR, NOT, *, Klammern) als Literale behandelt werden.
    """
    query = query.replace('"', '""')
    terms = query.split()
    if not terms:
        return '""'
    return " ".join(f'"{t}"' for t in terms)

SCHEMA = """
-- Faxe: Kern-Tabelle
CREATE TABLE IF NOT EXISTS faxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    phone_number TEXT NOT NULL,
    received_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'neu',
    category TEXT NOT NULL DEFAULT 'sonstiges',
    ocr_text TEXT,
    ocr_done INTEGER DEFAULT 0,
    thumbnail_path TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    page_count INTEGER DEFAULT 1,
    archived INTEGER DEFAULT 0,
    archived_at TIMESTAMP,
    printed INTEGER DEFAULT 0,
    printed_at TIMESTAMP,
    printed_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_faxes_status ON faxes(status);
CREATE INDEX IF NOT EXISTS idx_faxes_phone ON faxes(phone_number);
CREATE INDEX IF NOT EXISTS idx_faxes_received ON faxes(received_at);
CREATE INDEX IF NOT EXISTS idx_faxes_archived ON faxes(archived);
CREATE INDEX IF NOT EXISTS idx_faxes_category ON faxes(category);

-- Volltextsuche (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS faxes_fts USING fts5(
    ocr_text,
    content='faxes',
    content_rowid='id'
);

-- FTS Sync-Trigger
CREATE TRIGGER IF NOT EXISTS faxes_ai AFTER INSERT ON faxes BEGIN
    INSERT INTO faxes_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS faxes_ad AFTER DELETE ON faxes BEGIN
    INSERT INTO faxes_fts(faxes_fts, rowid, ocr_text) VALUES('delete', old.id, old.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS faxes_au AFTER UPDATE OF ocr_text ON faxes BEGIN
    INSERT INTO faxes_fts(faxes_fts, rowid, ocr_text) VALUES('delete', old.id, old.ocr_text);
    INSERT INTO faxes_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

-- Notizen an Faxe
CREATE TABLE IF NOT EXISTS fax_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fax_id INTEGER NOT NULL,
    author TEXT NOT NULL DEFAULT 'Mitarbeiter',
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fax_id) REFERENCES faxes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notes_fax ON fax_notes(fax_id);

-- Adressbuch
CREATE TABLE IF NOT EXISTS address_book (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    default_category TEXT NOT NULL DEFAULT 'sonstiges',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_address_phone ON address_book(phone_number);

-- Auto-Druck Regeln
CREATE TABLE IF NOT EXISTS print_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT NOT NULL,
    printer_name TEXT NOT NULL,
    copies INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_print_rules_phone ON print_rules(phone_number);
"""


def get_db():
    """Erstelle eine neue DB-Verbindung mit WAL-Modus."""
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_connection():
    """Context Manager fuer DB-Verbindungen."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Datenbank initialisieren."""
    with db_connection() as conn:
        conn.executescript(SCHEMA)
        # Migrationen fuer bestehende DBs
        _migrate(conn)


def _migrate(conn):
    """Spalten hinzufuegen falls sie fehlen (fuer Updates)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(faxes)").fetchall()}
    if "category" not in cols:
        conn.execute("ALTER TABLE faxes ADD COLUMN category TEXT NOT NULL DEFAULT 'sonstiges'")
    if "thumbnail_path" not in cols:
        conn.execute("ALTER TABLE faxes ADD COLUMN thumbnail_path TEXT")
    addr_cols = {r[1] for r in conn.execute("PRAGMA table_info(address_book)").fetchall()}
    if "default_category" not in addr_cols:
        conn.execute("ALTER TABLE address_book ADD COLUMN default_category TEXT NOT NULL DEFAULT 'sonstiges'")
    if "auto_print" not in addr_cols:
        conn.execute("ALTER TABLE address_book ADD COLUMN auto_print INTEGER DEFAULT 0")
    if "printer_name" not in addr_cols:
        conn.execute("ALTER TABLE address_book ADD COLUMN printer_name TEXT")
    if "print_copies" not in addr_cols:
        conn.execute("ALTER TABLE address_book ADD COLUMN print_copies INTEGER DEFAULT 1")
    if "printed" not in cols:
        conn.execute("ALTER TABLE faxes ADD COLUMN printed INTEGER DEFAULT 0")
    if "printed_at" not in cols:
        conn.execute("ALTER TABLE faxes ADD COLUMN printed_at TIMESTAMP")
    if "printed_by" not in cols:
        conn.execute("ALTER TABLE faxes ADD COLUMN printed_by TEXT")


# --- Fax Queries ---

def get_faxes(status=None, category=None, archived=0, search=None, limit=100, offset=0):
    """Faxe abfragen mit optionalen Filtern."""
    with db_connection() as conn:
        if search:
            escaped = _escape_like(search)
            query = """
                SELECT f.*, ab.name as sender_name
                FROM faxes f
                LEFT JOIN address_book ab ON f.phone_number = ab.phone_number
                WHERE f.archived = ?
                AND f.id IN (
                    SELECT rowid FROM faxes_fts WHERE faxes_fts MATCH ?
                    UNION
                    SELECT f2.id FROM faxes f2
                    LEFT JOIN address_book ab2 ON f2.phone_number = ab2.phone_number
                    WHERE f2.phone_number LIKE ? ESCAPE '\\' OR ab2.name LIKE ? ESCAPE '\\'
                )
            """
            params = [archived, _sanitize_fts_query(search), f"%{escaped}%", f"%{escaped}%"]
        else:
            query = """
                SELECT f.*, ab.name as sender_name
                FROM faxes f
                LEFT JOIN address_book ab ON f.phone_number = ab.phone_number
                WHERE f.archived = ?
            """
            params = [archived]

        if status:
            query += " AND f.status = ?"
            params.append(status)

        if category:
            query += " AND f.category = ?"
            params.append(category)

        query += " ORDER BY f.received_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        return conn.execute(query, params).fetchall()


def get_fax(fax_id):
    """Einzelnes Fax abrufen."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT f.*, ab.name as sender_name
               FROM faxes f
               LEFT JOIN address_book ab ON f.phone_number = ab.phone_number
               WHERE f.id = ?""",
            (fax_id,)
        ).fetchone()


def insert_fax(filename, phone_number, received_at, file_path, file_size, page_count=1, category="sonstiges"):
    """Neues Fax einfuegen."""
    with db_connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO faxes
               (filename, phone_number, received_at, file_path, file_size, page_count, category)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, phone_number, received_at, file_path, file_size, page_count, category)
        )
        return cursor.lastrowid if cursor.rowcount > 0 else None


def update_fax_status(fax_id, status):
    """Fax-Status aendern."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, fax_id)
        )


def update_fax_ocr(fax_id, ocr_text, ocr_done=1):
    """OCR-Text fuer ein Fax speichern."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET ocr_text = ?, ocr_done = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ocr_text, ocr_done, fax_id)
        )


def record_print_event(fax_id, printer_name):
    """Druckvorgang fuer ein Fax aufzeichnen."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET printed = 1, printed_at = CURRENT_TIMESTAMP, "
            "printed_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (printer_name, fax_id)
        )


def archive_fax(fax_id):
    """Einzelnes Fax manuell archivieren."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET archived = 1, archived_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (fax_id,)
        )


def unarchive_fax(fax_id):
    """Fax aus dem Archiv wiederherstellen."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET archived = 0, archived_at = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (fax_id,)
        )


def get_fax_count_by_status(archived=0):
    """Anzahl Faxe pro Status."""
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM faxes WHERE archived = ? GROUP BY status",
            (archived,)
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}


def get_fax_counts(archived=0):
    """Status- und Kategorie-Zaehler in einer DB-Verbindung."""
    with db_connection() as conn:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM faxes WHERE archived = ? GROUP BY status",
            (archived,)
        ).fetchall()
        cat_rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM faxes WHERE archived = ? GROUP BY category",
            (archived,)
        ).fetchall()
        return (
            {r["status"]: r["cnt"] for r in status_rows},
            {r["category"]: r["cnt"] for r in cat_rows},
        )


# --- Notizen ---

def get_notes(fax_id):
    """Notizen zu einem Fax."""
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM fax_notes WHERE fax_id = ? ORDER BY created_at ASC",
            (fax_id,)
        ).fetchall()


def add_note(fax_id, author, message):
    """Notiz hinzufuegen."""
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO fax_notes (fax_id, author, message) VALUES (?, ?, ?)",
            (fax_id, author, message)
        )
        return cursor.lastrowid


# --- Adressbuch ---

def get_address_book():
    """Alle Adressbuch-Eintraege."""
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM address_book ORDER BY name ASC"
        ).fetchall()


def get_address_entry(phone_number):
    """Einzelnen Adressbuch-Eintrag."""
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM address_book WHERE phone_number = ?",
            (phone_number,)
        ).fetchone()


def upsert_address(phone_number, name, default_category="sonstiges", notes=None,
                   auto_print=0, printer_name=None, print_copies=1):
    """Adressbuch-Eintrag anlegen oder aktualisieren."""
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO address_book (phone_number, name, default_category, notes, auto_print, printer_name, print_copies)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(phone_number)
               DO UPDATE SET name = ?, default_category = ?, notes = ?, auto_print = ?, printer_name = ?, print_copies = ?, updated_at = CURRENT_TIMESTAMP""",
            (phone_number, name, default_category, notes, auto_print, printer_name, print_copies,
             name, default_category, notes, auto_print, printer_name, print_copies)
        )


def delete_address(address_id):
    """Adressbuch-Eintrag loeschen."""
    with db_connection() as conn:
        conn.execute("DELETE FROM address_book WHERE id = ?", (address_id,))


# --- Druckregeln ---

def get_print_rules():
    """Alle Druckregeln."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT pr.*, ab.name as sender_name
               FROM print_rules pr
               LEFT JOIN address_book ab ON pr.phone_number = ab.phone_number
               ORDER BY pr.phone_number ASC"""
        ).fetchall()


def get_print_rules_for_number(phone_number):
    """Druckregeln fuer eine bestimmte Nummer (aus Adressbuch)."""
    with db_connection() as conn:
        entry = conn.execute(
            "SELECT * FROM address_book WHERE phone_number = ? AND auto_print = 1 AND printer_name IS NOT NULL",
            (phone_number,)
        ).fetchone()
        if entry:
            return [entry]
        # Fallback: alte print_rules Tabelle
        return conn.execute(
            "SELECT * FROM print_rules WHERE phone_number = ? AND enabled = 1",
            (phone_number,)
        ).fetchall()


def upsert_print_rule(phone_number, printer_name, copies=1):
    """Druckregel anlegen."""
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO print_rules (phone_number, printer_name, copies) VALUES (?, ?, ?)",
            (phone_number, printer_name, copies)
        )
        return cursor.lastrowid


def delete_print_rule(rule_id):
    """Druckregel loeschen."""
    with db_connection() as conn:
        conn.execute("DELETE FROM print_rules WHERE id = ?", (rule_id,))


# --- Kategorien ---

def update_fax_category(fax_id, category):
    """Fax-Kategorie aendern."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET category = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (category, fax_id)
        )


def get_fax_count_by_category(archived=0):
    """Anzahl Faxe pro Kategorie."""
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM faxes WHERE archived = ? GROUP BY category",
            (archived,)
        ).fetchall()
        return {row["category"]: row["cnt"] for row in rows}


def get_unread_count():
    """Anzahl ungelesener Faxe (Status 'neu')."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM faxes WHERE status = 'neu' AND archived = 0"
        ).fetchone()
        return row["cnt"]


def get_archive_count(search=None):
    """Gesamtanzahl archivierter Faxe (fuer Pagination)."""
    with db_connection() as conn:
        if search:
            escaped = _escape_like(search)
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM faxes f
                   LEFT JOIN address_book ab ON f.phone_number = ab.phone_number
                   WHERE f.archived = 1 AND (
                       f.id IN (SELECT rowid FROM faxes_fts WHERE faxes_fts MATCH ?)
                       OR f.phone_number LIKE ? ESCAPE '\\' OR ab.name LIKE ? ESCAPE '\\'
                   )""",
                (_sanitize_fts_query(search), f"%{escaped}%", f"%{escaped}%")
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM faxes WHERE archived = 1"
            ).fetchone()
        return row["cnt"]


def get_failed_ocr_fax_ids():
    """IDs von Faxen mit fehlgeschlagenem/ausstehendem OCR oder fehlendem Thumbnail."""
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT id FROM faxes
               WHERE ocr_done IN (0, -1)
               OR (ocr_done = 1 AND thumbnail_path IS NULL)
               ORDER BY id ASC"""
        ).fetchall()
        return [row["id"] for row in rows]


# --- Thumbnails ---

def update_fax_thumbnail(fax_id, thumbnail_path):
    """Thumbnail-Pfad fuer ein Fax speichern."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE faxes SET thumbnail_path = ? WHERE id = ?",
            (thumbnail_path, fax_id)
        )


# --- Statistiken ---

def get_stats_faxes_per_week(weeks=12):
    """Faxe pro Woche (letzte N Wochen)."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT strftime('%Y-W%W', received_at) as week,
                      COUNT(*) as cnt
               FROM faxes
               WHERE received_at >= datetime('now', ?)
               GROUP BY week ORDER BY week ASC""",
            (f"-{weeks * 7} days",)
        ).fetchall()


def get_stats_top_senders(limit=10):
    """Top-Absender nach Anzahl Faxe."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT f.phone_number, ab.name as sender_name, COUNT(*) as cnt
               FROM faxes f
               LEFT JOIN address_book ab ON f.phone_number = ab.phone_number
               GROUP BY f.phone_number
               ORDER BY cnt DESC LIMIT ?""",
            (limit,)
        ).fetchall()


def get_stats_categories():
    """Faxe pro Kategorie (alle, nicht nur aktive)."""
    with db_connection() as conn:
        return conn.execute(
            "SELECT category, COUNT(*) as cnt FROM faxes GROUP BY category ORDER BY cnt DESC"
        ).fetchall()


def get_stats_overview():
    """Allgemeine Statistiken (eine Query statt fuenf)."""
    with db_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN archived = 0 THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) as archived,
                SUM(CASE WHEN date(received_at) = date('now') THEN 1 ELSE 0 END) as today,
                SUM(CASE WHEN received_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END) as this_week
            FROM faxes
        """).fetchone()
        return {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
            "archived": row["archived"] or 0,
            "today": row["today"] or 0,
            "this_week": row["this_week"] or 0,
        }
