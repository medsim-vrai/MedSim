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

## 4 · Failure signatures (what each missing piece looks like)

| Symptom on the iPad | Actual cause | Fix |
|---|---|---|
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
