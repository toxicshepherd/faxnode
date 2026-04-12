#!/bin/bash
# FaxNode – Privilegierte Setup-Operationen
# Wird via sudoers ohne Passwort aufrufbar gemacht.
set -e

CMD="$1"
shift

case "$CMD" in
    write-creds)
        # Argumente: USERNAME PASSWORD
        USERNAME="$1"
        PASSWORD="$2"
        mkdir -p /etc/samba
        cat > /etc/samba/fax_creds <<EOF
username=$USERNAME
password=$PASSWORD
EOF
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
        echo "$SMB_PATH $MOUNT_POINT cifs credentials=/etc/samba/fax_creds,uid=$(id -u "$SUDO_USER"),gid=$(id -g "$SUDO_USER"),noperm,vers=1.0,_netdev 0 0" >> /etc/fstab
        echo "OK"
        ;;

    mount)
        MOUNT_POINT="$1"
        mkdir -p "$MOUNT_POINT"
        # Erst unmounten falls schon gemountet
        umount -l "$MOUNT_POINT" 2>/dev/null || true
        systemctl daemon-reload
        mount "$MOUNT_POINT"
        echo "OK"
        ;;

    umount)
        MOUNT_POINT="$1"
        umount -l "$MOUNT_POINT" 2>/dev/null || true
        echo "OK"
        ;;

    *)
        echo "Unbekannter Befehl: $CMD" >&2
        exit 1
        ;;
esac
