#!/bin/bash
# FaxNode – Privilegierte Setup-Operationen
# Wird via sudoers ohne Passwort aufrufbar gemacht.
set -e

CMD="$1"
shift

case "$CMD" in
    write-creds)
        # Credentials werden per stdin gelesen (nicht als Argument, sonst im Journal sichtbar)
        mkdir -p /etc/samba
        cat > /etc/samba/fax_creds
        chmod 600 /etc/samba/fax_creds
        echo "OK"
        ;;

    add-fstab)
        # Argumente: SMB_PATH MOUNT_POINT
        SMB_PATH="$1"
        MOUNT_POINT="$2"
        # Alte FaxNode-Eintraege entfernen
        sed -i '\|'"$MOUNT_POINT"'|d' /etc/fstab
        # Neuen Eintrag hinzufuegen
        echo "$SMB_PATH $MOUNT_POINT cifs credentials=/etc/samba/fax_creds,uid=$(id -u "$SUDO_USER"),gid=$(id -g "$SUDO_USER"),noserverino,noperm,_netdev 0 0" >> /etc/fstab
        echo "OK"
        ;;

    mount)
        MOUNT_POINT="$1"
        mkdir -p "$MOUNT_POINT"
        # Erst unmounten falls schon gemountet (force + lazy fuer stale mounts)
        umount -f -l "$MOUNT_POINT" 2>/dev/null || true
        sleep 1
        systemctl daemon-reload
        mount "$MOUNT_POINT"
        echo "OK"
        ;;

    umount)
        MOUNT_POINT="$1"
        umount -l "$MOUNT_POINT" 2>/dev/null || true
        echo "OK"
        ;;

    discover-printers)
        # Netzwerkdrucker via CUPS/lpinfo suchen
        if command -v lpinfo &>/dev/null; then
            lpinfo --timeout 10 -v 2>/dev/null | grep -E "^(network|socket|ipp|ipps)" || true
        fi
        echo "---END---"
        ;;

    add-printer)
        # Argumente: NAME URI DRIVER
        PNAME="$1"
        URI="$2"
        DRIVER="${3:-everywhere}"
        # Drucker hinzufuegen
        if [ "$DRIVER" = "everywhere" ]; then
            lpadmin -p "$PNAME" -v "$URI" -m everywhere -E 2>&1
        else
            lpadmin -p "$PNAME" -v "$URI" -m "$DRIVER" -E 2>&1
        fi
        # Aktivieren + als Standard-Optionen setzen
        cupsenable "$PNAME" 2>/dev/null || true
        cupsaccept "$PNAME" 2>/dev/null || true
        echo "OK"
        ;;

    remove-printer)
        # Argument: PRINTER_NAME
        PNAME="$1"
        if [ -z "$PNAME" ]; then
            echo "Druckername erforderlich" >&2
            exit 1
        fi
        lpadmin -x "$PNAME" 2>&1
        echo "OK"
        ;;

    test-printer)
        # Argument: PRINTER_NAME — Testseite drucken
        PNAME="$1"
        if [ -z "$PNAME" ]; then
            echo "Druckername erforderlich" >&2
            exit 1
        fi
        lp -d "$PNAME" /usr/share/cups/data/testprint 2>&1
        echo "OK"
        ;;

    *)
        echo "Unbekannter Befehl: $CMD" >&2
        exit 1
        ;;
esac
