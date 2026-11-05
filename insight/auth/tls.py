"""TLS certificate management: self-signed on first run, replaceable by an engineer."""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
import ssl
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


class CertificateError(ValueError):
    pass


def cert_paths(data_dir: Path) -> tuple[Path, Path]:
    tls_dir = data_dir / "tls"
    return tls_dir / "cert.pem", tls_dir / "key.pem"


def ensure_certificate(data_dir: Path) -> tuple[Path, Path]:
    cert_path, key_path = cert_paths(data_dir)
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    cert_pem, key_pem = generate_self_signed(socket.gethostname())
    _write_pair(cert_path, key_path, cert_pem, key_pem)
    return cert_path, key_path


def generate_self_signed(hostname: str) -> tuple[bytes, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, hostname or "insight"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "50N Systems Insight"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    alt_names: list[x509.GeneralName] = [
        x509.DNSName(hostname or "insight"),
        x509.DNSName("insight"),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def validate_pair(cert_pem: bytes, key_pem: bytes) -> None:
    """Raise CertificateError unless the certificate and key load and match."""
    with tempfile.TemporaryDirectory() as tmp:
        cert_file, key_file = Path(tmp) / "c.pem", Path(tmp) / "k.pem"
        cert_file.write_bytes(cert_pem)
        key_file.write_bytes(key_pem)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            context.load_cert_chain(cert_file, key_file)
        except (ssl.SSLError, ValueError) as exc:
            raise CertificateError(
                "The certificate and private key do not form a valid pair."
            ) from exc


def install_certificate(data_dir: Path, cert_pem: bytes, key_pem: bytes) -> tuple[Path, Path]:
    validate_pair(cert_pem, key_pem)
    cert_path, key_path = cert_paths(data_dir)
    _write_pair(cert_path, key_path, cert_pem, key_pem)
    return cert_path, key_path


def certificate_summary(cert_path: Path) -> dict[str, str]:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "expires": cert.not_valid_after_utc.strftime("%d %b %Y"),
        "self_signed": "yes" if cert.subject == cert.issuer else "no",
    }


def _write_pair(cert_path: Path, key_path: Path, cert_pem: bytes, key_pem: bytes) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert_pem)
    tmp_key = key_path.with_suffix(".tmp")
    fd = os.open(tmp_key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key_pem)
    tmp_key.replace(key_path)
