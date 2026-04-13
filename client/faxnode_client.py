"""FaxNode Client – Windows-Anwendung mit eingebettetem Web-Panel."""
import ctypes
import json
import os
import ssl
import subprocess
import sys
import threading
import urllib.request

APP_NAME = "FaxNode"
VERSION = "1.1.0"

# Konfigurationsverzeichnis: %APPDATA%/FaxNode/
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CA_CERT_FILE = os.path.join(CONFIG_DIR, "faxnode-ca.crt")


# --- Hilfsfunktionen ---

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
    """CA-Zertifikat vom FaxNode-Server herunterladen."""
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


def get_panel_url(host, port):
    return f"https://{host}:{port}"


# --- Setup-Fenster (tkinter, nur beim ersten Start) ---

def run_setup(existing_config=None):
    """Zeigt das Setup-Fenster und gibt (host, port) zurueck oder None bei Abbruch."""
    import tkinter as tk

    result = {}

    def on_connect():
        host = host_var.get().strip()
        port = port_var.get().strip()
        if not host:
            status_var.set("Bitte Server-Adresse eingeben.")
            status_label.configure(fg="#f7768e")
            return
        try:
            port_int = int(port)
        except ValueError:
            status_var.set("Ungueltiger Port.")
            status_label.configure(fg="#f7768e")
            return

        connect_btn.configure(state="disabled", text="Verbinde...")
        root.update_idletasks()

        try:
            # 1. Verbindung testen
            status_var.set("Verbindung wird getestet...")
            status_label.configure(fg="#565f89")
            root.update_idletasks()
            if not test_connection(host, port_int):
                status_var.set(f"Server nicht erreichbar: {host}:{port}")
                status_label.configure(fg="#f7768e")
                return

            # 2. Admin-Rechte pruefen
            if not is_admin():
                status_var.set("Administrator-Rechte benoetigt...")
                root.update_idletasks()
                save_config(host, port_int)
                relaunch_as_admin()
                return

            # 3. CA-Zertifikat herunterladen + installieren
            status_var.set("Zertifikat wird installiert...")
            root.update_idletasks()
            cert_data = download_ca_cert(host, port_int)
            if not cert_data or not install_ca_cert(cert_data):
                status_var.set("Zertifikat konnte nicht installiert werden.")
                status_label.configure(fg="#f7768e")
                return

            # 4. Config speichern
            save_config(host, port_int)
            result["host"] = host
            result["port"] = port_int
            root.destroy()

        except Exception as e:
            status_var.set(f"Fehler: {e}")
            status_label.configure(fg="#f7768e")
        finally:
            try:
                connect_btn.configure(state="normal", text="Verbinden")
            except tk.TclError:
                pass

    root = tk.Tk()
    root.title(f"{APP_NAME} — Einrichtung")
    root.resizable(False, False)
    root.configure(bg="#1a1b26")
    root.protocol("WM_DELETE_WINDOW", lambda: (result.clear(), root.destroy()))

    w, h = 420, 340
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    bg = "#1a1b26"
    fg = "#c0caf5"
    accent = "#39d353"
    input_bg = "#24283b"
    muted = "#565f89"

    header = tk.Frame(root, bg=bg)
    header.pack(fill="x", padx=30, pady=(25, 5))
    tk.Label(header, text="\u26C2", font=("Segoe UI", 20), bg=bg, fg=accent).pack(side="left")
    tk.Label(header, text=" FaxNode", font=("Segoe UI", 18, "bold"), bg=bg, fg=fg).pack(side="left")
    tk.Label(root, text="Client-Einrichtung", font=("Segoe UI", 10),
             bg=bg, fg=muted).pack(anchor="w", padx=32, pady=(0, 15))

    form = tk.Frame(root, bg=bg)
    form.pack(fill="x", padx=30)

    tk.Label(form, text="Server-Adresse (IP)", font=("Segoe UI", 9), bg=bg, fg=muted).pack(anchor="w")
    host_var = tk.StringVar(value=existing_config["host"] if existing_config else "192.168.178.")
    tk.Entry(form, textvariable=host_var, font=("Consolas", 11),
             bg=input_bg, fg=fg, insertbackground=fg, relief="flat", bd=0,
             highlightthickness=1, highlightbackground="#414868",
             highlightcolor=accent).pack(fill="x", ipady=6, pady=(2, 10))

    tk.Label(form, text="Port", font=("Segoe UI", 9), bg=bg, fg=muted).pack(anchor="w")
    port_var = tk.StringVar(value=str(existing_config["port"]) if existing_config else "5000")
    tk.Entry(form, textvariable=port_var, font=("Consolas", 11),
             bg=input_bg, fg=fg, insertbackground=fg, relief="flat", bd=0,
             highlightthickness=1, highlightbackground="#414868",
             highlightcolor=accent).pack(fill="x", ipady=6, pady=(2, 15))

    connect_btn = tk.Button(form, text="Verbinden", font=("Segoe UI", 10, "bold"),
                            bg=accent, fg="#1a1b26", activebackground="#2ea043",
                            relief="flat", bd=0, cursor="hand2", command=on_connect)
    connect_btn.pack(fill="x", ipady=8, pady=(0, 10))

    status_var = tk.StringVar(value="Bereit.")
    status_label = tk.Label(root, textvariable=status_var, font=("Segoe UI", 9),
                            bg=bg, fg=muted, wraplength=360)
    status_label.pack(anchor="w", padx=32, pady=(0, 10))

    root.mainloop()
    return result if result else None


# --- Hauptfenster (pywebview) ---

def run_panel(host, port):
    """FaxNode-Panel als natives Fenster mit eingebettetem WebView oeffnen."""
    import webview

    url = get_panel_url(host, port)

    window = webview.create_window(
        "FaxNode",
        url=url,
        width=1100,
        height=750,
        min_size=(800, 500),
        text_select=True,
        background_color="#1a1b26",
    )

    # Unread-Counter im Fenstertitel aktualisieren
    def update_title():
        import time
        while not window._closed:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(f"{url}/api/unread")
                with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                    data = json.loads(resp.read())
                    count = data.get("count", 0)
                    if count > 0:
                        window.set_title(f"({count}) FaxNode")
                    else:
                        window.set_title("FaxNode")
            except Exception:
                pass
            time.sleep(15)

    def on_loaded():
        t = threading.Thread(target=update_title, daemon=True)
        t.start()

    window.events.loaded += on_loaded

    webview.start(
        private_mode=False,
        storage_path=CONFIG_DIR,
    )


# --- Einstiegspunkt ---

def main():
    config = load_config()

    # Bereits eingerichtet und Zertifikat vorhanden?
    if config and os.path.exists(CA_CERT_FILE):
        host = config["host"]
        port = config["port"]
        if test_connection(host, port):
            run_panel(host, port)
            return
        # Server nicht erreichbar — Setup zeigen mit bestehender Config
        result = run_setup(existing_config=config)
    else:
        result = run_setup()

    if result:
        run_panel(result["host"], result["port"])


if __name__ == "__main__":
    main()
