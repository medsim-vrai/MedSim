# Certificates & Network Changes — the Runbook

**Why this exists:** on 2026-06-09 a router change cost ~2 hours twice because the TLS trust chain
broke in ways that *looked like* network failures (white screens, "only loads in private tabs",
ghost apps). This runbook makes any router/IP/venue change a **2-minute, zero-surprise procedure**.
Read this BEFORE touching networks; `scripts/preflight.sh` automates the checks.

---

## 1 · The trust model (one CA forever · disposable leaves)

```
MedSim Dev Local CA  (rootCA.pem · 10-year · created 2026-05-30)
 │   installed + FULL-TRUSTED **once per device** — never again
 │
 └── leaf cert (dev-cert.pem · ≤825 days · SAN = the portal's IPs/hostnames)
       re-minted FREELY whenever the network changes — devices trust it
       automatically because it chains to the CA
```

- **The CA is the device-side investment.** Each iPad/tablet installs + trusts it ONE time.
- **The leaf is disposable.** New router → new Mac IP → re-mint the leaf with the new IP in its
  SAN → restart the portal. **No device needs to be touched.**
- `scripts/make-dev-cert.sh` **reuses the existing CA by default** — this is what makes the model
  work. `REMINT_CA=yes` is the only way to destroy it; doing so forces **re-trusting every device
  in the fleet**. Never use it casually.

## 2 · Router / venue change procedure (the only steps)

```bash
# on the Mac, from the medsim_v8 repo:
bash scripts/make-dev-cert.sh <NEW-IP> 192.168.1.165 192.168.1.185   # new IP + keep known ones
# restart the portal (it loads the cert at startup):
VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 python3 run_portal.py
bash scripts/preflight.sh [tablet-ip]    # must be ALL GREEN before anyone scans
```
The preflight regenerates the QR for the current network (Desktop + Preview). **iPads need
nothing** — no new profile, no toggles, no warnings — because the new leaf chains to the CA they
already trust.

## 2b · "Operator works but EVERY tablet fails" — IP-SAN drift (2026-06-22)

A second venue/IP change cost a round-trip on 2026-06-22 in a way the §4 table didn't
yet name. Captured in full so it never repeats.

**Signature.** The operator on the Mac (localhost) is **fine** — control-room
push-to-talk works — but **every LAN device fails the same way**: the avatar page taps
through the cert warning and *appears to load*, then the **character image never
appears**, **STT/TTS don't connect**, sends fail (**"Send failed"**), and device QRs
bounce to **"scan a fresh QR."** It reads as "connections, not logic" — because it is.

**Why it's deceptive.** A browser lets you tap through a bad cert for the **top-level
page only**. The avatar's binding fetch (`/api/face/<id>/binding`) and the speech
**WebSocket** are *subresources* — there is **no tap-through** for those — so they're
silently blocked while the page itself looks loaded. Localhost is always in the SAN, so
the operator never sees the failure. Same root cause behind the Android device "fresh
QR."

**Root cause — two ways in:**
1. **IP drift.** DHCP moved the Mac (e.g. `192.168.1.134` → `.135`); the leaf's SAN no
   longer lists the current IP.
2. **The IP was minted as a DNS name, not an IP.** Passing the IP as a host arg
   (`dev_cert.py --host 192.168.1.134`) records it as `DNS:192.168.1.134`. Browsers
   validate an **IP-literal URL** against **`IP Address:` SAN entries only** — a `DNS:`
   entry that merely *looks* like an IP does **not** count. So IP-literal TLS fails even
   on the "correct" IP. (This is why it kept recurring — the fix command itself was
   wrong.)

**Diagnose (read-only):**
```
ipconfig getifaddr en0                                    # current LAN IP
openssl x509 -in portal/data/certs/dev-cert.pem -noout -text | grep -A1 "Alternative Name"
```
The SAN **must** contain `IP Address:<that LAN IP>` — not `DNS:<ip>`, and not a stale IP.

