"""Generate the demo PKI for OPC UA (IEC 62541-6 application instance certificates).

Creates a private CA and one application certificate per component, with the application
URI in the subjectAltName as OPC UA requires. Also creates a ROGUE certificate signed by a
different CA, used by the security tests to prove untrusted clients are rejected.

Output: infra/pki/out/ (gitignored). Never commit keys. Re-run to rotate everything.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
APPS = {  # name: (DNS names, is_server)
    "opcua-server": (["opcua", "localhost"], True),
    "collector": (["collector"], False),
    "twin": (["twin"], False),
    "operator-hmi": (["hmi"], False),
}


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Reference Gas Processing Facility (fictional)"),
        ]
    )


def make_ca(cn: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _key()
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(_name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_app(
    name: str, dns: list[str], server: bool, ca_key: rsa.RSAPrivateKey, ca: x509.Certificate
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _key()
    now = dt.datetime.now(dt.UTC)
    eku = [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH] if server else [ExtendedKeyUsageOID.CLIENT_AUTH]
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(name))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=730))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(f"urn:rgpf:{name}")] + [x509.DNSName(d) for d in dns]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage(eku), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _save(name: str, key: rsa.RSAPrivateKey, cert: x509.Certificate, d: Path) -> None:
    (d / f"{name}.der").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    (d / f"{name}.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    (d / f"{name}.pem").chmod(0o644)  # demo: containers run as a different uid


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trusted").mkdir(exist_ok=True)
    ca_key, ca = make_ca("RGPF Demo OT CA")
    (OUT / "ca.der").write_bytes(ca.public_bytes(serialization.Encoding.DER))
    (OUT / "trusted" / "ca.der").write_bytes(ca.public_bytes(serialization.Encoding.DER))
    for name, (dns, server) in APPS.items():
        key, cert = make_app(name, dns, server, ca_key, ca)
        _save(name, key, cert, OUT)
        if not server:  # server trusts its known clients explicitly (allow-list)
            (OUT / "trusted" / f"{name}.der").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    rogue_ca_key, rogue_ca = make_ca("Rogue CA")
    key, cert = make_app("rogue", ["rogue"], False, rogue_ca_key, rogue_ca)
    _save("rogue", key, cert, OUT)
    print(f"PKI written to {OUT}")


if __name__ == "__main__":
    main()
