#!/bin/bash
# FaxNode – Selbstsignierte CA + Server-Zertifikat generieren
# Wird von install.sh aufgerufen. Kann auch manuell gestartet werden,
# z.B. wenn sich die IP des Pi aendert.
set -e

CERT_DIR="${1:-$(dirname "$0")/certs}"
mkdir -p "$CERT_DIR"

# Lokale IPs und Hostname ermitteln
HOSTNAME=$(hostname)
mapfile -t ALL_IPS < <(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')
IP="${ALL_IPS[0]}"

echo "Zertifikate fuer: ${ALL_IPS[*]} ($HOSTNAME)"

# --- CA generieren (nur beim ersten Mal) ---
if [ ! -f "$CERT_DIR/ca.key" ]; then
    echo "CA wird erstellt..."
    openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
    openssl req -x509 -new -nodes -key "$CERT_DIR/ca.key" \
        -sha256 -days 3650 -out "$CERT_DIR/ca.crt" \
        -subj "/CN=FaxNode CA/O=FaxNode" 2>/dev/null
    echo "CA erstellt: $CERT_DIR/ca.crt"
else
    echo "CA vorhanden, wird wiederverwendet."
fi

# --- Server-Zertifikat generieren (immer neu, fuer aktuelle IP) ---
echo "Server-Zertifikat wird erstellt..."

ALT_IP_LINES=""
idx=1
for ip in "${ALL_IPS[@]}"; do
    ALT_IP_LINES+="IP.${idx} = ${ip}"$'\n'
    idx=$((idx + 1))
done
ALT_IP_LINES+="IP.${idx} = 127.0.0.1"$'\n'

cat > "$CERT_DIR/server.cnf" <<EOF
[req]
default_bits = 2048
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
CN = FaxNode

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
${ALT_IP_LINES}DNS.1 = $HOSTNAME
DNS.2 = localhost
DNS.3 = faxnode.local
EOF

openssl genrsa -out "$CERT_DIR/server.key" 2048 2>/dev/null
openssl req -new -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -config "$CERT_DIR/server.cnf" 2>/dev/null
openssl x509 -req -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/server.crt" \
    -days 3650 -sha256 \
    -extfile "$CERT_DIR/server.cnf" -extensions v3_req 2>/dev/null

# Aufraeumen
rm -f "$CERT_DIR/server.csr" "$CERT_DIR/server.cnf" "$CERT_DIR/ca.srl"

# Berechtigungen
chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"

echo "Server-Zertifikat erstellt fuer IPs=${ALL_IPS[*]}"
echo ""
echo "Dateien:"
echo "  CA:     $CERT_DIR/ca.crt"
echo "  Server: $CERT_DIR/server.crt"
