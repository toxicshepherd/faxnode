<p align="center">
  <img src="https://img.shields.io/github/v/release/toxicshepherd/faxnode?style=flat-square&color=39d353" alt="Release">
  <img src="https://img.shields.io/github/license/toxicshepherd/faxnode?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Plattform-Linux%20%7C%20Windows-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
</p>

# FaxNode

**Digitaler Faxempfang und -verwaltung fuer Apotheken und Praxen.**

FaxNode ueberwacht das NAS-Verzeichnis deiner FritzBox, erkennt neue Faxe automatisch, extrahiert den Text per OCR und stellt alles ueber eine moderne Web-Oberflaeche bereit — mit Live-Updates, Volltextsuche, Druck-Integration und automatischer Archivierung.

> Faxe digital empfangen, verwalten und archivieren — ohne Papier, ohne Tinte.

---

## Features

### Fax-Empfang & Erkennung
- **Automatische Ueberwachung** des FritzBox-NAS-Verzeichnisses (SMB/CIFS)
- **Sofortige Erkennung** neuer Faxe mit Polling-Fallback (inotify funktioniert nicht auf CIFS)
- **OCR-Texterkennung** via Tesseract (optimiert fuer deutsche Dokumente)
- **Volltextsuche** ueber alle Faxe (SQLite FTS5)
- **Thumbnail-Generierung** fuer schnelle Vorschau in der Liste

### Verwaltung & Workflow
- **Status-System**: Neu → Gelesen → Bearbeitet → Erledigt (direkt in der Liste klickbar)
- **Auto-Read**: Fax wird nach 5 Sekunden Ansicht automatisch als "Gelesen" markiert
- **Kategorien**: Rezept, Bestellung, Lieferschein, Rueckruf, Sonstiges (erweiterbar)
- **Adressbuch**: Absender benennen, Standard-Kategorie und Auto-Druck-Regeln festlegen
- **Notizen**: Pro Fax koennen Mitarbeiter Notizen hinterlassen
- **Archivierung**: Manuell per Button oder automatisch nach X Tagen

### Druck
- **Netzwerkdrucker-Erkennung** (CUPS auf Linux, win32print auf Windows)
- **Standarddrucker** in Einstellungen festlegbar — kein Popup beim Drucken
- **Auto-Print**: Faxe bestimmter Absender automatisch drucken (konfigurierbar im Adressbuch)
- **Druck-Tracking**: Sichtbar ob/wann/wo ein Fax gedruckt wurde

### Echtzeit
- **Server-Sent Events (SSE)** — alle offenen Browser aktualisieren sich sofort
- **Browser-Benachrichtigungen** + Ton bei neuem Fax
- **Tab-Titel** zeigt Anzahl ungelesener Faxe: `(3) FaxNode`

### Plattform-Support
- **Linux** (Raspberry Pi, Debian, Ubuntu) — CUPS, smbclient, systemd
- **Windows** (10/11) — win32print, SumatraPDF, UNC-Pfade, Windows-Dienst
- **Windows-Client** — Desktop-App mit Auto-Discovery und eingebettetem WebView

---

## Screenshots

<details>
<summary>Faxliste (Dark Theme)</summary>
<br>
Grid-Layout mit Status-Buttons, Kategorie-Badges, Vorschau-Text und Aktionen.
</details>

<details>
<summary>Fax-Detailansicht</summary>
<br>
PDF-Vorschau, OCR-Text, Status, Kategorie, Druck-Status, Notizen.
</details>

<details>
<summary>Setup-Wizard</summary>
<br>
Schritt-fuer-Schritt-Einrichtung: NAS finden, SMB-Zugangsdaten, Fax-Ordner, Drucker.
</details>

---

## Installation

### Linux (Raspberry Pi / Debian / Ubuntu)

Ein Befehl — installiert alle Abhaengigkeiten, richtet den Dienst ein und startet den Setup-Wizard:

```bash
curl -fsSL https://raw.githubusercontent.com/toxicshepherd/faxnode/main/install.sh | bash
```

<details>
<summary>Was der Installer macht</summary>

1. Installiert System-Pakete: Python 3, Tesseract OCR (deutsch), Poppler, CUPS, smbclient
2. Erstellt Python-Virtualenv mit allen Dependencies
3. Generiert SSL-Zertifikate (Self-Signed)
4. Richtet systemd-Service ein (Auto-Start bei Boot)
5. Erstellt Firewall-Regel (Port 9741)
6. Startet FaxNode und oeffnet den Setup-Wizard

</details>

### Windows

