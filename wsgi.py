"""FaxNode – WSGI Entry Point.

Gunicorn auf Linux, Waitress auf Windows.
"""
import sys
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
        app.run()
