"""FaxNode – Windows-Implementierungen (win32print, UNC-Pfade, PowerShell)."""
import logging
import os
import re
import subprocess
from pathlib import Path

from compat.base import PrinterService, NasService, NetworkService

logger = logging.getLogger(__name__)

# SumatraPDF portable fuer PDF-Druck
_TOOLS_DIR = Path(__file__).parent.parent / "tools"
_SUMATRA_PATH = os.environ.get("SUMATRA_PATH", str(_TOOLS_DIR / "SumatraPDF.exe"))


class WindowsPrinterService(PrinterService):
    """Windows-Druckerverwaltung via win32print + SumatraPDF."""

    def get_printers(self) -> dict:
        import win32print
        printers = {}
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        for _flags, _desc, name, _comment in win32print.EnumPrinters(flags):
            printers[name] = {
                "printer-info": _desc or name,
                "printer-state": "idle",
            }
        return printers

    def print_file(self, file_path: str, printer_name: str, copies: int = 1) -> int:
        printers = self.get_printers()
        if printer_name not in printers:
            raise ValueError(f"Drucker '{printer_name}' nicht gefunden")
        if not os.path.exists(_SUMATRA_PATH):
            raise FileNotFoundError(
                f"SumatraPDF nicht gefunden: {_SUMATRA_PATH} — "
                "bitte install.ps1 erneut ausfuehren"
            )
        r = subprocess.run(
            [_SUMATRA_PATH, "-print-to", printer_name,
             "-print-count", str(copies), "-silent", file_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            raise RuntimeError(f"Druckfehler: {r.stderr.strip()}")
        logger.info("Druckauftrag: %s -> %s (%d Kopien)", file_path, printer_name, copies)
        return 0

    def discover_printers(self) -> list[dict]:
        printers = self.get_printers()
        return [{"uri": name, "name": name} for name in printers]

    def add_printer(self, name: str, uri: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'Add-Printer -Name "{name}" -PortName "{uri}"'],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0:
                return False, r.stderr.strip() or "Drucker konnte nicht hinzugefuegt werden"
            return True, name
        except Exception as e:
            return False, str(e)

    def remove_printer(self, name: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'Remove-Printer -Name "{name}"'],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return False, r.stderr.strip() or "Drucker konnte nicht entfernt werden"
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def test_printer(self, name: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        # Testseite via Windows-Druckdialog
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'rundll32 printui.dll,PrintUIEntry /k /n "{name}"'],
                capture_output=True, text=True, timeout=15
            )
            return True, "Testseite gesendet"
        except Exception as e:
            return False, str(e)


class WindowsNasService(NasService):
    """SMB-Zugriff via UNC-Pfade (Windows)."""

    def scan_network_for_smb(self) -> list[dict]:
        net = WindowsNetworkService()
        gw = net.get_gateway_ip()

        hosts = []
        if gw:
            hosts.append(gw)
        for ip in ["192.168.178.1", "192.168.1.1", "192.168.0.1"]:
            if ip not in hosts:
                hosts.append(ip)

        found = []
        for ip in hosts:
            if net.check_port(ip, 445, timeout=3):
                found.append({"ip": ip, "is_gateway": ip == gw})
        return found

    def list_shares(self, ip: str, username: str, password: str) -> list[dict]:
        # net use fuer Authentifizierung, dann net view fuer Freigaben
        try:
            # Erst authentifizieren
            subprocess.run(
                ["net", "use", f"\\\\{ip}\\IPC$", password, f"/user:{username}"],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass

        r = subprocess.run(
            ["net", "view", f"\\\\{ip}"],
            capture_output=True, text=True, timeout=10
        )
        shares = []
        for line in r.stdout.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+Datenträger\s*(.*)$", line)
            if not m:
                # Englisches Windows
                m = re.match(r"^(\S+)\s+Disk\s*(.*)$", line)
            if m and not m.group(1).endswith("$"):
                shares.append({"name": m.group(1), "comment": m.group(2).strip()})
        return shares

    def browse_share(self, ip: str, share: str, path: str,
                     username: str, password: str) -> dict:
        # Authentifizierung sicherstellen
        self._ensure_credentials(ip, share, username, password)

        unc_path = f"\\\\{ip}\\{share}"
        if path:
            unc_path = os.path.join(unc_path, path)

        entries = []
        pdf_count = 0
        try:
            for item in os.listdir(unc_path):
                full = os.path.join(unc_path, item)
                if os.path.isdir(full):
                    entries.append({"name": item, "type": "dir"})
                elif item.lower().endswith(".pdf"):
                    pdf_count += 1
        except OSError as e:
            logger.warning("UNC-Pfad nicht lesbar: %s — %s", unc_path, e)

        return {"dirs": entries, "pdf_count": pdf_count}

    def connect_nas(self, ip: str, share: str, path: str,
                    username: str, password: str) -> dict:
        unc_share = f"\\\\{ip}\\{share}"

        # Bestehende Verbindung trennen (falls vorhanden)
        subprocess.run(
            ["net", "use", unc_share, "/delete", "/yes"],
            capture_output=True, text=True, timeout=5
        )

        # Persistente Verbindung herstellen
        r = subprocess.run(
            ["net", "use", unc_share, password,
             f"/user:{username}", "/persistent:yes"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"Verbindungsfehler: {r.stderr.strip()}"}

        fax_dir = unc_share
        if path:
            fax_dir = os.path.join(fax_dir, path)

        # Pruefen ob Dateien lesbar sind
        try:
            files = os.listdir(fax_dir)
            pdfs = [f for f in files if f.lower().endswith(".pdf")]
            if pdfs:
                test_path = os.path.join(fax_dir, pdfs[0])
                with open(test_path, "rb") as f:
                    f.read(10)
            return {"ok": True, "fax_dir": fax_dir, "pdf_count": len(pdfs)}
        except Exception as e:
            return {"ok": False,
                    "error": f"Verbindung erfolgreich, aber Dateien nicht lesbar: {e}"}

    def _ensure_credentials(self, ip: str, share: str, username: str, password: str):
        """Sicherstellen dass UNC-Pfad authentifiziert ist."""
        try:
            subprocess.run(
                ["net", "use", f"\\\\{ip}\\{share}", password,
                 f"/user:{username}"],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass


class WindowsNetworkService(NetworkService):
    """Netzwerk-Hilfsfunktionen (Windows)."""

    def get_gateway_ip(self) -> str | None:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-NetRoute -DestinationPrefix '0.0.0.0/0').NextHop"],
                capture_output=True, text=True, timeout=5
            )
            lines = r.stdout.strip().splitlines()
            if lines:
                return lines[0].strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Gateway-Erkennung fehlgeschlagen: %s", e)
        return None