PowerShell als Administrator:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
iwr -useb https://raw.githubusercontent.com/toxicshepherd/faxnode/main/install.ps1 | iex
```

<details>
<summary>Was der Installer macht</summary>

1. Installiert via winget: Python, Git, Poppler, SumatraPDF
2. Erstellt Python-Virtualenv
3. Richtet FaxNode als Windows-Dienst ein (via NSSM)
4. Erstellt Firewall-Regel
5. Startet den Setup-Wizard

</details>

### Windows-Client (Desktop-App)

Fuer Arbeitsplaetze, die nur auf den FaxNode-Server zugreifen wollen:

1. **[FaxNode-Setup.exe herunterladen](https://github.com/toxicshepherd/faxnode/releases/latest)**
2. Installer ausfuehren
3. Der Client findet den Server automatisch im Netzwerk (UDP-Discovery)

---

## Nach der Installation

Oeffne im Browser: `https://<IP>:9741`

Der **Setup-Wizard** fuehrt durch:
1. FritzBox/NAS im Netzwerk finden
2. SMB-Zugangsdaten eingeben
3. Fax-Ordner auswaehlen
4. NAS automatisch mounten (Linux) / UNC-Pfad verbinden (Windows)
5. Drucker einrichten (optional)

---

## Update

### Linux
```bash
cd /opt/faxnode && git pull && sudo systemctl restart faxnode
```

### Windows
```powershell
cd C:\faxnode; git pull; Restart-Service FaxNode
```

---

## Architektur

```
┌─────────────────────────────────────────────────────┐
│                    Browser / Client                   │
│         (Vanilla JS, SSE, NorthNode Dark Theme)       │
└───────────────────────┬─────────────────────────────┘
                        │ HTTPS
┌───────────────────────┴─────────────────────────────┐
│              Flask + Gunicorn / Waitress              │
│                                                       │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │ Watcher  │ │   OCR    │ │Scheduler│ │ Discovery │ │
│  │(NAS-Poll)│ │(Tesseract)│ │(Archiv) │ │  (UDP)   │ │
│  └────┬─────┘ └────┬─────┘ └───┬────┘ └───────────┘ │
│       └─────────────┴───────────┘                     │
│                     │                                 │
│            ┌────────┴────────┐                        │
│            │  SQLite + FTS5  │                        │
│            │   (WAL-Modus)   │                        │
│            └─────────────────┘                        │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │           compat/ (Plattform-Abstraktion)        │ │
│  │  Linux: CUPS, smbclient, mount, systemd          │ │
│  │  Windows: win32print, SumatraPDF, UNC, PowerShell│ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### Projektstruktur

```
faxnode/
├── app.py                 # Flask-App: Routes, API, SSE, Background-Services
├── config.py              # Konfiguration aus Umgebungsvariablen
├── db.py                  # SQLite-Datenbankschicht mit FTS5
├── watcher.py             # NAS-Verzeichnis ueberwachen (Polling)
├── scheduler.py           # Auto-Archivierung und -Loeschung
├── ocr.py                 # Tesseract OCR + Thumbnail-Generierung
├── printer.py             # Druck-Service (delegiert an compat/)
├── wsgi.py                # WSGI-Einstiegspunkt
├── compat/                # Plattform-Abstraktion
│   ├── base.py            #   Abstrakte Basisklassen
│   ├── linux.py           #   Linux: CUPS, smbclient, mount
│   ├── windows.py         #   Windows: win32print, UNC, PowerShell
│   └── certs.py           #   SSL-Zertifikat-Generierung
├── client/                # Windows Desktop-Client
│   ├── faxnode_client.py  #   PyWebView-App mit Auto-Discovery
│   ├── installer.iss      #   Inno Setup Installer-Skript
│   └── faxnode.ico        #   App-Icon
├── templates/             # Jinja2-Templates
│   ├── base.html          #   Basis-Layout (Sidebar, Navigation)
│   ├── index.html         #   Faxliste
│   ├── fax_detail.html    #   Fax-Detailansicht
│   ├── archive.html       #   Archiv
│   ├── address_book.html  #   Adressbuch
│   ├── settings.html      #   Einstellungen
│   ├── setup.html         #   Setup-Wizard
│   └── statistics.html    #   Statistiken
├── static/
│   ├── css/style.css      #   NorthNode Design System (Dark Theme)
│   └── js/app.js          #   Frontend-Logik, SSE-Handler
├── install.sh             # Linux-Installer
├── install.ps1            # Windows-Installer
└── .github/workflows/
    └── build-client.yml   # GitHub Actions: Windows-Client bauen
