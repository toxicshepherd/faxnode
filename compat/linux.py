"""FaxNode – Linux-Implementierungen (CUPS, smbclient, mount)."""
import logging
import os
import re
import subprocess
from pathlib import Path

from compat.base import PrinterService, NasService, NetworkService

logger = logging.getLogger(__name__)

# Pfad zum Setup-Helper (privilegierte Operationen via sudo)
_SETUP_HELPER = str(Path(__file__).parent.parent / "setup-helper.sh")


class LinuxPrinterService(PrinterService):
    """CUPS-basierte Druckerverwaltung."""

    def get_printers(self) -> dict:
        import cups
        conn = cups.Connection()
        return conn.getPrinters()

    def print_file(self, file_path: str, printer_name: str, copies: int = 1) -> int:
        import cups
        conn = cups.Connection()
        printers = conn.getPrinters()
        if printer_name not in printers:
            raise ValueError(f"Drucker '{printer_name}' nicht gefunden")
        job_id = conn.printFile(printer_name, file_path, "FaxNode",
                                {"copies": str(copies)})
        logger.info("Druckauftrag %d: %s -> %s (%d Kopien)",
                     job_id, file_path, printer_name, copies)
        return job_id

    def discover_printers(self) -> list[dict]:
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "discover-printers"],
            capture_output=True, text=True, timeout=20
        )
        printers = []
        seen = set()
        for line in r.stdout.splitlines():
            if line.strip() == "---END---":
                break
            parts = line.strip().split(" ", 1)
            if len(parts) == 2:
                uri = parts[1].strip()
                if uri in seen:
                    continue
                seen.add(uri)
                name = uri.split("/")[-1] if "/" in uri else uri
                name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
                printers.append({"uri": uri, "name": name})
        return printers

    def add_printer(self, name: str, uri: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "add-printer", name, uri, "everywhere"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return False, r.stderr.strip() or "Drucker konnte nicht hinzugefuegt werden"
        return True, name

    def remove_printer(self, name: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "remove-printer", name],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return False, r.stderr.strip() or "Drucker konnte nicht entfernt werden"
        return True, "OK"

    def test_printer(self, name: str) -> tuple[bool, str]:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "test-printer", name],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return False, r.stderr.strip() or "Testseite konnte nicht gedruckt werden"
        return True, "OK"


class LinuxNasService(NasService):
    """SMB-Zugriff via smbclient + mount (Linux)."""

    def scan_network_for_smb(self) -> list[dict]:
        net = LinuxNetworkService()
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
        env = {**os.environ, "PASSWD": password}
        r = subprocess.run(
            ["smbclient", "-L", f"//{ip}", "-U", username],
            capture_output=True, text=True, timeout=10, env=env
        )
        shares = []
        for line in r.stdout.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+Disk\s+(.*)$", line)
            if m and not m.group(1).endswith("$"):
                shares.append({"name": m.group(1), "comment": m.group(2).strip()})
        return shares

    def browse_share(self, ip: str, share: str, path: str,
                     username: str, password: str) -> dict:
        cmd_path = f"{path}/" if path else ""
        env = {**os.environ, "PASSWD": password}
        r = subprocess.run(
            ["smbclient", f"//{ip}/{share}", "-U", username,
             "-c", f"ls {cmd_path}*"],
            capture_output=True, text=True, timeout=10, env=env
        )
        entries = []
        pdf_count = 0
        for line in r.stdout.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+([A-Z]*D[A-Z]*)\s+\d+\s+.+$", line)
            if m and m.group(1) not in (".", ".."):
                entries.append({"name": m.group(1), "type": "dir"})
            elif line.lower().endswith(".pdf"):
                pdf_count += 1
        return {"dirs": entries, "pdf_count": pdf_count}

    def connect_nas(self, ip: str, share: str, path: str,
                    username: str, password: str) -> dict:
        mount_point = "/mnt/nas/faxe"
        smb_path = f"//{ip}/{share}"
        if path:
            smb_path += f"/{path}"

        # 1. Credentials schreiben
        creds_content = f"username={username}\npassword={password}\n"
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "write-creds"],
            input=creds_content, capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"Credentials-Fehler: {r.stderr}"}

        # 2. fstab Eintrag
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "add-fstab", smb_path, mount_point],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"fstab-Fehler: {r.stderr}"}

        # 3. Mounten
        r = subprocess.run(
            ["sudo", _SETUP_HELPER, "mount", mount_point],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"Mount-Fehler: {r.stderr}"}

        # 4. Pruefen ob Dateien lesbar sind
        # Kurz warten damit der frische Mount vollstaendig bereit ist
        # und keine stale file handles vom vorherigen Mount uebrig sind.
        import time
        time.sleep(1)
        try:
            # Frischen Verzeichnis-Scan erzwingen (O_DIRECTORY bypass fuer stale caches)
            fd = os.open(mount_point, os.O_RDONLY | os.O_DIRECTORY)
            os.close(fd)
            files = os.listdir(mount_point)
            pdfs = [f for f in files if f.lower().endswith(".pdf")]
            if pdfs:
                test_path = os.path.join(mount_point, pdfs[0])
                with open(test_path, "rb") as f:
                    f.read(10)
            return {"ok": True, "fax_dir": mount_point, "pdf_count": len(pdfs)}
        except Exception as e:
            return {"ok": False, "error": f"Mount erfolgreich, aber Dateien nicht lesbar: {e}"}


class LinuxNetworkService(NetworkService):
    """Netzwerk-Hilfsfunktionen (Linux)."""

    def get_gateway_ip(self) -> str | None:
        try:
            result = subprocess.run(
                ["ip", "route"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if line.startswith("default"):
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Gateway-Erkennung fehlgeschlagen: %s", e)
        return None