**Fix — re-mint the leaf with the BARE command (no host arg):**
```
python scripts/dev_cert.py        # auto-detects the LAN IP, writes it as an IP SAN, REUSES the CA
```
- ✅ Bare invocation auto-detects the egress IP and adds it as a proper `IP Address:` SAN.
- ❌ Do **not** pass the IP as `--host <ip>` — that's the `DNS:`-SAN trap above.
- ❌ Do **not** use `--remint` — it regenerates the CA and forces re-trusting every device.

**Then RESTART the portal — this is the step that bit us.** The server loads the cert
**once at boot**, so a *running* server keeps serving the OLD cert after a re-mint until
you bounce it (Ctrl+C → relaunch). Always verify the **running** server is serving the
new cert before touching a tablet:
```
echo | openssl s_client -connect 127.0.0.1:8765 2>/dev/null | openssl x509 -noout -text | grep -A1 "Alternative Name"
```
Tablets need **nothing** (CA unchanged) — just **re-scan the QR** (drops the stale
cached page and reconnects over the new cert). **Confirmed end-to-end on an iPad
2026-06-22:** after re-mint + restart, the patient avatar loaded, the character
responded, and STT/TTS worked.

> **Prevention SHIPPED (#70, commit `0ad8447`):** `run_portal.main()` now calls
> `_ensure_cert_covers_lan_ip()` at boot — if the current `_lan_ip()` isn't an
> IP-Address SAN in the leaf, it auto-re-mints (bare `dev_cert.py`, reuse CA) before
> binding, so IP drift self-heals on every launch and the served cert always matches
> the IP baked into the tablet QRs. The banner prints `Cert: auto re-minted for <ip>`.
> Disable with `MEDSIM_NO_CERT_AUTOFIX=1`. The durable fix is still §6 (stable hostname).
> So in practice the §2b manual steps are now only needed mid-session (no restart).

## 3 · New-device onboarding (one time per tablet — Apple AND Android)

**The easy path (2026-06-10): the portal runs an onboarding helper on plain HTTP at
`http://<mac-ip>:8766`** — open that on any new tablet. It serves per-platform step-by-step
instructions + the CA download, with no certificate chicken-and-egg (plain http needs no trust).
The portal banner + `preflight.sh` print this URL. Manual steps, for reference:

**Apple (iPad / Safari):**
1. **Install the CA:** download `rootca.pem` (from the onboarding page, or
   `https://<mac-ip>:8765/rootca.pem` if this tablet can already reach the portal) → Allow →
   Settings → **Profile Downloaded → Install** (passcode → Install again).
   ⚠️ Never hand-type a plain-`http://` download link into Safari — HTTPS-First upgrades it and
   the download dies. The :8766 onboarding page's buttons carry explicit schemes and work.
2. **Trust it fully:** Settings → General → About → **Certificate Trust Settings** → toggle
   **MedSim Dev Local CA → ON**. (The toggle only appears AFTER the profile is installed.)
3. **Network identity:** Settings → Wi-Fi → ⓘ on the dev network → **Private Wi-Fi Address →
   Off** (→ Rejoin). A randomized/rotating MAC made the Tenda router silently drop ALL
   device↔device traffic (2026-06-09) — and some routers key device policies to the MAC.

**Android (tablet / Chrome):**
1. Download `rootca.pem` from the onboarding page (`http://<mac-ip>:8766`).
2. Settings → search "**CA certificate**" (usually Security & privacy → More security →
   Encryption & credentials → **Install a certificate → CA certificate**) → tap **Install
   anyway** → pick the downloaded file.
3. **Chrome on Android trusts user-installed CAs immediately** — pages load with no warning.
   (Native Android *apps* would need a network-security-config; the browser does not.)

Then scan the QR. Done — the device now survives every future cert re-mint and router change.

## 3b · Simulated-device pages (monitors/pumps) on tablets — fixed 2026-06-10

The device-skin QR flow historically failed on tablets with a "security conflict". TWO stacked
causes, both fixed/handled:
1. **The `/d` QR redirector dated from the portal's pre-TLS era**: it bounced tablets to
   hard-coded `http://` targets (dead against the https-only port on EVERY platform) and
   force-opened Chrome via `googlechrome://` (errors on iPads without Chrome). It is now a plain
   **same-origin 307 redirect** — scheme/host preserved by construction, opens in the platform's
   default browser. The skins were audited (2026-06-10): plain same-origin web pages, **no
   Chrome-only APIs** — Safari (iPadOS) and Chrome (Android) both render them.
   (`MEDSIM_QR_OPEN_IN=ios` still exists for the legacy Chrome-handoff QR encoding; default
   "smart" mode needs nothing.)
2. **Missing CA trust on the tablet** — §3 above. Any tablet that skips onboarding sees the
   interstitial on ALL portal pages, devices included.

**Validated on tablet 2026-06-10:** IV pump (alaris) minted from the Ops page, scanned, loaded
and functioned on the tablet — no security warning, no Chrome hand-off.

## 4 · Failure signatures (what each missing piece looks like)

| Symptom on the iPad | Actual cause | Fix |
|---|---|---|
| Operator (localhost) works, but **every tablet** fails: page loads then no image, no STT/TTS, "Send failed", device asks for a "fresh QR" | Leaf has no `IP Address:` SAN for the current IP (IP drift, or the IP was minted as a `DNS:` name) — subresource fetch + speech WS are blocked with no tap-through | **§2b** — bare `python scripts/dev_cert.py` → **restart** portal → verify served SAN → re-scan QR |
| "This Connection Is Not Private" interstitial | Leaf SAN doesn't cover the current IP, OR the CA trust toggle is off / profile not installed | Re-mint leaf + restart portal (§2), or finish §3 steps 1–2 |
| Loads only after tapping "visit this website" — and **breaks again after every re-mint** | Running on a per-cert exception instead of CA trust | §3 steps 1–2 (the tap-through dies with each new leaf; CA trust doesn't) |
| White screen, URL in the bar, spinner forever | TLS failing with **stale tab state** masking the interstitial | Clear Safari Website Data for the portal origins, retry — then fix the cert per above |
| **Ghost app** — UI/panels load, face is a black void | The service worker's offline shell booted from cache; the (uncached) binding API couldn't reach the portal | Network/TLS is broken underneath — diagnose with the table above |
| "Works in private tabs only" | Normal-tab state (stale exception/caches) — **not** Private Relay (exonerated 2026-06-09) | Clear Website Data + §3 steps 1–2 |
| Page loads; mic takes are slow EVERY session (~60 s first take) | Running in a **private tab** → no persistent storage → the ~70 MB speech model re-downloads each session | Use a normal tab (or the home-screen app); the model then caches per-origin |
| Nothing loads, ping Mac→iPad fails, iPad invisible | Router dropping device↔device traffic (randomized MAC identity, or AP/client isolation) | §3 step 3; or the router's isolation setting; hotspots: carrier IPv6-only (CLAT 192.0.0.2) can't pair at all |

## 5 · Diagnostic gotchas (hard-won)

- **The portal access log is blind to TLS failures.** Uvicorn logs a line only AFTER a request
  arrives over a completed TLS session — a cert-rejected handshake leaves **no trace**. "Zero log
  lines" ≠ "no traffic". Don't repeat the 2026-06-09 misdiagnosis ("transport block") — when the
  log is empty but ping works, suspect **TLS/trust first**.
- **Leaf requirements for iOS:** ≤825-day validity, `serverAuth` EKU, IPs in SAN —
  `make-dev-cert.sh` produces compliant leaves; don't hand-roll.
- `scripts/cert-doctor.sh` inspects the current chain when in doubt.

## 6 · The structural fix (planned — FR-004)

A **stable hostname** (`portal.medsim.lan`, already in the leaf SAN) pinned via the kit travel
router (or local DNS) removes even the §2 re-mint: one origin everywhere → one QR forever → and the
iPad's model cache (keyed to the origin!) stays warm across venues. Until then, §2 is the drill.
