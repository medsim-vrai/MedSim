#!/usr/bin/env python3
"""Cross-platform dev TLS cert tool for VRAI Faces (macOS / Windows / Linux).

A pure-Python twin of `scripts/make-dev-cert.sh` + `cert-doctor.sh`, using the
already-declared `cryptography` dependency — so a **Windows** host needs no
openssl or bash. It produces the SAME files `run_portal.py` serves:

  portal/data/certs/rootCA.pem      install + trust on each tablet (the ONE CA)
  portal/data/certs/rootCA-key.pem  CA private key (never commit / share)
  portal/data/certs/dev-cert.pem    leaf + CA chain (served by the portal)
  portal/data/certs/dev-key.pem     leaf private key (never commit / share)

The CA is **mint-once** (ADR-0029): an existing rootCA is REUSED and only the
leaf is reissued (e.g. for a new LAN IP), so devices that already trust
rootCA.pem stay trusted. Re-minting requires --remint and re-trust everywhere.

Usage:
  python scripts/dev_cert.py                      # issue/refresh the leaf (reuse CA)
  python scripts/dev_cert.py --host portal.medsim.lan   # add an extra SAN entry
  python scripts/dev_cert.py doctor               # read-only diagnosis
  python scripts/dev_cert.py --remint             # regenerate the CA (re-trust ALL devices!)

Trust the CA after generating (a system-security step you run yourself):
  macOS    sudo scripts/trust-ca-mac.sh
  Windows  pwsh -File scripts/trust-ca-windows.ps1   (Run as Administrator)
  tablet   open https://<host>:8760/rootca.pem and install it as a CA certificate
"""
from __future__ import annotations

import argparse
import datetime as _dt
import ipaddress
import os
import platform
import socket
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
except ModuleNotFoundError:  # pragma: no cover - environment guard
    sys.exit(
        "dev_cert.py needs the 'cryptography' package.\n"
        "  pip install 'cryptography>=42'   (it is a declared portal dependency)"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CERT_DIR = REPO_ROOT / "portal" / "data" / "certs"

CA_CN = "MedSim Dev Local CA"
LEAF_CN = "MedSim VRAI Faces (dev)"
CA_DAYS = 3650
LEAF_DAYS = 397  # < 398 so Safari/iOS (iPad-first) accepts the leaf without warnings
UTC = _dt.timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────
def _lan_ipv4s() -> list[str]:
    """Best-effort LAN IPv4s for the SAN (no packets are actually sent)."""
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # selects the egress interface; sends nothing
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def _san(extra_hosts: list[str]) -> x509.SubjectAlternativeName:
    dns = ["localhost", *extra_hosts]
    pub = os.environ.get("MEDSIM_PUBLIC_HOST", "").strip()
    if pub:
        dns.append(pub)
    names: list[x509.GeneralName] = []
    seen: set[str] = set()
    for h in dns:
        if h and h not in seen:
            seen.add(h)
            names.append(x509.DNSName(h))
    for ip in ["127.0.0.1", "::1", *_lan_ipv4s()]:
        if ip not in seen:
            seen.add(ip)
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
    return x509.SubjectAlternativeName(names)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)  # best-effort; a no-op semantic on Windows
    except OSError:
        pass


def _fingerprint(cert: x509.Certificate) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


# ── generate ────────────────────────────────────────────────────────────────
def _load_or_make_ca(cert_dir: Path, remint: bool) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    ca_crt, ca_key = cert_dir / "rootCA.pem", cert_dir / "rootCA-key.pem"
    if ca_crt.exists() and ca_key.exists() and not remint:
        cert = x509.load_pem_x509_certificate(ca_crt.read_bytes())
        key = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
        print(f"Reusing existing CA (mint-once, ADR-0029): {ca_crt}")
        return cert, key  # type: ignore[return-value]
    if (ca_crt.exists() or ca_key.exists()) and not remint:
        sys.exit("CA is half-present — pass --remint to regenerate (re-trust ALL devices).")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_CN)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca_crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(ca_key, key)
    print(f"{'RE-MINTED' if remint else 'Created'} CA → {ca_crt} (re-trust on every device)")
    return cert, key


