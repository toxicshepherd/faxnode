"""FaxNode – SSL-Zertifikat-Generierung (plattformuebergreifend).

Ersetzt generate-certs.sh durch reines Python mit dem cryptography-Modul.
Kann auf Linux und Windows ohne externes OpenSSL genutzt werden.
"""
import datetime
import ipaddress
import os
import socket
import stat
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _get_local_ip() -> str:
    """Lokale IP-Adresse ermitteln."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_ca(cert_dir: str) -> tuple[str, str]:
    """CA-Key + CA-Zertifikat generieren. Gibt (ca_cert_path, ca_key_path) zurueck."""
    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_key_path = cert_dir / "ca.key"
    ca_cert_path = cert_dir / "ca.crt"

    # CA Key (RSA 4096)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ca_key_pem = ca_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    ca_key_path.write_bytes(ca_key_pem)

    # CA Zertifikat (10 Jahre)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "FaxNode CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FaxNode"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    # Berechtigungen (nur auf Unix)
    if sys.platform != "win32":
        os.chmod(ca_key_path, stat.S_IRUSR | stat.S_IWUSR)
        os.chmod(ca_cert_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return str(ca_cert_path), str(ca_key_path)


def generate_server_cert(cert_dir: str) -> tuple[str, str]:
    """Server-Key + Server-Zertifikat generieren, signiert von CA.
    Gibt (server_cert_path, server_key_path) zurueck.
    """
    cert_dir = Path(cert_dir)
    ca_key_path = cert_dir / "ca.key"
    ca_cert_path = cert_dir / "ca.crt"

    if not ca_key_path.exists() or not ca_cert_path.exists():
        raise FileNotFoundError("CA-Zertifikat nicht vorhanden. Zuerst generate_ca() aufrufen.")

    # CA laden
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())

    # Server Key (RSA 2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key_path = cert_dir / "server.key"
    server_key_path.write_bytes(server_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

    # SAN (Subject Alternative Names)
    local_ip = _get_local_ip()
    hostname = socket.gethostname()
    san_names = [
        x509.IPAddress(ipaddress.IPv4Address(local_ip)),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.DNSName(hostname),
        x509.DNSName("localhost"),
        x509.DNSName("faxnode.local"),
    ]

    # Server-Zertifikat (10 Jahre, signiert von CA)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FaxNode")]))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_cert_path = cert_dir / "server.crt"
    server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    # Berechtigungen (nur auf Unix)
    if sys.platform != "win32":
        os.chmod(server_key_path, stat.S_IRUSR | stat.S_IWUSR)
        os.chmod(server_cert_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return str(server_cert_path), str(server_key_path)


def ensure_certs(cert_dir: str):
    """Zertifikate generieren falls noch nicht vorhanden."""
    cert_dir = Path(cert_dir)
    ca_exists = (cert_dir / "ca.key").exists() and (cert_dir / "ca.crt").exists()
    server_exists = (cert_dir / "server.key").exists() and (cert_dir / "server.crt").exists()

    if not ca_exists:
        print(f"CA wird erstellt in {cert_dir}...")
        generate_ca(str(cert_dir))
        print("CA erstellt.")

    if not server_exists:
        local_ip = _get_local_ip()
        print(f"Server-Zertifikat wird erstellt fuer {local_ip} ({socket.gethostname()})...")
        generate_server_cert(str(cert_dir))
        print("Server-Zertifikat erstellt.")

    if ca_exists and server_exists:
        print("Zertifikate bereits vorhanden.")


if __name__ == "__main__":
    # Aufruf: python -m compat.certs [cert_dir]
    import config
    cert_dir = sys.argv[1] if len(sys.argv) > 1 else config.CERT_DIR
    ensure_certs(cert_dir)
