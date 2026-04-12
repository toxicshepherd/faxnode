#!/bin/bash
# FaxNode – Installations-Script fuer Raspberry Pi
set -e

echo "=== FaxNode Installation ==="

# System-Pakete
echo "[1/6] System-Pakete installieren..."
sudo apt-get update
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-deu \
    poppler-utils \
    libcups2-dev \
    cifs-utils

# Benutzer anlegen
echo "[2/6] Benutzer 'faxnode' anlegen..."
if ! id -u faxnode &>/dev/null; then
    sudo useradd -r -s /bin/false -m -d /opt/faxnode faxnode
fi

# Dateien kopieren
echo "[3/6] Dateien nach /opt/faxnode kopieren..."
sudo mkdir -p /opt/faxnode/data
sudo cp -r ./*.py ./requirements.txt ./static ./templates /opt/faxnode/
sudo cp .env.example /opt/faxnode/.env

# Python venv + Dependencies
echo "[4/6] Python-Umgebung einrichten..."
sudo python3 -m venv /opt/faxnode/venv
sudo /opt/faxnode/venv/bin/pip install --upgrade pip
sudo /opt/faxnode/venv/bin/pip install -r /opt/faxnode/requirements.txt

# NAS-Mount vorbereiten
echo "[5/6] NAS-Mount vorbereiten..."
sudo mkdir -p /mnt/nas/faxe
echo ""
echo "  WICHTIG: NAS-Mount manuell konfigurieren!"
echo "  1. Erstelle /etc/samba/fax_creds mit:"
echo "     username=DEIN_NAS_USER"
echo "     password=DEIN_NAS_PASSWORT"
echo ""
echo "  2. Fuege folgende Zeile zu /etc/fstab hinzu:"
echo "     //NAS-IP/fax-share /mnt/nas/faxe cifs credentials=/etc/samba/fax_creds,uid=faxnode,gid=faxnode,iocharset=utf8,_netdev 0 0"
echo ""
echo "  3. Mounte mit: sudo mount -a"
echo ""

# Berechtigungen + .env anpassen
sudo chown -R faxnode:faxnode /opt/faxnode
echo "  Passe /opt/faxnode/.env an (FAX_WATCH_DIR, SECRET_KEY)!"

# systemd Service
echo "[6/6] systemd Service einrichten..."
sudo cp faxnode.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable faxnode.service

echo ""
echo "=== Installation abgeschlossen ==="
echo ""
echo "Naechste Schritte:"
echo "  1. /opt/faxnode/.env anpassen"
echo "  2. NAS-Mount konfigurieren (siehe oben)"
echo "  3. sudo systemctl start faxnode"
echo "  4. Im Browser oeffnen: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
