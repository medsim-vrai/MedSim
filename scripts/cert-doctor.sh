#!/usr/bin/env bash
# Read-only TLS/trust diagnosis for the MedSim dev HTTPS setup. Run this anytime
# the Mac or a tablet says "not secure" — it pinpoints whether the problem is the
# CERT (rare) or TRUST (the usual cause) and prints the exact fix. Changes nothing.
#
#   scripts/cert-doctor.sh             # checks the portal on :8760
#   PORT=5173 scripts/cert-doctor.sh   # checks a vite dev server instead
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
C="$ROOT_DIR/portal/data/certs"
PORT="${PORT:-8760}"

ok()  { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad() { printf "  \033[31m✗\033[0m %s\n" "$1"; }

echo "== MedSim cert doctor (port $PORT) =="

if [ -f "$C/rootCA.pem" ] && [ -f "$C/dev-cert.pem" ] && [ -f "$C/dev-key.pem" ]; then
  ok "cert files present in portal/data/certs/"
else
  bad "missing certs in $C — run scripts/make-dev-cert.sh"
  exit 1
fi

# Serving mode — is the portal actually answering over TLS?
code=$(curl -sk -o /dev/null -w "%{http_code}" "https://127.0.0.1:$PORT/" 2>/dev/null || echo 000)
if [ "$code" != "000" ]; then ok "HTTPS responding on :$PORT (HTTP $code)"
else bad "no HTTPS on :$PORT — is the portal running with the cert? (run_portal.py auto-TLS when certs exist)"; fi

# Cert/key pair match
cm=$(openssl x509 -noout -modulus -in "$C/dev-cert.pem" 2>/dev/null | openssl md5)
km=$(openssl rsa  -noout -modulus -in "$C/dev-key.pem"  2>/dev/null | openssl md5)
if [ "$cm" = "$km" ]; then ok "cert/key pair matches"; else bad "cert/key MISMATCH"; fi

# Chain — leaf verifies against the CA
if openssl verify -CAfile "$C/rootCA.pem" "$C/dev-cert.pem" >/dev/null 2>&1; then
  ok "leaf chains to rootCA.pem"; else bad "leaf does NOT chain to rootCA.pem"; fi

# Validity window
nb=$(openssl x509 -in "$C/dev-cert.pem" -noout -startdate 2>/dev/null | sed 's/.*=//')
na=$(openssl x509 -in "$C/dev-cert.pem" -noout -enddate   2>/dev/null | sed 's/.*=//')
if openssl x509 -in "$C/dev-cert.pem" -noout -checkend 0 >/dev/null 2>&1; then
  ok "within validity ($nb → $na)"; else bad "cert EXPIRED/not-yet-valid ($nb → $na) — check the clock"; fi

# SAN vs current LAN IP (a changed IP is the usual reissue trigger)
lan=$(python3 -c "import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8',80)); print(s.getsockname()[0])
except OSError:
    pass
finally:
    s.close()" 2>/dev/null)
# Parse SAN from -text (portable: macOS LibreSSL has no `-ext` flag).
san=$(openssl x509 -in "$C/dev-cert.pem" -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name")
if [ -n "${lan:-}" ]; then
  if printf '%s' "$san" | grep -q "$lan"; then ok "SAN covers this LAN IP ($lan)"
  else bad "SAN is MISSING this LAN IP ($lan) — reissue: scripts/make-dev-cert.sh $lan"; fi
fi

# Stable hostname (ADR-0030): if MEDSIM_PUBLIC_HOST is set it must be in the SAN
# AND must resolve here, or devices addressing the portal by name will fail.
pub="${MEDSIM_PUBLIC_HOST:-}"
if [ -n "$pub" ]; then
  printf '%s' "$san" | grep -q "$pub" \
    && ok "SAN covers MEDSIM_PUBLIC_HOST ($pub)" \
    || bad "SAN missing MEDSIM_PUBLIC_HOST ($pub) — reissue: MEDSIM_PUBLIC_HOST=$pub scripts/make-dev-cert.sh <ips>"
  if python3 -c "import socket; socket.gethostbyname('$pub')" >/dev/null 2>&1; then
    ok "$pub resolves on this machine"
  else
    bad "$pub does NOT resolve here — add a gateway DNS record (devices) or an /etc/hosts entry (this Mac)"
  fi
fi

# THE key check on macOS — is the CA actually TRUSTED (not just present)?
if [ "$(uname)" = "Darwin" ]; then
  if security verify-cert -c "$C/rootCA.pem" >/dev/null 2>&1; then
    ok "CA trusted on this Mac"
  else
    bad "CA NOT trusted on this Mac   ← this is the 'Not Secure' cause"
    echo "        fix:  sudo scripts/trust-ca-mac.sh   (then fully quit + reopen Chrome)"
  fi
fi

fpr=$(openssl x509 -in "$C/rootCA.pem" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
echo ""
echo "  rootCA SHA-256: $fpr"
echo "  Tablet (one-time): on the tablet open  https://${lan:-<lan-ip>}:$PORT/rootca.pem"
echo "    → Settings → Security → Install a certificate → CA certificate → pick it,"
echo "    → confirm the fingerprint above matches. Remove any older 'MedSim Dev Local CA' first."
