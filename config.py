"""FaxNode – Konfiguration."""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# NAS-Verzeichnis wo die FritzBox Faxe speichert
FAX_WATCH_DIR = os.environ.get("FAX_WATCH_DIR", "")

# Poppler-Pfad fuer pdf2image (Windows: tools/poppler/Library/bin)
POPPLER_PATH = os.environ.get("POPPLER_PATH", "")
if not POPPLER_PATH and sys.platform == "win32":
    _poppler_candidate = str(BASE_DIR / "tools" / "poppler" / "Library" / "bin")
    if os.path.isdir(_poppler_candidate):
        POPPLER_PATH = _poppler_candidate

# Datenbank
DATABASE = str(BASE_DIR / "data" / "faxnode.db")

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "9741"))
def _get_or_create_secret_key():
    """SECRET_KEY aus .env lesen oder einmalig generieren und persistieren."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    key = secrets.token_hex(32)
    env_path = BASE_DIR / ".env"
    # Key in .env anfuegen, damit er beim naechsten Start erhalten bleibt
    try:
        with open(env_path, "a") as f:
            f.write(f"SECRET_KEY={key}\n")
    except OSError:
        pass  # Funktioniert trotzdem, wird nur nicht persistiert
    return key

SECRET_KEY = _get_or_create_secret_key()

# FritzBox Dateiname: DD.MM.YY_HH.MM_Telefax.RUFNUMMER.pdf
FAX_FILENAME_PATTERN = r"(\d{2})\.(\d{2})\.(\d{2})_(\d{2})\.(\d{2})_Telefax\.(\d+)\.pdf"

# OCR
OCR_LANGUAGE = os.environ.get("OCR_LANGUAGE", "deu")

# Auto-Archiv nach X Tagen
ARCHIVE_AFTER_DAYS = int(os.environ.get("ARCHIVE_AFTER_DAYS", "7"))

# Auto-Delete nach X Tagen
DELETE_AFTER_DAYS = int(os.environ.get("DELETE_AFTER_DAYS", "90"))

# Standarddrucker (Name wie eingerichtet, leer = keiner)
DEFAULT_PRINTER = os.environ.get("DEFAULT_PRINTER", "")

# Discord-Webhook fuer Benachrichtigungen (leer = deaktiviert)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Polling-Fallback Intervall in Sekunden
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

# SSL/TLS Zertifikate
CERT_DIR = str(BASE_DIR / "certs")
SSL_CERT = os.path.join(CERT_DIR, "server.crt")
SSL_KEY = os.path.join(CERT_DIR, "server.key")
CA_CERT = os.path.join(CERT_DIR, "ca.crt")

FAX_STATUSES = {
    "neu": "Neu",
    "gelesen": "Gelesen",
    "bearbeitet": "Bearbeitet",
    "erledigt": "Erledigt",
}

FAX_CATEGORIES = {
    "rezept": "Rezept",
    "bestellung": "Bestellung",
    "lieferschein": "Lieferschein",
    "rueckruf": "Rueckruf",
    "sonstiges": "Sonstiges",
}

# Thumbnail-Verzeichnis (unter static/ fuer direktes Serving ohne API-Call)
THUMBNAIL_DIR = str(BASE_DIR / "static" / "thumbnails")

# Auto-Archiv: alle Faxe nach X Tagen unabhaengig vom Status
FORCE_ARCHIVE_AFTER_DAYS = int(os.environ.get("FORCE_ARCHIVE_AFTER_DAYS", "30"))
