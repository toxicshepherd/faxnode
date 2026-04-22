#!/bin/bash
# FaxNode – Installer
# Installiert alles, Konfiguration erfolgt im Browser-Wizard.
set -e

REPO="https://github.com/toxicshepherd/faxnode.git"
INSTALL_DIR="/opt/faxnode"
USER=$(whoami)
PORT=9741

echo ""
echo "  ╔═══════════════════════════╗"
echo "  ║     FaxNode Installer     ║"
echo "  ╚═══════════════════════════╝"
echo ""

# 1. System-Pakete
echo "[1/7] System-Pakete installieren..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-deu \
    poppler-utils \
    libcups2-dev \
    cups \
    cifs-utils \
    smbclient \
    netcat-openbsd \
    openssl \
    git > /dev/null
echo "      Fertig."

# CUPS konfigurieren (Netzwerkdrucker-Erkennung + Fernzugriff)
echo "      CUPS konfigurieren..."
sudo usermod -aG lpadmin "$USER" 2>/dev/null || true
sudo systemctl enable cups -q 2>/dev/null || true
sudo systemctl start cups 2>/dev/null || true

# 2. Repo klonen
echo "[2/7] FaxNode herunterladen..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "      Aktualisiere..."
    sudo git -C "$INSTALL_DIR" pull -q
else
    sudo rm -rf "$INSTALL_DIR"
    sudo git clone -q "$REPO" "$INSTALL_DIR"
fi
sudo chown -R "$USER":"$USER" "$INSTALL_DIR"
echo "      Fertig."

# 3. Python-Umgebung
echo "[3/7] Python-Umgebung einrichten..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements-linux.txt" -q
echo "      Fertig."

# 4. Verzeichnisse
echo "[4/7] Verzeichnisse vorbereiten..."
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/static/thumbnails"
mkdir -p "$INSTALL_DIR/static/sounds"
echo "      Fertig."

# 5. SSL-Zertifikate generieren
echo "[5/7] SSL-Zertifikate generieren..."
chmod +x "$INSTALL_DIR/generate-certs.sh"
bash "$INSTALL_DIR/generate-certs.sh" "$INSTALL_DIR/certs"
echo "      Fertig."

# 6. Sudoers fuer Setup-Helper (NAS-Mount ohne Passwort)
echo "[6/7] Berechtigungen einrichten..."
sudo chmod +x "$INSTALL_DIR/setup-helper.sh"
SUDOERS_LINE="$USER ALL=(ALL) NOPASSWD: $INSTALL_DIR/setup-helper.sh"
SUDOERS_FILE="/etc/sudoers.d/faxnode"
if [ ! -f "$SUDOERS_FILE" ] || ! grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE" 2>/dev/null; then
    echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
fi
echo "      Fertig."

# 7. systemd Service
echo "[7/7] systemd Service einrichten..."
sudo tee /etc/systemd/system/faxnode.service > /dev/null <<EOF
[Unit]
Description=FaxNode – Digitale Faxverwaltung
After=network.target remote-fs.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/gunicorn -k gthread -w 2 --threads 8 -b 0.0.0.0:$PORT --certfile $INSTALL_DIR/certs/server.crt --keyfile $INSTALL_DIR/certs/server.key --timeout 120 wsgi:app
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable faxnode.service -q
sudo systemctl restart faxnode.service
echo "      Fertig."

# Fertig
mapfile -t ALL_IPS < <(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')
echo ""
echo "  ══════════════════════════════════════"
echo "  FaxNode laeuft!"
echo ""
echo "  Oeffne im Browser:"
for ip in "${ALL_IPS[@]}"; do
    echo "  https://$ip:$PORT"
done
echo ""
echo "  Windows-Clients: FaxNode-Setup.exe"
echo "  installieren und starten."
echo "  Der Server wird automatisch gefunden."
echo "  ══════════════════════════════════════"
echo ""
