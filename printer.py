"""FaxNode – CUPS Drucker-Integration."""
import logging

logger = logging.getLogger(__name__)


def get_printers() -> dict:
    """Verfuegbare CUPS-Drucker auflisten."""
    import cups
    conn = cups.Connection()
    return conn.getPrinters()


def print_fax(file_path: str, printer_name: str, copies: int = 1):
    """PDF an einen CUPS-Drucker senden."""
    import cups
    conn = cups.Connection()
    printers = conn.getPrinters()
    if printer_name not in printers:
        raise ValueError(f"Drucker '{printer_name}' nicht gefunden")
    job_id = conn.printFile(printer_name, file_path, "FaxNode", {"copies": str(copies)})
    logger.info("Druckauftrag %d: %s -> %s (%d Kopien)", job_id, file_path, printer_name, copies)
    return job_id
