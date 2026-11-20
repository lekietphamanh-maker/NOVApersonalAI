"""A certificate authority that lives only on this PC, so Nova Lite can use HTTPS on the home network.

The user installs its certificate on the phone once. It can only vouch for home-network and Tailscale
addresses (name constraints), so even a stolen key could not impersonate real websites.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ALLOWED_NETWORKS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8")
CA_NAME = "Alfred Local CA (this PC only)"


def folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "tls"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def ensure_ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key_path, cert_path = folder() / "ca.key", folder() / "ca.crt"
    if key_path.is_file() and cert_path.is_file():
        return (serialization.load_pem_private_key(key_path.read_bytes(), password=None),
                x509.load_pem_x509_certificate(cert_path.read_bytes()))
    folder().mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Alfred")])
    permitted = [x509.IPAddress(ipaddress.ip_network(network)) for network in ALLOWED_NETWORKS]
    permitted.append(x509.DNSName("alfred.invalid"))  # constrains DNS names too: no real domain can be signed
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=5))
        .not_valid_after(_now() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_private(key_path, _key_pem(key))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return key, certificate


def ensure_server_certificate(address: str) -> tuple[Path, Path]:
    """A certificate for this PC's current address (renewed when the address changes or it nears expiry)."""
    ca_key, ca_cert = ensure_ca()
    cert_path, key_path = folder() / "server.crt", folder() / "server.key"
    wanted = {ipaddress.ip_address(address), ipaddress.ip_address("127.0.0.1")}
    if cert_path.is_file() and key_path.is_file():
        current = x509.load_pem_x509_certificate(cert_path.read_bytes())
        names = set(current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress))
        if names == wanted and current.not_valid_after_utc - _now() > datetime.timedelta(days=30):
            return cert_path, key_path
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Nova on {address}")]))
        .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=5))
        .not_valid_after(_now() + datetime.timedelta(days=397))  # Apple rejects longer-lived TLS certificates
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip) for ip in sorted(wanted, key=str)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_private(key_path, _key_pem(key))
    # The chain (server, then CA) so phones that have the CA can build the path.
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def ca_certificate_der() -> bytes:
    return ensure_ca()[1].public_bytes(serialization.Encoding.DER)


def ca_fingerprint() -> str:
    digest = ensure_ca()[1].fingerprint(hashes.SHA256()).hex().upper()
    return " ".join(digest[i:i + 4] for i in range(0, 16, 4))
