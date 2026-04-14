"""FaxNode – Abstrakte Basisklassen fuer plattformspezifische Services."""
from abc import ABC, abstractmethod


class PrinterService(ABC):
    """Drucker-Verwaltung (CUPS auf Linux, win32print + SumatraPDF auf Windows)."""

    @abstractmethod
    def get_printers(self) -> dict:
        """Eingerichtete Drucker auflisten. Gibt {name: info_dict, ...} zurueck."""

    @abstractmethod
    def print_file(self, file_path: str, printer_name: str, copies: int = 1) -> int:
        """PDF an Drucker senden. Gibt Job-ID zurueck."""

    @abstractmethod
    def discover_printers(self) -> list[dict]:
        """Netzwerkdrucker suchen. Gibt [{"uri": ..., "name": ...}, ...] zurueck."""

    @abstractmethod
    def add_printer(self, name: str, uri: str) -> tuple[bool, str]:
        """Drucker einrichten. Gibt (ok, error_or_name) zurueck."""

    @abstractmethod
    def remove_printer(self, name: str) -> tuple[bool, str]:
        """Drucker entfernen. Gibt (ok, error_msg) zurueck."""

    @abstractmethod
    def test_printer(self, name: str) -> tuple[bool, str]:
        """Testseite drucken. Gibt (ok, error_msg) zurueck."""


class NasService(ABC):
    """NAS/SMB-Zugriff (mount auf Linux, UNC-Pfade auf Windows)."""

    @abstractmethod
    def scan_network_for_smb(self) -> list[dict]:
        """Netzwerk nach SMB-Hosts scannen. Gibt [{"ip": ..., "is_gateway": bool}, ...] zurueck."""

    @abstractmethod
    def list_shares(self, ip: str, username: str, password: str) -> list[dict]:
        """SMB-Freigaben auflisten. Gibt [{"name": ..., "comment": ...}, ...] zurueck."""

    @abstractmethod
    def browse_share(self, ip: str, share: str, path: str,
                     username: str, password: str) -> dict:
        """Verzeichnisse in Share durchsuchen. Gibt {"dirs": [...], "pdf_count": int} zurueck."""

    @abstractmethod
    def connect_nas(self, ip: str, share: str, path: str,
                    username: str, password: str) -> dict:
        """NAS-Verbindung einrichten. Gibt {"ok": bool, "fax_dir": str, "pdf_count": int, ...} zurueck."""


class NetworkService(ABC):
    """Netzwerk-Hilfsfunktionen."""

    @abstractmethod
    def get_gateway_ip(self) -> str | None:
        """Standard-Gateway-IP ermitteln."""

    def check_port(self, ip: str, port: int, timeout: int = 3) -> bool:
        """Port-Erreichbarkeit testen (plattformneutral)."""
        import socket
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False
