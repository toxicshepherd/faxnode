"""FaxNode – WSGI Entry Point.

Gunicorn auf Linux, Waitress auf Windows.
"""
import sys

# gevent-Monkey-Patching als ALLERERSTES, noch vor dem App-Import.
# Gunicorn's gevent-Worker patched zwar selbst, aber nur nach Fork —
# wenn eine Modul-Level-Initialisierung in app.py (z.B. das
# Discovery-Thread-Start) blockierendes I/O macht, wuerde der
# Event-Loop stehen. Defensiv & idempotent: wenn gevent nicht
# installiert ist (z.B. Windows), still skippen.
if sys.platform != "win32":
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        pass

from app import app

if __name__ == "__main__":
    if sys.platform == "win32":
        import config
        from pathlib import Path

        # SSL-Kontext
        cert_dir = Path(config.CERT_DIR)
        cert_file = cert_dir / "server.crt"
        key_file = cert_dir / "server.key"

        if cert_file.exists() and key_file.exists():
            # Waitress unterstuetzt kein natives SSL — Werkzeug-Fallback
            app.run(
                host=config.HOST, port=config.PORT,
                debug=False, threaded=True,
                ssl_context=(str(cert_file), str(key_file)),
            )
        else:
            from waitress import serve
            serve(app, host=config.HOST, port=config.PORT, threads=4)
    else:
        # Linux: normalerweise via Gunicorn gestartet (siehe faxnode.service)
        # Fallback fuer direkten Start:
        import config
        app.run(host=config.HOST, port=config.PORT, debug=False)
