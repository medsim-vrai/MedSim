# iPad Normal-Tab Fix & Cold-Start Elimination — Strategy (2026-06-10)

**Goal.** Scan the QR → avatar up → **first take warm in ≤10 s**, in normal Safari (or the installed
home-screen app), surviving venue/network changes — never again a 60 s first take or a tab that
silently won't load.

## The problem is three stacked layers (each alone breaks the experience)

**L1 · Transport — normal tabs don't connect.** Field-proven 2026-06-09 (post MAC-fix): normal-tab
loads of `https://192.168.1.185:8765` produced **zero packets at the portal** while private tabs
worked fully, and ping was fine. Private Browsing is documented to bypass **iCloud Private Relay**;
the matching per-network lever is **"Limit IP Address Tracking"**. Apple says Relay excludes private
(RFC-1918) addresses, but local-IP + custom-CA + non-standard-port in normal tabs hanging while
private works is a widely reported failure signature. The app's service worker is exonerated for
THIS layer: its navigations are network-first (`app-sw.js` §2a), so it always attempts the network —
zero packets means the connection died below the page layer.

**L2 · Storage — why the 60 s first take exists at all.**
- **Private tabs have no persistent storage** → the ~70 MB whisper model (transformers.js
  CacheStorage) re-downloads EVERY session. That's the 60 s.
- **Caches are per-ORIGIN, and our origin is an IP:port.** Router 1 (`…1.165:8765`) and router 2
  (`…1.185:8765`) are *different origins* → two cold caches (~200 MB each: whisper + kokoro + wasm +
  meshes). Every venue/IP change = another full cold start **even in normal tabs**. The stable
  hostname (FR-004; `DNS:portal.medsim.lan` is ALREADY in the cert SAN) collapses these into one
  permanent cache — the stable name isn't QR convenience, **it's the model cache**.
- **Safari's 7-day eviction** (ITP) can purge script-writable storage for sites unused for a week.
  Home-screen web apps (Add to Home Screen) are exempt — and standalone launch also removes the
  whole tab-mode/private-mode foot-gun for facilitators.

**L3 · Observability — we can't see which layer bit us.** Tonight's 2-hour hunt happened because a
white screen / slow take doesn't say WHY. The app must self-report: storage mode, service-worker
state, model-cache hit/miss, origin.

## ✅ Phase A — RESOLVED 2026-06-09 23:21 (root cause ≠ the suspect)

**Confirmed root cause: certificate trust, not Private Relay.** Step 2 (clear Website Data) surfaced
the truth: the fresh normal tab showed Safari's **"This Connection Is Not Private"** interstitial —
meaning connections had been reaching the portal ALL ALONG. Two compounding mistakes had hidden it:
1. **The access log only records requests AFTER TLS succeeds** — cert-rejected handshakes are
   invisible, which I had misread as "zero packets / transport block". (Lesson: absence from the
   uvicorn access log ≠ absence of traffic; only a packet capture proves transport.)
2. **Per-cert "visit this website" exceptions + the SW's offline ghost masked the failures
   inconsistently** — each cert re-mint today silently invalidated the previous tap-through, and
   depending on cache state the failure looked like a white screen, a ghost app (SW shell, no face),
   or "only works in private". Private Relay / Limit IP Address Tracking: **exonerated**.

After tapping "visit this website": the full avatar runs in a NORMAL tab (478-landmark mesh, webgpu,
voice turn in flight) and the whisper model is downloading into PERSISTENT cache.