```

---

## Konfiguration

Alle Einstellungen werden ueber Umgebungsvariablen oder die `.env`-Datei gesetzt:

| Variable | Standard | Beschreibung |
|----------|----------|-------------|
| `FAX_WATCH_DIR` | `/mnt/nas/faxe` | Verzeichnis mit FritzBox-Faxen |
| `PORT` | `9741` | Web-Server-Port |
| `OCR_LANGUAGE` | `deu` | Tesseract-Sprache |
| `ARCHIVE_AFTER_DAYS` | `7` | Erledigte Faxe nach X Tagen archivieren |
| `DELETE_AFTER_DAYS` | `90` | Archivierte Faxe nach X Tagen loeschen |
| `FORCE_ARCHIVE_AFTER_DAYS` | `30` | Alle Faxe nach X Tagen zwangsarchivieren |
| `DEFAULT_PRINTER` | _(leer)_ | Standarddrucker fuer Schnelldruck |
| `POLL_INTERVAL` | `30` | NAS-Polling-Intervall in Sekunden |

Die meisten Einstellungen koennen auch ueber die Web-Oberflaeche unter **Einstellungen** geaendert werden.

---

## API

FaxNode bietet eine REST-API fuer alle Operationen:

| Methode | Endpoint | Beschreibung |
|---------|----------|-------------|
| `GET` | `/api/faxe` | Faxliste (mit Pagination, Suche, Filter) |
| `GET` | `/api/fax/<id>` | Einzelnes Fax |
| `POST` | `/api/fax/<id>/status` | Status aendern |
| `POST` | `/api/fax/<id>/kategorie` | Kategorie aendern |
| `POST` | `/api/fax/<id>/notiz` | Notiz hinzufuegen |
| `POST` | `/api/fax/<id>/drucken` | Fax drucken |
| `POST` | `/api/fax/<id>/archivieren` | Fax archivieren |
| `POST` | `/api/fax/<id>/wiederherstellen` | Aus Archiv wiederherstellen |
| `GET` | `/api/drucker` | Verfuegbare Drucker |
| `GET/POST` | `/api/adressbuch` | Adressbuch verwalten |
| `GET/POST` | `/api/einstellungen/standarddrucker` | Standarddrucker |
| `GET` | `/api/unread` | Anzahl ungelesener Faxe |
| `GET` | `/events` | SSE-Stream (Echtzeit-Updates) |

---

## Tech Stack

| Komponente | Technologie |
|-----------|-------------|
| Backend | Flask 3.1, Gunicorn (Linux) / Waitress (Windows) |
| Datenbank | SQLite mit WAL-Modus + FTS5 Volltextsuche |
| OCR | Tesseract (deutsch), pdf2image + Poppler |
| Echtzeit | Server-Sent Events (SSE) |
| Druck | CUPS (Linux) / win32print + SumatraPDF (Windows) |
| NAS | CIFS/SMB mount (Linux) / UNC-Pfade (Windows) |
| Frontend | Vanilla JavaScript, CSS Custom Properties |
| Desktop-Client | PyWebView (Windows) |
| CI/CD | GitHub Actions (PyInstaller + Inno Setup) |
| SSL | Self-Signed Zertifikate via Python cryptography |

---

## Voraussetzungen

### Server (Linux)
- Raspberry Pi 4 (2+ GB RAM) oder beliebiger Linux-Server
- Netzwerkzugang zur FritzBox / NAS
- FritzBox mit aktivierter NAS-Funktion (SMB/CIFS)

### Server (Windows)
- Windows 10/11 mit PowerShell 5.1+
- Netzwerkzugang zur FritzBox / NAS

### Client (optional)
- Windows 10/11
- Netzwerkzugang zum FaxNode-Server

---

## Bekannte Einschraenkungen

- **CIFS + inotify**: Dateisystem-Events funktionieren nicht auf SMB-Mounts — FaxNode nutzt Polling als Fallback (Standard: 30 Sekunden)
- **OCR-Geschwindigkeit**: Ca. 3-8 Sekunden pro Seite auf einem Raspberry Pi 4
- **FritzBox SMB**: Benoetigt aktiviertes SMB unter Heimnetz → Speicher → Speicher (NAS)
- **Einzelner Benutzer**: Kein Login-System — FaxNode ist fuer vertrauenswuerdige lokale Netzwerke gedacht

---

## Lizenz

MIT

---

<p align="center">
  <sub>Ein Projekt von <a href="https://northnode.dev">NorthNode</a></sub>
</p>
