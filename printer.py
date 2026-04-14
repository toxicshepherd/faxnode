"""FaxNode – Drucker-Integration (plattformneutral).

Delegiert an die plattformspezifische Implementierung in compat/.
"""
import logging

from compat import get_printer_service

logger = logging.getLogger(__name__)


def get_printers() -> dict:
    """Verfuegbare Drucker auflisten."""
    return get_printer_service().get_printers()


def print_fax(file_path: str, printer_name: str, copies: int = 1):
    """PDF an einen Drucker senden."""
    return get_printer_service().print_file(file_path, printer_name, copies)
