#!/usr/bin/env bash
# Standard test-session preflight (FR-004 lesson, 2026-06-09): one command that answers
# "is the tablet pairing going to work RIGHT NOW?" before anyone scans a QR — so a router/
# IP/cert/identity drift is caught in 10 seconds instead of burning a 2-hour session.
#
#   bash scripts/preflight.sh            # checks + regenerates the QR for the current network
#   bash scripts/preflight.sh 192.168.1.169   # also ping-test the tablet at that IP
#
# Checks: network identity → portal up + one-origin mode → cert covers the current IP →
# QR regenerated for the current IP (Desktop + Preview). Exits non-zero if anything's wrong.
set -u
cd "$(dirname "$0")/.." || exit 1

PORT="${MEDSIM_PORT:-8760}"
TABLET_IP="${1:-}"
PASS=0; FAIL=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }

echo "── 1 · Network ─────────────────────────────────────────────"
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
ROUTER="$(ipconfig getsummary en0 2>/dev/null | awk '/Router :/ {print $3; exit}')"
ROUTER_MAC="$(arp -n "${ROUTER:-0}" 2>/dev/null | awk '{print $4}' | head -1)"
if [ -n "${IP:-}" ] && [[ "$IP" != 192.0.0.* ]]; then
  ok "Mac LAN IP: $IP   (router ${ROUTER:-?} ${ROUTER_MAC:+· $ROUTER_MAC})"
else
  bad "No usable IPv4 (got '${IP:-none}'). 192.0.0.2 = IPv6-only hotspot — tablets can't pair on it."
fi

echo "── 2 · Portal ──────────────────────────────────────────────"
LISTENER="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1" pid "$2}')"
if [ -n "$LISTENER" ]; then ok "Portal listening on :$PORT ($LISTENER)"; else bad "Nothing listening on :$PORT — start it: VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 python3 run_portal.py"; fi
if [ -n "${IP:-}" ]; then
  BODY="$(curl -sk --connect-timeout 4 "https://$IP:$PORT/face/P-014" 2>/dev/null)"
  if echo "$BODY" | grep -q '/assets/index-'; then ok "One-origin app served at https://$IP:$PORT/face/… (built dist)"
  elif [ -n "$BODY" ]; then bad "/face responds but isn't the built app — portal started without VRAI_FACES_SERVE=portal?"
  else bad "Portal unreachable at https://$IP:$PORT (bound to 127.0.0.1 only? need MEDSIM_HOST=0.0.0.0)"; fi
fi

echo "── 3 · Certificate ─────────────────────────────────────────"
CERT="portal/data/certs/dev-cert.pem"
if [ -f "$CERT" ] && [ -n "${IP:-}" ]; then
  SAN="$(openssl x509 -in "$CERT" -noout -text 2>/dev/null | grep -A1 'Subject Alternative Name' | tail -1)"
  if echo "$SAN" | grep -q "$IP"; then ok "Cert SAN covers $IP"
  else bad "Cert does NOT cover $IP — run: bash scripts/make-dev-cert.sh $IP <other-known-IPs> && restart the portal"; fi
  echo "      SAN:$(echo "$SAN" | sed 's/^ *//')"
else
  [ -f "$CERT" ] || bad "No dev cert at $CERT (scripts/make-dev-cert.sh)"
fi

echo "── 4 · Tablet identity reminder ───────────────────────────"
echo "      Router/IP changed, or a tablet misbehaving? READ THE RUNBOOK: docs/CERTIFICATES-AND-NETWORK-CHANGES.md"
echo "      The 3 rules: (1) NEVER re-mint the CA (REMINT_CA) — leaf-only re-mints keep every device trusted;"
echo "      (2) every tablet (Apple AND Android) trusts the CA once — send NEW tablets to the onboarding"
echo "          page below; (3) Private Wi-Fi Address OFF on dev routers (randomized MACs get dropped)."
OB="$(curl -so /dev/null -w '%{http_code}' --connect-timeout 2 "http://$IP:$((PORT+1))/" 2>/dev/null)"
if [ "$OB" = "200" ]; then ok "Onboarding helper up: http://$IP:$((PORT+1))  ← new tablets start here"
else echo "      (onboarding helper not detected on :$((PORT+1)) — older portal build?)"; fi
if [ -n "$TABLET_IP" ]; then
  if ping -c 2 -t 3 -q "$TABLET_IP" >/dev/null 2>&1; then ok "Tablet $TABLET_IP answers ping"
  else bad "Tablet $TABLET_IP does NOT answer ping — wrong network, private-MAC identity, or router isolation"; fi
fi

echo "── 5 · QR (regenerated for the CURRENT network) ───────────"
if [ -n "${IP:-}" ] && [ "$FAIL" -eq 0 ]; then
  curl -sk "https://$IP:$PORT/qr/face/P-014.svg?scenario=eCsd-26gvgI&debug=1" -o /tmp/face_qr.svg \
    && rm -f /tmp/face_qr.svg.png \
    && qlmanage -t -s 560 -o /tmp /tmp/face_qr.svg >/dev/null 2>&1 \
    && mv -f /tmp/face_qr.svg.png "$HOME/Desktop/VRAI_face_QR.png" 2>/dev/null \
    && ok "QR → ~/Desktop/VRAI_face_QR.png (encodes https://$IP:$PORT/…)" \
    && open "$HOME/Desktop/VRAI_face_QR.png"
  echo "      Launch URL: https://$IP:$PORT/face/P-014?scenario=eCsd-26gvgI&opacity=0.66&api=https%3A%2F%2F$IP%3A$PORT&debug=1"
  echo "      Control room (Mac): https://localhost:$PORT — log in, then start your scenario (English name; the id above is only a channel)"
else
  echo "      (skipped — fix the ✗ items first)"
fi

echo "────────────────────────────────────────────────────────────"
if [ "$FAIL" -eq 0 ]; then echo "PREFLIGHT PASS ($PASS checks) — scan and go."; exit 0
else echo "PREFLIGHT FAIL ($FAIL problem(s) above) — fix before handing anyone a QR."; exit 1; fi
