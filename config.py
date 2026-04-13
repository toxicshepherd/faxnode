"""FaxNode – Konfiguration."""
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# NAS-Verzeichnis wo die FritzBox Faxe speichert
FAX_WATCH_DIR = os.environ.get("FAX_WATCH_DIR", "/mnt/nas/faxe")

# Datenbank
DATABASE = str(BASE_DIR / "data" / "faxnode.db")

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# FritzBox Dateiname: DD.MM.YY_HH.MM_Telefax.RUFNUMMER.pdf
FAX_FILENAME_PATTERN = r"(\d{2})\.(\d{2})\.(\d{2})_(\d{2})\.(\d{2})_Telefax\.(\d+)\.pdf"

# OCR
OCR_LANGUAGE = os.environ.get("OCR_LANGUAGE", "deu")

# Auto-Archiv nach X Tagen
ARCHIVE_AFTER_DAYS = int(os.environ.get("ARCHIVE_AFTER_DAYS", "7"))

# Auto-Delete nach X Tagen
DELETE_AFTER_DAYS = int(os.environ.get("DELETE_AFTER_DAYS", "90"))

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
