#!/usr/bin/env bash
# Generate a local dev TLS cert so the VRAI Faces app + portal can be served over
# HTTPS — required for a *secure context* on a tablet (WebGPU renders the avatar
# skin, getUserMedia/Web Speech enables push-to-talk, crypto.subtle works).
#
# Creates a small local Certificate Authority and a leaf cert covering
# localhost, 127.0.0.1, and the LAN IP. Trust rootCA.pem once on each tablet and
# the browser stops warning (the mkcert experience, with stock openssl).
#
# Usage:
#   scripts/make-dev-cert.sh            # auto-detect LAN IP
#   scripts/make-dev-cert.sh 192.168.1.165 [more IPs/hosts...]
#   FORCE=1 scripts/make-dev-cert.sh    # regenerate even if certs exist
#
# Outputs (gitignored) into portal/data/certs/:
#   rootCA.pem     — install + trust this on each tablet
#   dev-cert.pem   — leaf + CA chain (served by vite + uvicorn)
#   dev-key.pem    — leaf private key (NEVER commit / share)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="$ROOT_DIR/portal/data/certs"
mkdir -p "$CERT_DIR"

# --- collect SAN entries: localhost + loopback + the LAN IP(s) ----------------
lan_ip() {
  # Best-effort LAN IP (no traffic actually sent over the UDP socket).
  python3 - <<'PY' 2>/dev/null || true
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80)); print(s.getsockname()[0])
except OSError:
    pass
finally:
    s.close()
PY
}

HOSTS=("localhost")
IPS=("127.0.0.1")
if [ "$#" -gt 0 ]; then
  for arg in "$@"; do
    if [[ "$arg" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then IPS+=("$arg"); else HOSTS+=("$arg"); fi
  done
else
  ip="$(lan_ip)"
  [ -n "${ip:-}" ] && IPS+=("$ip")
fi

# Build the subjectAltName list (Bash 3.2-compatible — no associative arrays;
# duplicate SAN entries are harmless to openssl).
SAN=""
for h in "${HOSTS[@]}"; do SAN+="DNS:$h,"; done
for i in "${IPS[@]}"; do SAN+="IP:$i,"; done
SAN="${SAN%,}"
# Squash any exact duplicate entries for tidiness.
SAN="$(printf '%s' "$SAN" | tr ',' '\n' | awk '!seen[$0]++' | paste -sd, -)"

echo "Issuing dev TLS leaf for: $SAN"
cd "$CERT_DIR"

# --- 1. Local root CA — REUSE if present so trusted devices stay valid --------
# Re-issuing the leaf for a new LAN IP keeps the SAME CA, so a tablet that
# already trusts rootCA.pem does NOT need to re-trust anything. FORCE=1 mints a
# brand-new CA (then you must re-install rootCA.pem on each device).
if [ -f rootCA.pem ] && [ -f rootCA-key.pem ] && [ -z "${FORCE:-}" ]; then
  echo "  ↻ reusing existing root CA (no device re-trust needed)."
else
  echo "  + creating a new root CA (re-trust rootCA.pem on each device afterward)."
  openssl genrsa -out rootCA-key.pem 2048 >/dev/null 2>&1
  openssl req -x509 -new -nodes -key rootCA-key.pem -sha256 -days 825 \
    -out rootCA.pem -subj "/CN=MedSim Dev Local CA" >/dev/null 2>&1
fi

# --- 2. Leaf key + CSR --------------------------------------------------------
openssl genrsa -out dev-key.pem 2048 >/dev/null 2>&1
openssl req -new -key dev-key.pem -out dev.csr -subj "/CN=MedSim VRAI Faces (dev)" >/dev/null 2>&1

# --- 3. Sign the leaf with the CA, carrying the SAN ---------------------------
EXT_FILE="$(mktemp)"
cat > "$EXT_FILE" <<EXT
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$SAN
EXT
openssl x509 -req -in dev.csr -CA rootCA.pem -CAkey rootCA-key.pem -CAcreateserial \
  -out dev-leaf.pem -days 825 -sha256 -extfile "$EXT_FILE" >/dev/null 2>&1
rm -f "$EXT_FILE" dev.csr rootCA.srl

# Served chain = leaf + CA (so clients that don't yet trust the CA still see it).
cat dev-leaf.pem rootCA.pem > dev-cert.pem
rm -f dev-leaf.pem

echo "✓ Wrote:"
echo "    $CERT_DIR/rootCA.pem    (trust this on each tablet)"
echo "    $CERT_DIR/dev-cert.pem  (served by vite + uvicorn)"
echo "    $CERT_DIR/dev-key.pem   (private key — never commit)"
echo ""
echo "Next: trust rootCA.pem on the tablet, then start the portal + app over HTTPS."