**Permanent fix — APPLIED + VERIFIED 2026-06-09 23:35:** the **MedSim Dev Local CA** profile was
installed on the iPad (download from the portal itself: `https://<mac-ip>:8765/rootca.pem` — NOTE:
Safari's HTTPS-First breaks plain-http download links, use the portal route) + **full trust ON** in
Certificate Trust Settings. Result: the avatar loads in a normal tab **with no warning**, and a reload
fetched **zero assets and zero model files** — the SW shell cache + the whisper model persistent cache
both held. The 60 s private-tab first take is dead; future leaf re-mints chain silently. Added to the
preflight checklist. (Also corrected: the dev router is a **Tenda**, not TP-Link.)
**Canonical reference:** the full trust model, the router-change procedure, per-device onboarding,
and the failure-signature table now live in **`docs/CERTIFICATES-AND-NETWORK-CHANGES.md`** (repo
root) — read that before any network/venue change; the preflight points to it.

### (superseded) the original isolation matrix

One variable at a time, normal tab, retry `https://<ip>:8765` after each step; record which step
flips it green — that becomes the documented fix in the preflight + facilitator notes:
1. As-is (expect: white/hang) — baseline.
2. **Settings → Safari → Advanced → Website Data** → delete entries for both portal origins → retry.
   (Rules out residual site-state/SW; per L1 analysis this likely does NOT fix it — proving that is
   the point.)
3. **Settings → Wi-Fi → ⓘ → Limit IP Address Tracking → OFF** → toggle Wi-Fi off/on → retry. *(Prime
   suspect.)*
4. **Settings → [name] → iCloud → Private Relay → Off** (or "Don't use on this network") → retry.
5. If green at 3/4: turn the OTHER one back on to find the minimal toggle; note iPadOS version.

Deliverable: one line in `scripts/preflight.sh` + the strategy doc updated from "suspect" to
"confirmed: <step N>".

## Phase B — App-side hardening (code, S–M, one sitting)

1. **Boot diagnostic line** (diag panel + ⚙ metrics): `storage persistent|ephemeral · sw v11 active ·
   model-cache hit|miss · origin <host:port>`. Uses `navigator.storage.persisted()/estimate()`,
   `navigator.serviceWorker.getRegistration()`, and a transformers-cache probe. Any future "it's
   slow/white" becomes a 5-second read. *(The single highest-value item.)*
2. **`navigator.storage.persist()`** at boot — requests durable storage (no-op where unsupported;
   granted automatically for home-screen apps).
3. **Service-worker escape hatch**: a `?swreset=1` URL knob → unregister all SWs + clear CacheStorage
   for the origin + reload clean (fits the existing tuneNum knob pattern; preflight prints it).
4. **Quota-pressure trim**: stop double-caching >20 MB assets in the SW shell cache (`app-sw.js` §2b
   caches everything under `/assets/`, including the 96 MB kokoro ONNX that transformers/kokoro
   already cache themselves) — halves the origin's storage footprint → less eviction risk on iPads.

## Phase C — Kill the per-origin cold start structurally (rides FR-004)

Stable origin = permanent cache. When the kit router lands (or via mDNS/local DNS on the dev
routers): QR + cert pinned to **one hostname** (`portal.medsim.lan`, already in the SAN) → the iPad
caches the model ONCE, for every venue thereafter. Acceptance: change routers, scan, first take
warm with `model-cache hit` in the diag line.

## Phase D — Standard launch = installed home-screen app (PWA)

Manifest + icons already ship (Phase 5.7). Make **Add to Home Screen** the documented facilitator
launch: standalone window (no tab modes, no private-mode accidents), exempt from the 7-day eviction,
and the bedside icon requested back on 2026-05-31. Validate during Phase A′ that the standalone app
connects on the same network where normal-tab Safari failed (if Relay also intercepts standalone,
the Phase-A toggle is already the fix).

## Phase E — Validation gates

1. Normal tab (or PWA) loads where it failed tonight (L1 fixed, documented).
2. Reload → diag reads `model-cache hit` → **scan-to-first-warm-take <10 s** (L2 fixed).
3. Warm loop numbers unchanged (2.3–2.9 s, OPT-008 baseline).
4. Re-test after 24 h idle (eviction check) and after a router/IP change (origin check — full fix
   gated on Phase C).
5. `preflight.sh` prints the iPad-side checklist (private-address OFF · tracking-limit per Phase A ·
   launch from the home-screen app · `?swreset=1` if ever wedged).

## Effort & order
A (10–15 min, mostly user, next session) → B (S–M, same session, my side) → D (S) → C (rides the
FR-004 router purchase) → E throughout. Worst-case fallbacks if L1 resists all toggles: facilitators
launch from the installed app (D) — which is where we want them anyway — or per-site Safari
"Use Private Relay" off for the portal origin.
