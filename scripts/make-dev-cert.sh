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
# Always cover the configured stable hostname (ADR-0030) so the cert can't drift
# from MEDSIM_PUBLIC_HOST — set it once and every reissue includes it.
[ -n "${MEDSIM_PUBLIC_HOST:-}" ] && HOSTS+=("$MEDSIM_PUBLIC_HOST")
if [ "$#" -gt 0 ]; then
  # NOTE: when you pass IPs explicitly, ALL the ones you want must be listed
  # (e.g. both locations: `make-dev-cert.sh 192.168.1.185 192.168.1.165`) — a
  # bare run only auto-adds the *current* IP and would drop the others.
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
# already trusts rootCA.pem does NOT need to re-trust anything.
#
# RE-MINTING THE CA INVALIDATES TRUST ON EVERY DEVICE — it is the #1 cause of the
# recurring "not secure" pain — so it is GUARDED: FORCE=1 alone is NOT enough to
# replace an existing CA; you must ALSO pass REMINT_CA=yes to confirm you accept
# re-trusting every Mac + tablet afterward. To merely reissue the LEAF for a new
# IP, run with NO flags (the CA is reused automatically).
MINT_CA=0
if [ -f rootCA.pem ] && [ -f rootCA-key.pem ]; then
  if [ -n "${FORCE:-}" ]; then
    if [ "${REMINT_CA:-}" != "yes" ]; then
      echo "✗ REFUSING to re-mint the existing root CA."
      echo "  FORCE=1 was set, but re-minting invalidates CA trust on EVERY device"
      echo "  (the Mac keychain + each tablet). If you truly intend that, re-run with:"
      echo "      FORCE=1 REMINT_CA=yes $0 $*"
      echo "  To only reissue the leaf for a new IP, drop FORCE (the CA is reused)."
      exit 1
    fi
    echo "  ⚠️  RE-MINTING the root CA (REMINT_CA=yes) — you MUST re-trust rootCA.pem on"
    echo "      every device afterward (sudo scripts/trust-ca-mac.sh + reinstall on tablets)."
    MINT_CA=1
  else
    echo "  ↻ reusing existing root CA (no device re-trust needed)."
  fi
else
  echo "  + creating the root CA for the first time."
  MINT_CA=1
fi

if [ "$MINT_CA" = 1 ]; then
  openssl genrsa -out rootCA-key.pem 2048 >/dev/null 2>&1
  # CRITICAL: a CA cert MUST carry basicConstraints CA:TRUE + keyCertSign, or
  # Android/Chrome reject it as a signer ("not secure") even though macOS's
  # lenient `openssl verify` accepts a bare self-signed cert.
  openssl req -x509 -new -nodes -key rootCA-key.pem -sha256 -days 3650 \
    -out rootCA.pem -subj "/CN=MedSim Dev Local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1
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
  -out dev-leaf.pem -days 398 -sha256 -extfile "$EXT_FILE" >/dev/null 2>&1
rm -f "$EXT_FILE" dev.csr rootCA.srl

# Served chain = leaf + CA (so clients that don't yet trust the CA still see it).
cat dev-leaf.pem rootCA.pem > dev-cert.pem
rm -f dev-leaf.pem

echo "✓ Wrote:"
echo "    $CERT_DIR/rootCA.pem    (trust this on each device)"
echo "    $CERT_DIR/dev-cert.pem  (served by vite + uvicorn)"
echo "    $CERT_DIR/dev-key.pem   (private key — never commit)"
echo ""
echo "rootCA SHA-256: $(openssl x509 -in rootCA.pem -noout -fingerprint -sha256 | sed 's/.*=//')"
echo ""
echo "Next (trusting the CA is what stops the 'not secure' warning — the cert is fine):"
echo "  • Mac:    sudo $ROOT_DIR/scripts/trust-ca-mac.sh   then fully quit + reopen Chrome"
echo "  • Tablet: install rootCA.pem (Settings → Install a certificate → CA certificate)"
echo "  • Verify: $ROOT_DIR/scripts/cert-doctor.sh"
