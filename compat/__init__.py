"""FaxNode – Plattform-Abstraktionsschicht.

Erkennt automatisch das Betriebssystem und stellt die passenden
Service-Implementierungen bereit.
"""
import sys
import threading

_printer_service = None
_nas_service = None
_network_service = None
_lock = threading.Lock()

IS_WINDOWS = sys.platform == "win32"


def get_printer_service():
    """Drucker-Service fuer die aktuelle Plattform."""
    global _printer_service
    if _printer_service is None:
        with _lock:
            if _printer_service is None:
                if IS_WINDOWS:
                    from compat.windows import WindowsPrinterService
                    _printer_service = WindowsPrinterService()
                else:
                    from compat.linux import LinuxPrinterService
                    _printer_service = LinuxPrinterService()
    return _printer_service


def get_nas_service():
    """NAS/SMB-Service fuer die aktuelle Plattform."""
    global _nas_service
    if _nas_service is None:
        with _lock:
            if _nas_service is None:
                if IS_WINDOWS:
                    from compat.windows import WindowsNasService
                    _nas_service = WindowsNasService()
                else:
                    from compat.linux import LinuxNasService
                    _nas_service = LinuxNasService()
    return _nas_service


def get_network_service():
    """Netzwerk-Service fuer die aktuelle Plattform."""
    global _network_service
    if _network_service is None:
        with _lock:
            if _network_service is None:
                if IS_WINDOWS:
                    from compat.windows import WindowsNetworkService
                    _network_service = WindowsNetworkService()
                else:
                    from compat.linux import LinuxNetworkService
                    _network_service = LinuxNetworkService()
    return _network_service
