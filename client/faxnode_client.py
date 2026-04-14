"""FaxNode Client – Windows-Anwendung mit Auto-Discovery und eingebettetem Web-Panel."""
import ctypes
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import urllib.request

APP_NAME = "FaxNode"
VERSION = "2.1.0"
DISCOVERY_PORT = 9742  # Fester Discovery-Port

# Konfigurationsverzeichnis: %APPDATA%/FaxNode/
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CA_CERT_FILE = os.path.join(CONFIG_DIR, "faxnode-ca.crt")


# --- Hilfsfunktionen ---

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    params = " ".join(f'"{a}"' for a in sys.argv)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception:
        pass
    sys.exit(0)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_config(host, port):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"host": host, "port": port, "version": VERSION}, f, indent=2)


def discover_server(timeout=4):
    """FaxNode-Server im Netzwerk per UDP-Broadcast finden."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(b"FAXNODE_DISCOVER", ("255.255.255.255", DISCOVERY_PORT))
        data, addr = sock.recvfrom(1024)
        info = json.loads(data.decode())
        return {
            "host": addr[0],
            "port": info.get("port", 9741),
            "hostname": info.get("hostname", ""),
        }
    except socket.timeout:
        return None
    except Exception:
        return None
    finally:
        sock.close()


def download_ca_cert(host, port):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}/api/ca-cert"
    req = urllib.request.Request(url, headers={"Accept": "application/x-pem-file"})
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return resp.read()


def install_ca_cert(cert_data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CA_CERT_FILE, "wb") as f:
        f.write(cert_data)
    result = subprocess.run(
        ["certutil", "-addstore", "Root", CA_CERT_FILE],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def test_connection(host, port):
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


# --- Setup-Fenster (tkinter) ---

def run_setup(existing_config=None):
    """Setup-Fenster mit Auto-Discovery. Gibt (host, port) zurueck oder None."""
    import tkinter as tk

    result = {}
    found_server = None

    bg = "#1a1b26"
    fg = "#c0caf5"
    accent = "#39d353"
    input_bg = "#24283b"
    muted = "#565f89"
    error_fg = "#f7768e"

    root = tk.Tk()
    root.title(f"{APP_NAME} — Einrichtung")
    root.resizable(False, False)
    root.configure(bg=bg)
    root.protocol("WM_DELETE_WINDOW", lambda: (result.clear(), root.destroy()))

    w, h = 440, 420
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    # --- Header ---
    header = tk.Frame(root, bg=bg)
    header.pack(fill="x", padx=30, pady=(25, 5))
    tk.Label(header, text="\u26C2", font=("Segoe UI", 20), bg=bg, fg=accent).pack(side="left")
    tk.Label(header, text=" FaxNode", font=("Segoe UI", 18, "bold"), bg=bg, fg=fg).pack(side="left")
    tk.Label(root, text="Client-Einrichtung", font=("Segoe UI", 10),
             bg=bg, fg=muted).pack(anchor="w", padx=32, pady=(0, 15))

    # --- Discovery-Bereich ---
    disc_frame = tk.Frame(root, bg=bg)
    disc_frame.pack(fill="x", padx=30, pady=(0, 10))

    disc_status = tk.StringVar(value="Suche FaxNode-Server im Netzwerk...")
    disc_label = tk.Label(disc_frame, textvariable=disc_status, font=("Segoe UI", 9),
                          bg=bg, fg=muted)
    disc_label.pack(anchor="w")

    found_frame = tk.Frame(disc_frame, bg=input_bg, highlightthickness=1,
                           highlightbackground="#414868")
    # Wird erst angezeigt wenn Server gefunden

    found_text = tk.StringVar()
    found_label = tk.Label(found_frame, textvariable=found_text, font=("Consolas", 10),
                           bg=input_bg, fg=fg, padx=10, pady=8)
    found_label.pack(side="left", fill="x", expand=True)

    connect_found_btn = tk.Button(found_frame, text="Verbinden", font=("Segoe UI", 9, "bold"),
                                  bg=accent, fg="#1a1b26", relief="flat", bd=0, padx=12, pady=6,
                                  cursor="hand2")
    connect_found_btn.pack(side="right", padx=(0, 8), pady=6)

    # --- Manuell-Bereich ---
    sep = tk.Frame(root, bg="#414868", height=1)
    sep.pack(fill="x", padx=30, pady=10)

    manual_toggle = tk.Label(root, text="Server nicht gefunden? Manuell eingeben:",
                             font=("Segoe UI", 9), bg=bg, fg=muted, cursor="hand2")
    manual_toggle.pack(anchor="w", padx=32)

    manual_frame = tk.Frame(root, bg=bg)

    tk.Label(manual_frame, text="Server-IP", font=("Segoe UI", 9), bg=bg, fg=muted).pack(anchor="w")
    host_var = tk.StringVar(value=existing_config["host"] if existing_config else "192.168.178.")
    tk.Entry(manual_frame, textvariable=host_var, font=("Consolas", 11),
             bg=input_bg, fg=fg, insertbackground=fg, relief="flat", bd=0,
             highlightthickness=1, highlightbackground="#414868",
             highlightcolor=accent).pack(fill="x", ipady=5, pady=(2, 8))

    tk.Label(manual_frame, text="Port", font=("Segoe UI", 9), bg=bg, fg=muted).pack(anchor="w")
    port_var = tk.StringVar(value=str(existing_config["port"]) if existing_config else "9741")
    tk.Entry(manual_frame, textvariable=port_var, font=("Consolas", 11),
             bg=input_bg, fg=fg, insertbackground=fg, relief="flat", bd=0,
             highlightthickness=1, highlightbackground="#414868",
             highlightcolor=accent).pack(fill="x", ipady=5, pady=(2, 10))

    manual_btn = tk.Button(manual_frame, text="Verbinden", font=("Segoe UI", 10, "bold"),
                           bg=accent, fg="#1a1b26", activebackground="#2ea043",
                           relief="flat", bd=0, cursor="hand2")
    manual_btn.pack(fill="x", ipady=7)

    manual_visible = [False]

    def toggle_manual():
        if manual_visible[0]:
            manual_frame.pack_forget()
        else:
            manual_frame.pack(fill="x", padx=30, pady=(5, 0))
        manual_visible[0] = not manual_visible[0]

    manual_toggle.bind("<Button-1>", lambda e: toggle_manual())

    # --- Status ---
    status_var = tk.StringVar()
    status_label = tk.Label(root, textvariable=status_var, font=("Segoe UI", 9),
                            bg=bg, fg=muted, wraplength=380)
    status_label.pack(anchor="w", padx=32, pady=(10, 5), side="bottom")

    # --- Verbindungslogik ---

    def do_connect(host, port_int):
        status_var.set("Verbindung wird getestet...")
        status_label.configure(fg=muted)
        root.update_idletasks()

        if not test_connection(host, port_int):
            status_var.set(f"Server nicht erreichbar: {host}:{port_int}")
            status_label.configure(fg=error_fg)
            return

        if not is_admin():
            status_var.set("Administrator-Rechte werden benoetigt...")
            root.update_idletasks()
            save_config(host, port_int)
            relaunch_as_admin()
            return

        status_var.set("Zertifikat wird installiert...")
        root.update_idletasks()
        try:
            cert_data = download_ca_cert(host, port_int)
            if not cert_data or not install_ca_cert(cert_data):
                status_var.set("Zertifikat konnte nicht installiert werden.")
                status_label.configure(fg=error_fg)
                return
        except Exception as e:
            status_var.set(f"Fehler: {e}")
            status_label.configure(fg=error_fg)
            return

        save_config(host, port_int)
        result["host"] = host
        result["port"] = port_int
        root.destroy()

    def on_connect_found():
        if found_server:
            do_connect(found_server["host"], found_server["port"])

    def on_connect_manual():
        host = host_var.get().strip()
        try:
            port_int = int(port_var.get().strip())
        except ValueError:
            status_var.set("Ungueltiger Port.")
            status_label.configure(fg=error_fg)
            return
        if not host:
            status_var.set("Bitte IP eingeben.")
            status_label.configure(fg=error_fg)
            return
        do_connect(host, port_int)

    connect_found_btn.configure(command=on_connect_found)
    manual_btn.configure(command=on_connect_manual)

    # --- Auto-Discovery im Hintergrund ---

    def do_discovery():
        nonlocal found_server
        server = discover_server(timeout=4)

        def on_found():
            nonlocal found_server
            found_server = server
            name = server.get("hostname", server["host"])
            found_text.set(f"{name}  ({server['host']}:{server['port']})")
            disc_status.set("FaxNode-Server gefunden:")
            disc_label.configure(fg=accent)
            found_frame.pack(fill="x", pady=(5, 0))

        def on_not_found():
            disc_status.set("Kein Server gefunden. Manuell eingeben:")
            disc_label.configure(fg=error_fg)
            toggle_manual()

        # Tkinter ist nicht thread-safe — Widget-Updates auf Main-Thread planen
        if server:
            root.after(0, on_found)
        else:
            root.after(0, on_not_found)

    threading.Thread(target=do_discovery, daemon=True).start()

    root.mainloop()
    return result if result else None


# --- Hauptfenster (pywebview) ---

def run_panel(host, port):
    """FaxNode-Panel als natives Fenster mit eingebettetem WebView."""
    import webview

    url = f"https://{host}:{port}"

    window = webview.create_window(
        "FaxNode",
        url=url,
        width=1100,
        height=750,
        min_size=(800, 500),
        text_select=True,
        background_color="#1a1b26",
    )

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
                    window.set_title(f"({count}) FaxNode" if count > 0 else "FaxNode")
            except Exception:
                pass
            time.sleep(15)

    def on_loaded():
        threading.Thread(target=update_title, daemon=True).start()

    window.events.loaded += on_loaded

    webview.start(private_mode=False, storage_path=CONFIG_DIR)


# --- Einstiegspunkt ---

def main():
    config = load_config()

    # Bereits eingerichtet?
    if config and os.path.exists(CA_CERT_FILE):
        host = config["host"]
        port = config["port"]
        if test_connection(host, port):
            run_panel(host, port)
            return
        # Server nicht erreichbar — Setup mit bestehender Config
        result = run_setup(existing_config=config)
    else:
        result = run_setup()

    if result:
        run_panel(result["host"], result["port"])


if __name__ == "__main__":
    main()
