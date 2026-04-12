"""FaxNode – OCR Worker (Tesseract) + Thumbnail-Generierung."""
import os
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

            # Thumbnail generieren (erste Seite, 200px breit)
            thumbnail_path = _generate_thumbnail(fax_id, images[0])
            if thumbnail_path:
                db.update_fax_thumbnail(fax_id, thumbnail_path)

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


def _generate_thumbnail(fax_id, image):
    """Thumbnail aus der ersten PDF-Seite generieren."""
    try:
        thumb_dir = config.THUMBNAIL_DIR
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, f"{fax_id}.png")
        thumb = image.copy()
        thumb.thumbnail((200, 280))
        thumb.save(thumb_path, "PNG", optimize=True)
        logger.debug("Thumbnail erstellt: %s", thumb_path)
        return thumb_path
    except Exception as e:
        logger.warning("Thumbnail-Generierung fehlgeschlagen: %s", e)
        return None


def start_ocr_worker(broadcast_fn):
    """OCR Worker Thread starten."""
    global _broadcast
    _broadcast = broadcast_fn

    worker = threading.Thread(target=_ocr_worker, daemon=True, name="ocr-worker")
    worker.start()
    logger.info("OCR Worker gestartet")
