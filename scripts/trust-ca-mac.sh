#!/usr/bin/env bash
# Trust the MedSim dev root CA on THIS Mac so Chrome/Safari stop warning about
# the local HTTPS cert.
#
# The cert, key, chain and SAN are already correct — the ONLY thing missing is
# the *trust* setting. A root CA can sit in the keychain UNtrusted, which is
# exactly the "Not Secure" state (`security verify-cert` → CSSMERR_TP_NOT_TRUSTED).
# This sets the cert as a trusted root in the admin (system) domain, which is
# what Chrome on macOS evaluates.
#
# Trusting a root CA is a system-security change, so this needs admin:
#   sudo scripts/trust-ca-mac.sh
#
# Idempotent: clears any stale "MedSim Dev Local CA" copies from the System
# keychain first (old re-mints), then installs + trusts the CURRENT rootCA.pem.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CA="$ROOT_DIR/portal/data/certs/rootCA.pem"
CA_CN="MedSim Dev Local CA"
SYS_KC="/Library/Keychains/System.keychain"

if [ "$(uname)" != "Darwin" ]; then
  echo "✗ This script is macOS-only (it uses the 'security' keychain tool)."
  exit 1
fi
if [ ! -f "$CA" ]; then
  echo "✗ No CA at $CA"
  echo "  Run scripts/make-dev-cert.sh first to generate it."
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "Trusting a root CA is a system-security change and needs admin."
  echo "Re-run:  sudo $0"
  exit 1
fi

FPR="$(openssl x509 -in "$CA" -noout -fingerprint -sha256 | sed 's/.*=//')"
echo "Trusting root CA on this Mac:"
echo "  file:    $CA"
echo "  SHA-256: $FPR"
echo ""

# 1. Remove stale System-keychain copies (old re-mints) so trust evaluation
#    can't latch onto an old, untrusted duplicate. Best-effort + bounded.
for _ in 1 2 3 4 5; do
  security find-certificate -c "$CA_CN" "$SYS_KC" >/dev/null 2>&1 || break
  security delete-certificate -c "$CA_CN" "$SYS_KC" >/dev/null 2>&1 || break
done

# 2. Install + TRUST the current CA as a root in the admin (system) domain.
security add-trusted-cert -d -r trustRoot -k "$SYS_KC" "$CA"

echo "✓ CA installed and trusted as a root."
echo ""
echo "  NEXT: fully quit Chrome (Cmd-Q) and reopen it — it caches trust at launch."
echo "  Verify:  scripts/cert-doctor.sh   → should now show 'CA trusted on this Mac'"
