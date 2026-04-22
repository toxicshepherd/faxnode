"""FaxNode – Discord-Webhook-Benachrichtigungen.

Laeuft in einem eigenen Hintergrund-Thread mit Queue. send_discord() ist
non-blocking: wenn die Queue voll ist oder kein Webhook konfiguriert ist,
wird die Nachricht verworfen — kein Einfluss auf den ausloesenden Request.
"""
import json
import logging
import queue
import socket
import threading
import time
import urllib.error
import urllib.request

import config

logger = logging.getLogger(__name__)

_QUEUE_MAX = 200
_q: "queue.Queue[dict]" = queue.Queue(maxsize=_QUEUE_MAX)
_worker_started = False
_worker_lock = threading.Lock()

LEVEL_COLORS = {
    "info": 0x3498DB,     # blau
    "success": 0x2ECC71,  # gruen
    "warning": 0xF1C40F,  # gelb
    "error": 0xE74C3C,    # rot
}


def _is_valid_webhook(url: str) -> bool:
    if not url:
        return False
    return url.startswith("https://discord.com/api/webhooks/") or \
           url.startswith("https://discordapp.com/api/webhooks/") or \
           url.startswith("https://canary.discord.com/api/webhooks/") or \
           url.startswith("https://ptb.discord.com/api/webhooks/")


def send_discord(title: str, message: str, level: str = "info") -> None:
    """Discord-Benachrichtigung in die Queue stellen. Non-blocking."""
    url = getattr(config, "DISCORD_WEBHOOK_URL", "") or ""
    if not _is_valid_webhook(url):
        return
    try:
        _q.put_nowait({"title": title, "message": message, "level": level, "url": url})
    except queue.Full:
        logger.debug("Discord-Queue voll, Nachricht verworfen")


def send_discord_sync(title: str, message: str, level: str = "info", url: str | None = None) -> tuple[bool, str]:
    """Synchron senden — nur fuer Test-Button in den Settings verwenden."""
    target = url if url is not None else getattr(config, "DISCORD_WEBHOOK_URL", "")
    if not _is_valid_webhook(target):
        return False, "Ungueltige Webhook-URL"
    payload = _build_payload(title, message, level)
    try:
        _post(target, payload)
        return True, "Gesendet"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout) as e:
        return False, f"Netzwerk-Fehler: {e}"
    except Exception as e:
        logger.warning("Discord-Test fehlgeschlagen: %s", e)
        return False, "Fehler"


def _build_payload(title: str, message: str, level: str) -> dict:
    color = LEVEL_COLORS.get(level, LEVEL_COLORS["info"])
    return {
        "username": "FaxNode",
        "embeds": [{
            "title": title[:256],
            "description": message[:4000],
            "color": color,
        }],
    }


def _post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    # Discord/Cloudflare blockiert den Default-UA "Python-urllib/x.y" mit 403.
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "FaxNode/1.1 (+https://github.com/toxicshepherd/faxnode)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _worker_loop() -> None:
    while True:
        item = _q.get()
        payload = _build_payload(item["title"], item["message"], item["level"])
        try:
            _post(item["url"], payload)
        except urllib.error.HTTPError as e:
            # Discord-Rate-Limit: Retry-After respektieren und
            # den Job erneut zustellen.
            if e.code == 429:
                retry_after = 1.0
                try:
                    retry_after = float(e.headers.get("Retry-After", "1"))
                except (TypeError, ValueError):
                    pass
                retry_after = max(0.5, min(retry_after, 60.0))
                logger.warning("Discord Rate-Limit, warte %.1fs", retry_after)
                time.sleep(retry_after)
                try:
                    _post(item["url"], payload)
                except Exception as e2:
                    logger.warning("Discord-Retry fehlgeschlagen: %s", e2)
            else:
                logger.warning("Discord-Webhook HTTP %s: %s", e.code, e)
        except Exception as e:
            logger.warning("Discord-Webhook fehlgeschlagen: %s", e)


def start_worker() -> None:
    """Hintergrund-Thread starten (idempotent)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, daemon=True, name="discord-notify").start()
    logger.info("Discord-Notify-Worker gestartet")
