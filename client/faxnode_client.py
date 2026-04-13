"""FaxNode Client – Windows-Anwendung fuer Zertifikat-Setup und Panel-Zugriff."""
import ctypes
import json
import os
import ssl
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import messagebox
import urllib.request
import webbrowser

APP_NAME = "FaxNode"
VERSION = "1.0.0"

# Konfigurationsverzeichnis: %APPDATA%/FaxNode/
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CA_CERT_FILE = os.path.join(CONFIG_DIR, "faxnode-ca.crt")


def is_admin():
    """Prueft ob das Programm als Administrator laeuft."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    """Startet das Programm mit Administrator-Rechten neu."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception:
        pass
    sys.exit(0)


def load_config():
    """Gespeicherte Konfiguration laden."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_config(host, port):
    """Konfiguration speichern."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"host": host, "port": port, "version": VERSION}, f, indent=2)


def download_ca_cert(host, port):
    """CA-Zertifikat vom FaxNode-Server herunterladen.

    Verwendet verify=False nur fuer diesen einen Request,
    da das CA-Zertifikat selbst oeffentlich und unkritisch ist.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}/api/ca-cert"
    req = urllib.request.Request(url, headers={"Accept": "application/x-pem-file"})
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return resp.read()


def install_ca_cert(cert_data):
    """CA-Zertifikat im Windows-Zertifikatspeicher installieren."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CA_CERT_FILE, "wb") as f:
        f.write(cert_data)
    result = subprocess.run(
        ["certutil", "-addstore", "Root", CA_CERT_FILE],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def is_cert_installed():
    """Prueft ob das FaxNode CA-Zertifikat bereits installiert ist."""
    result = subprocess.run(
        ["certutil", "-verifystore", "Root", "FaxNode CA"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def test_connection(host, port):
    """Testet die HTTPS-Verbindung zum Server."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = f"https://{host}:{port}/api/unread"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def open_panel(host, port):
    """FaxNode im Standardbrowser oeffnen."""
    webbrowser.open(f"https://{host}:{port}")


class FaxNodeApp:
    """Hauptfenster der FaxNode-Client-Anwendung."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} Client")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1b26")

        # Fenster zentrieren
        w, h = 420, 340
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui()

    def _build_ui(self):
        bg = "#1a1b26"
        fg = "#c0caf5"
        accent = "#39d353"
        input_bg = "#24283b"
        muted = "#565f89"

        # Header
        header = tk.Frame(self.root, bg=bg)
        header.pack(fill="x", padx=30, pady=(25, 5))
        tk.Label(header, text="\u26C2", font=("Segoe UI", 20), bg=bg, fg=accent).pack(side="left")
        tk.Label(header, text=" FaxNode", font=("Segoe UI", 18, "bold"), bg=bg, fg=fg).pack(side="left")

        tk.Label(self.root, text="Client-Einrichtung", font=("Segoe UI", 10),
                 bg=bg, fg=muted).pack(anchor="w", padx=32, pady=(0, 15))

        # Server-Adresse
        form = tk.Frame(self.root, bg=bg)
        form.pack(fill="x", padx=30)

        tk.Label(form, text="Server-Adresse (IP)", font=("Segoe UI", 9),
                 bg=bg, fg=muted).pack(anchor="w")
        self.host_var = tk.StringVar(value="192.168.178.")
        host_entry = tk.Entry(form, textvariable=self.host_var, font=("JetBrains Mono", 11),
                              bg=input_bg, fg=fg, insertbackground=fg,
                              relief="flat", bd=0, highlightthickness=1,
                              highlightbackground="#414868", highlightcolor=accent)
        host_entry.pack(fill="x", ipady=6, pady=(2, 10))

        # Port
        tk.Label(form, text="Port", font=("Segoe UI", 9), bg=bg, fg=muted).pack(anchor="w")
        self.port_var = tk.StringVar(value="5000")
        port_entry = tk.Entry(form, textvariable=self.port_var, font=("JetBrains Mono", 11),
                              bg=input_bg, fg=fg, insertbackground=fg,
                              relief="flat", bd=0, highlightthickness=1,
                              highlightbackground="#414868", highlightcolor=accent)
        port_entry.pack(fill="x", ipady=6, pady=(2, 15))

        # Verbinden-Button
        self.connect_btn = tk.Button(
            form, text="Verbinden", font=("Segoe UI", 10, "bold"),
            bg=accent, fg="#1a1b26", activebackground="#2ea043",
            relief="flat", bd=0, cursor="hand2",
            command=self._on_connect,
        )
        self.connect_btn.pack(fill="x", ipady=8, pady=(0, 10))

        # Status
        self.status_var = tk.StringVar(value="Bereit.")
        self.status_label = tk.Label(
            self.root, textvariable=self.status_var,
            font=("Segoe UI", 9), bg=bg, fg=muted, wraplength=360,
        )
        self.status_label.pack(anchor="w", padx=32, pady=(0, 10))

        # Bestehende Config laden
        config = load_config()
        if config:
            self.host_var.set(config["host"])
            self.port_var.set(str(config["port"]))

    def _set_status(self, text, error=False):
        self.status_var.set(text)
        self.status_label.configure(fg="#f7768e" if error else "#565f89")
        self.root.update_idletasks()

    def _on_connect(self):
        host = self.host_var.get().strip()
        port = self.port_var.get().strip()

        if not host:
            self._set_status("Bitte Server-Adresse eingeben.", error=True)
            return
        try:
            port_int = int(port)
        except ValueError:
            self._set_status("Ungueltiger Port.", error=True)
            return

        self.connect_btn.configure(state="disabled", text="Verbinde...")
        self.root.update_idletasks()

        try:
            # 1. Verbindung testen
            self._set_status("Verbindung wird getestet...")
            if not test_connection(host, port_int):
                self._set_status(f"Server nicht erreichbar: {host}:{port}", error=True)
                return

            # 2. Admin-Rechte pruefen (fuer Zertifikat-Installation)
            if not is_admin():
                self._set_status("Administrator-Rechte werden benoetigt...")
                save_config(host, port_int)  # Config schon mal speichern
                relaunch_as_admin()
                return

            # 3. CA-Zertifikat herunterladen
            self._set_status("CA-Zertifikat wird heruntergeladen...")
            cert_data = download_ca_cert(host, port_int)
            if not cert_data:
                self._set_status("CA-Zertifikat konnte nicht heruntergeladen werden.", error=True)
                return

            # 4. Zertifikat installieren
            self._set_status("Zertifikat wird installiert...")
            if not install_ca_cert(cert_data):
                self._set_status("Zertifikat konnte nicht installiert werden.", error=True)
                return

            # 5. Config speichern
            save_config(host, port_int)

            # 6. Browser oeffnen
            self._set_status("Fertig! Browser wird geoeffnet...")
            open_panel(host, port_int)

            # Kurz warten, dann schliessen
            self.root.after(1500, self.root.destroy)

        except Exception as e:
            self._set_status(f"Fehler: {e}", error=True)
        finally:
            try:
                self.connect_btn.configure(state="normal", text="Verbinden")
            except tk.TclError:
                pass

    def run(self):
        self.root.mainloop()


def main():
    """Haupteinstiegspunkt."""
    config = load_config()

    # Wenn bereits eingerichtet: direkt Browser oeffnen
    if config and os.path.exists(CA_CERT_FILE):
        host = config["host"]
        port = config["port"]
        if test_connection(host, port):
            open_panel(host, port)
            return
        # Server nicht erreichbar — Setup zeigen

    # Setup-Fenster anzeigen
    app = FaxNodeApp()
    app.run()


if __name__ == "__main__":
    main()
