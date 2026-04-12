"""FaxNode – OCR Worker (Tesseract)."""
import queue
import threading
import logging

import config
import db

logger = logging.getLogger(__name__)

ocr_queue = queue.Queue()
_broadcast = None


def _ocr_worker():
    """Background-Thread: PDFs mit Tesseract verarbeiten."""
    while True:
        fax_id = ocr_queue.get()
        try:
            fax = db.get_fax(fax_id)
            if not fax or fax["ocr_done"] != 0:
                continue

            file_path = fax["file_path"]
            logger.info("OCR starten: Fax %d (%s)", fax_id, fax["filename"])

            # PDF -> Bilder -> Text
            from pdf2image import convert_from_path
            import pytesseract

            images = convert_from_path(file_path, dpi=200)
            texts = []
            for i, image in enumerate(images):
                text = pytesseract.image_to_string(image, lang=config.OCR_LANGUAGE)
                texts.append(text.strip())
                logger.debug("OCR Seite %d/%d fertig", i + 1, len(images))

            full_text = "\n\n".join(texts)
            page_count = len(images)

            # DB Update
            db.update_fax_ocr(fax_id, full_text, ocr_done=1)
            with db.db_connection() as conn:
                conn.execute(
                    "UPDATE faxes SET page_count = ? WHERE id = ?",
                    (page_count, fax_id)
                )

            logger.info("OCR fertig: Fax %d (%d Seiten, %d Zeichen)",
                        fax_id, page_count, len(full_text))

            # SSE broadcast
            if _broadcast:
                _broadcast("ocr_complete", {
                    "fax_id": fax_id,
                    "page_count": page_count,
                    "text_length": len(full_text),
                })

        except Exception as e:
            logger.error("OCR Fehler bei Fax %d: %s", fax_id, e)
            try:
                db.update_fax_ocr(fax_id, None, ocr_done=-1)
            except Exception:
                pass

        finally:
            ocr_queue.task_done()


def start_ocr_worker(broadcast_fn):
    """OCR Worker Thread starten."""
    global _broadcast
    _broadcast = broadcast_fn

    worker = threading.Thread(target=_ocr_worker, daemon=True, name="ocr-worker")
    worker.start()
    logger.info("OCR Worker gestartet")