def generate(cert_dir: Path, extra_hosts: list[str], remint: bool) -> int:
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_key = _load_or_make_ca(cert_dir, remint)
    san = _san(extra_hosts)
    print("Issuing dev TLS leaf for: " + ", ".join(g.value if isinstance(g, x509.DNSName)
          else str(g.value) for g in san))

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.now(UTC)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, LEAF_CN)]))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=LEAF_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(san, critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_pem = leaf.public_bytes(serialization.Encoding.PEM)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    (cert_dir / "dev-cert.pem").write_bytes(leaf_pem + ca_pem)  # leaf + CA chain
    _write_key(cert_dir / "dev-key.pem", leaf_key)

    print(f"\nWrote leaf (valid {LEAF_DAYS}d) → {cert_dir / 'dev-cert.pem'} (+ dev-key.pem)")
    print(f"CA SHA-256: {_fingerprint(ca_cert)}")
    print("\nNext: trust rootCA.pem — sudo scripts/trust-ca-mac.sh (macOS) / "
          "scripts/trust-ca-windows.ps1 (Windows, admin); install it on each tablet.")
    return 0


# ── doctor ──────────────────────────────────────────────────────────────────
def doctor(cert_dir: Path) -> int:
    print(f"== dev_cert doctor ==  {cert_dir}\n")
    files = {n: cert_dir / n for n in ("rootCA.pem", "rootCA-key.pem", "dev-cert.pem", "dev-key.pem")}
    missing = [n for n, p in files.items() if not p.exists()]
    if missing:
        print("MISSING: " + ", ".join(missing) + "\n  → run: python scripts/dev_cert.py")
        return 1

    leaf = x509.load_pem_x509_certificate(files["dev-cert.pem"].read_bytes())
    ca = x509.load_pem_x509_certificate(files["rootCA.pem"].read_bytes())
    key = serialization.load_pem_private_key(files["dev-key.pem"].read_bytes(), password=None)

    ok = True

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and cond
        print(f"  [{'OK ' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    leaf_pub = leaf.public_key().public_numbers()  # type: ignore[union-attr]
    check("cert/key match", leaf_pub == key.public_key().public_numbers())  # type: ignore[union-attr]
    check("leaf issued by the CA", leaf.issuer == ca.subject)
    now = _dt.datetime.now(UTC)
    check("leaf within validity", leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc,
          f"expires {leaf.not_valid_after_utc.date()}")
    check("CA within validity", ca.not_valid_before_utc <= now <= ca.not_valid_after_utc,
          f"expires {ca.not_valid_after_utc.date()}")

    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = san.get_values_for_type(x509.DNSName)
        ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
        print(f"  SAN DNS: {', '.join(dns) or '(none)'}")
        print(f"  SAN IPs: {', '.join(ips) or '(none)'}")
        lan = _lan_ipv4s()
        missing_ip = [ip for ip in lan if ip not in ips]
        check("SAN covers this host's LAN IP(s)", not missing_ip,
              f"not covered: {missing_ip}; re-run dev_cert.py" if missing_ip else f"{lan or 'none detected'}")
        pub = os.environ.get("MEDSIM_PUBLIC_HOST", "").strip()
        if pub:
            check(f"SAN covers MEDSIM_PUBLIC_HOST ({pub})", pub in dns)
    except x509.ExtensionNotFound:
        check("leaf has SubjectAltName", False)

    print(f"\n  CA SHA-256: {_fingerprint(ca)}")
    sysname = platform.system()
    print("\n  Trust the CA (the decisive step — the cert above is fine; ADR-0029):")
    if sysname == "Darwin":
        print("    sudo scripts/trust-ca-mac.sh   then fully quit + reopen Chrome")
        print("    verify: security verify-cert -c portal/data/certs/dev-cert.pem")
    elif sysname == "Windows":
        print("    pwsh -File scripts/trust-ca-windows.ps1   (Run as Administrator)")
        print("    verify: Get-ChildItem Cert:\\LocalMachine\\Root | ? Subject -match 'MedSim Dev Local CA'")
    else:
        print("    sudo cp portal/data/certs/rootCA.pem /usr/local/share/ca-certificates/medsim.crt "
              "&& sudo update-ca-certificates")
    print("    tablet: open https://<host>:8760/rootca.pem → install as a CA certificate")
    print("\n" + ("All cert checks passed (trust separately, above)." if ok else "Some checks FAILED — see above."))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Cross-platform dev TLS cert tool (VRAI Faces).")
    p.add_argument("command", nargs="?", default="gen", choices=("gen", "doctor"),
                   help="gen = issue/refresh the leaf (default); doctor = read-only diagnosis")
    p.add_argument("--cert-dir", type=Path, default=DEFAULT_CERT_DIR, help="cert output dir")
    p.add_argument("--host", action="append", default=[], metavar="NAME",
                   help="extra DNS SAN entry (repeatable); MEDSIM_PUBLIC_HOST is auto-included")
    p.add_argument("--remint", action="store_true",
                   help="regenerate the CA too — invalidates trust on EVERY device")
    args = p.parse_args(argv)
    if args.command == "doctor":
        return doctor(args.cert_dir)
    return generate(args.cert_dir, args.host, args.remint)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
