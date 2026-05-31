# VRAI Faces — Fleet Network Strategy

**Status:** Active design · 2026‑05‑31 · see ADR‑0030
**Scope now (development / internal pilot):** one site, multiple rooms, ~15–60 devices, **our own AP/router**, **MDM‑managed** tablets.
**Scope next (deployment / sales):** 60+ devices, permanent and/or multi‑site. Called out throughout as **→ Option 3**.

This is the durable answer to the class of failure we hit repeatedly (the avatar
"binding fetch failed", "connection not secure", and finally a tablet that could
not reach the Mac at all because it was on a range‑extender's separate
`192.168.1.x` LAN). None of those were app bugs — they were the **network**. The
system assumes every device shares **one flat, mutually‑reachable, secure LAN**,
and uncontrolled networks break that assumption. So we own the layers that matter.

---

## 1. The failure class we are designing against

| Failure | What it looks like | Why it kills us |
|---|---|---|
| Client/AP isolation | Same subnet, devices can't ping each other | Tablet can't reach the portal |
| Range‑extender / double‑NAT | Same `192.168.1.x` + `.1` gateway, **different physical LAN** | Tablet talks to the extender, never the portal (today's bug) |
| Guest network | Internet‑only, LAN blocked | Same as isolation |
| Band‑steering / multi‑AP splits | Devices land on different APs that don't bridge | Intermittent reachability |
| Captive portal | All traffic redirected to a login page | "RouterNetwork.com" instead of the app |
| DHCP IP churn | Host IP changes on lease renewal | Breaks the cert SAN **and** any baked‑in QR/URL |
| Non‑secure context | Plain HTTP on a LAN IP | No WebGPU / mic / `crypto.subtle` (ADR‑0027) |

**Conclusion:** never depend on a network we don't control. Bring our own, give the
portal a stable *name* (not an IP), and distribute trust + config by MDM.

---

## 2. Design principles

1. **Own the L2 network.** One dedicated SSID, isolation OFF, no extenders/double‑NAT, our DHCP + DNS.
2. **Address by name, not IP.** The portal is `portal.medsim.lan`; the cert and every URL/QR use the name. DHCP can move the IP without breaking anything.
3. **Trust + config by MDM.** The Root CA, the Wi‑Fi profile, and the app icon are *pushed*, not hand‑installed. This is what makes today's manual pain disappear at scale.
4. **Single origin (ADR‑0028).** The portal serves the app + API + speech WS on one host/cert (`VRAI_FACES_SERVE=portal`).
5. **Contain PHI at the network layer (ADR‑0001/0014).** Devices can reach the portal and nothing else; the portal reaches only Anthropic (BAA) outbound; mic/STT stays on‑device (ADR‑0026).
6. **Reproducible.** The whole site config is a saved blueprint (controller export + DHCP/DNS templates + MDM profiles), so a new site is a checklist, not a redesign.

---

## 3. Reference architecture — Option 2 (now)

### 3.1 Topology + bill of materials
A **controller‑managed** Wi‑Fi system (one pane of glass, scales straight into Option 3). Reference build = Ubiquiti UniFi; TP‑Link **Omada** and **Aruba InstantOn** are equivalent‑class alternatives. **Avoid consumer mesh/Wi‑Fi extenders entirely** — they are the exact cause of today's outage.

| Role | Dev / Option 2 pick | Notes |
|---|---|---|
| Gateway/router (DHCP, DNS, firewall, controller) | UniFi Cloud Gateway (e.g. UCG‑Ultra / Dream Router) | Built‑in controller + local DNS records |
| PoE switch | 8‑port PoE (e.g. USW‑Lite‑8‑PoE) | Powers APs, wires the portal host |
| Access points | 2–4× Wi‑Fi 6 APs (U6+/U6‑Pro/U7) | One per ~1–2 rooms; controller handles roaming |
| Portal host | **Wired** Mac mini / NUC (dev: the MacBook via USB‑C→Ethernet) | Never on Wi‑Fi |
| Power | UPS on gateway + switch + host | Ride out blips |

### 3.2 Addressing, DNS, identity (kills the IP/cert churn)
- **Subnet:** `10.50.10.0/24` — deliberately *not* `192.168.0/1.x`, to avoid colliding with venue gear or a stray extender. Gateway `10.50.10.1`.
- **Portal:** DHCP **reservation** → `10.50.10.10`, hostname **`portal.medsim.lan`** via the gateway's local DNS (A‑record). DHCP pool `…100–…250` for devices.
- **Everything points at the name.** The cert, the QR, the app's `api` origin = `https://portal.medsim.lan:8765`. An IP change never breaks the cert again (it's issued for the name).
- mDNS/`.local` is *unreliable* across Android Chrome — use the gateway's **real local DNS** as primary; mDNS only as a bonus.
- **Port:** `:8765` for dev. **→ Option 3:** serve on **443** (standard HTTPS) via a local reverse proxy or privileged bind, so no non‑standard port is ever filtered and URLs drop the `:8765`.

### 3.3 Wi‑Fi config
- **One SSID** (e.g. `MedSim`), WPA2‑PSK for dev. **Client isolation OFF.** 2.4 + 5 GHz under one SSID on one VLAN (bridged — cross‑band devices still reach the portal). Fast roaming (802.11k/v/r) ON for multi‑room.
- A separate hidden **ops** SSID for the facilitator laptop is optional.
- **→ Option 3:** WPA2/WPA3‑**Enterprise** with per‑device certs issued by MDM (no shared PSK to leak), and a dedicated **device VLAN**.

### 3.4 Firewall / PHI boundary (ADR‑0001/0014)
- Device subnet → **portal host only** (`10.50.10.10:8765` + WS). 
- Device subnet → **internet: BLOCK** (the app + models are served by the portal and cached; trainee PHI cannot leave the LAN).
- Portal host → **internet: allow outbound 443 to Anthropic only** (the BAA‑covered AI‑turn path; trainee free‑text is PHI and only a BAA provider may receive it).
- **Data flow:** mic → on‑device STT → text → portal (LAN) → Anthropic (BAA) → reply text → portal → device WS → on‑device TTS. The *only* off‑LAN hop is portal↔Anthropic. Mic audio never leaves the device (ADR‑0026).
- If a site forbids the portal any internet, the AI turn degrades to echo mode — flag it; an on‑prem LLM is the future mitigation.

### 3.5 Portal serving
- Run in **single‑origin mode**: `VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 python3 run_portal.py` (ADR‑0028). App + API + WS on one host/cert.
- **Wired**, **autostart on boot** (launchd/systemd service), on UPS.
- uvicorn sizing: each device holds one speech WS + bursts of binding/listen; per‑session wire traffic is light because compute is on‑device. Run with a couple of workers and **load‑test before Option 3** (see §6).

### 3.6 Certificates (trust pushed by MDM)
- Keep the existing internal **Root CA** (ADR‑0029); the re‑mint guard stays (re‑minting invalidates fleet trust). 
- Leaf issued for **`portal.medsim.lan`** (+ SAN for `10.50.10.10`), ≤398‑day validity, **auto‑renewed** by a scheduled job that reissues the leaf and reloads uvicorn.
- **MDM pushes the Root CA** to every device's **managed/system** trust store — on Android this avoids the "user CA" caveats that bit us, and on iOS the managed profile grants full trust. No per‑device manual trust, ever.
- **→ Option 3:** replace the hand‑rolled CA with **`step‑ca`** (internal ACME → automatic issue/renew), *or* — best for sales — a **publicly‑trusted** cert on a real domain with **split‑horizon DNS** (`portal.medsim.example.com` → the LAN IP internally), which removes CA distribution **entirely** (devices already trust public roots).

### 3.7 Device provisioning (MDM)
One enrollment pushes everything; a new tablet is plug‑and‑play:
1. **Wi‑Fi profile** — SSID + creds, auto‑join.
2. **Trusted Root CA** — managed trust (Configuration Profile / Intune Trusted‑Cert / Android Enterprise CA).
3. **App** — a **Web Clip / managed PWA** (and/or kiosk single‑app mode) pointing at `https://portal.medsim.lan:8765/…`.
4. **Permissions** — pre‑grant mic where the platform allows (Android Enterprise managed config); on iOS web clips the user grants mic once.
5. Optional **kiosk/single‑app lock** for bedside tablets.

### 3.8 Acceptance test (prove a site is correct before a session)
From a freshly‑enrolled device, all must pass:
- [ ] Resolves `portal.medsim.lan` and loads the app with a **trusted** lock (no warning).
- [ ] Speech **WS connects**; PTT → transcript → avatar **replies** (real AI, not echo).
- [ ] **Two** devices + the portal are mutually reachable (isolation truly off).
- [ ] Device **cannot** reach the internet; portal **can** reach Anthropic.
- [ ] `scripts/cert-doctor.sh` green; leaf valid > 30 days.

---

## 4. Operations & resilience
- Portal: boot‑autostart service, wired, UPS; cert auto‑renew cron; a fleet health check (extend `cert-doctor` into a "site‑doctor" that also checks DNS, reachability, and the egress rules).
- Gear: UPS on gateway+switch; **spare AP** on the shelf; **export the controller config** as the known‑good snapshot.
- Monitoring: controller client/health view; portal logs; a simple "devices connected / sessions active" readout.
- **Runbook** (printed): power‑on order, "add a device" (MDM enroll), verify (acceptance test), and recovery steps.

---

## 5. Transition to Option 3 (deployment / sales) — detailed notations
Everything above is built so this is an *expansion*, not a redo:

1. **PKI / trust.** Move to `step‑ca` (ACME auto‑renew) **or** public cert + split‑horizon DNS (zero CA install — the strongest sales story). Decide early; it changes provisioning.
2. **Segmentation.** Dedicated **device VLAN**, **server VLAN**, **mgmt VLAN**; inter‑VLAN firewall rule = *fleet → portal only*, *portal → Anthropic only*.
3. **Enterprise Wi‑Fi.** WPA2/WPA3‑Enterprise with **per‑device certificates** from MDM (no shared PSK); more APs with real RF planning + roaming.
4. **Serving.** Portal on **443**; consider a **reverse proxy** (TLS termination, multiple workers), and **load‑test** concurrency (target the real per‑site device count × active‑session ratio).
5. **Host.** Dedicated server (not a laptop); consider **per‑site portal** so each site is self‑contained and offline‑tolerant; evaluate redundancy/HA.
6. **First‑load at scale.** 60+ devices first‑loading the app+models at once is the one real bandwidth spike (per‑session traffic is otherwise light because compute is on‑device). Mitigate: **pre‑cache during MDM staging**, **bundle models locally** (so nothing hits the internet), and stagger rollout. Consider a LAN cache for the static bundle.
7. **Site kit / IaC.** Package gateway + switch + APs + server as a standardized **site kit** with a reproducible config (controller export, DHCP/DNS templates, `step‑ca` config, MDM blueprint) → a turnkey, repeatable deployment for sales.
8. **Naming at scale.** Per‑site DNS (`portal.<site>.medsim.lan`) or a consistent `portal.medsim.lan` on each isolated site network.
9. **Support.** Monitoring/alerting per site, remote health, and an escalation runbook.

---

## 6. Open decisions / things to validate
- **Cert model for Option 3:** internal `step‑ca` vs public‑cert + split‑horizon DNS. (Recommend public‑cert for sales — no CA distribution.)
- **Concurrency:** load‑test the portal at the real per‑site device count before committing host specs.
- **Per‑MDM specifics:** the exact CA + Wi‑Fi + Web‑Clip payloads differ across Jamf / Intune / Android Enterprise — confirm against the chosen MDM.
- **No‑internet venues:** decide the AI fallback (echo now; on‑prem LLM later).
- **Port 443 vs 8765:** move to 443 for the cleanest URLs and to dodge port filters.

---

## 7. Software changes this strategy needs (our side)
Tracked separately; the network design above assumes these land:
1. **Hostname support — ✅ DONE (2026‑05‑31).** `MEDSIM_PUBLIC_HOST` (e.g. `portal.medsim.lan`) makes the portal's QR/URL builders (`_base_url_for_qr`, `_vrai_base_for_qr`) target the NAME instead of the auto‑detected LAN IP. Opt‑in: unset = prior LAN‑IP behavior. The structural fix to IP/cert churn between locations.
   - **Activate (dev):** `make-dev-cert.sh` auto‑adds `MEDSIM_PUBLIC_HOST` to the cert SAN; for the Mac to reach itself by name add `127.0.0.1 portal.medsim.lan` to `/etc/hosts`; then run with `MEDSIM_PUBLIC_HOST=portal.medsim.lan` and **restart the portal** to serve the refreshed cert. For devices, the gateway DNS must map the name → the portal's reserved IP.
2. **Cert for the hostname — ✅ DONE.** `make-dev-cert.sh` issues the leaf for the name (auto‑includes `MEDSIM_PUBLIC_HOST`) alongside the IP SANs. _Remaining:_ an auto‑renew job (re‑issue < 398d + reload uvicorn).
3. **Site‑doctor — ◐ seeded.** `cert-doctor.sh` now also checks the hostname is in the SAN and resolves on this machine. _Remaining:_ portal reachability + egress‑rule checks for a full per‑site preflight.
4. (Carries existing) single‑origin serving (ADR‑0028), CA re‑mint guard (ADR‑0029), on‑device STT bundling (ADR‑0026 follow‑up).

---

## 8. Researched BOM + config specifics (deep‑research, 2026‑05‑31)
Run `wwusvbr4p` (114 agents, 31 sources, 23 verified claims). **Verified** = vendor‑doc‑cited and adversarially confirmed. **Analysis** = my reasoning to fill a gap the research left open — verify on‑device before shipping.

### 8.1 Networking — VERIFIED
- **Recommended: UniFi** — strongest fit because the gateway natively binds a local DNS **Host (A)** record to a **DHCP reservation** in one step ("Fixed IP Address" + "Local DNS Record"), which is exactly the stable‑hostname design. Local hostnames resolve **only** for clients using the gateway as DNS (DHCP hands that out by default — works cleanly; keep Content/Domain Filtering OFF on the device subnet). [help.ui.com/15179064940439]
  - **Gateway:** UniFi Cloud Gateway (UCG‑Ultra ≈ $129). Local DNS at Settings → Policy Table → DNS → Host (A) (Network 9.4).
  - **APs:** **U6 Pro ≈ $159 ea** — Wi‑Fi 6 dual‑band (NOT 6E/no 6 GHz), per‑SSID **802.11r/k/v** toggles, dynamic‑VLAN capable. Size by **room coverage** at **~20–30 active tablets/AP** (the "250+/AP" figure was **refuted 0‑3** — do not size by it) → **2–4 APs** for 15–60 across rooms. [techspecs.ui.com/unifi/wifi/u6-pro]
  - **Switch:** USW‑Lite‑8‑PoE (≈ $109) → USW‑24‑PoE (≈ $379) by room count.
  - **Config musts:** per‑SSID **"Client Device Isolation" OFF** (default OFF on *standard* — non‑guest — networks; only blocks same‑AP east‑west, cross‑AP is the VLAN "Network Isolation" setting). **Do NOT enable Switch Port Isolation alongside 802.11r** — documented conflict; keep Fast Roaming ON. [help.ui.com/32065480092951]
  - **Dev BOM ≈ $600–1,150** (medium confidence on line items beyond the U6 Pro).
- **Alternative: TP‑Link Omada (cheaper)** — **ER605** router (≈ $60–70): DHCP reservation, 802.1Q VLAN, **LAN→WAN deny/permit ACLs** (permit portal host : TCP 443, deny fleet → PHI containment at the gateway), 802.11r per‑SSID on Controller **6.2+**. **Leave "SSID Isolation" OFF and NEVER set the SSID as a "Guest Network"** — Guest blocks all client‑to‑client *and* all private‑subnet (10/172.16/192.168) access: the exact breakage we hit. [omadanetworks.com/.../er605, support.omadanetworks.com/12928]
- **Alternative: HPE Aruba** — client isolation = **"Deny Intra VLAN Traffic"** (leave OFF). Standalone Aruba Instant 802.11r needs a **manually‑matched MDID** on every AP. [arubanetworking.hpe.com]

### 8.2 MDM — VERIFIED
- **iOS/iPadOS: a CA deployed via MDM / enrollment profile is AUTO‑trusted for SSL/TLS — NO manual trust step** (best practice: bundle the cert in the enrollment profile). The manual "Enable Full Trust" toggle only applies to certs installed via email/web. [support.apple.com/102390]
- **Intune:** deploy the root via a **"Trusted certificate"** profile (Devices → Configuration → Create → Trusted certificate). [learn.microsoft.com, updated 2026‑04]
- **Browser‑layer PHI containment** (Android Enterprise COBO/COSU, managed Chrome via Intune **app configuration policy**): `URLBlocklist=["*"]` + `URLAllowlist=["<portal host>"]` locks the fleet to the portal origin. Complements — does not replace — the VLAN/firewall network containment; use both. [learn.microsoft.com, updated 2026‑04]

### 8.3 Gaps the research flagged — ANALYSIS (verify on‑device before shipping)
- **Mic pre‑grant (Android, load‑bearing):** use managed‑Chrome enterprise policy `AudioCaptureAllowed` + `AudioCaptureAllowedUrls=["<portal origin>"]` (via Intune app config) to grant the mic to the portal **without a prompt**. (Policy exists — chromeenterprise.google/policies/audio-capture-allowed-urls — but persistence under kiosk was not workflow‑confirmed.)
- **Android CA → site TLS:** Chrome on Android requires Certificate Transparency only for **publicly‑trusted** roots, **not** locally/MDM‑installed roots → a private MDM‑pushed CA works for site TLS. Confirm on the target Android version.
- **iPadOS Safari Web Clip mic persistence is weaker than Android** (may re‑prompt) → a reason Android is primary; the Capacitor‑native wrapper is the iOS fallback.
- **Name resolution:** a real local **DNS A‑record (chosen)** is the safe path — do **not** rely on mDNS/`.local` on Android.
- **Port:** `:8765` works in browsers; **443** is cleaner (no port in the QR) and dodges rare proxy/port filters — move to 443 for Option 3.
- **HSTS:** a trusted private cert gives a full secure context; just don't enable HSTS **preload**.

### 8.4 OPEN — needs a focused follow‑up before committing
- **Cert decision (C) — NOT resolved by the workflow.** Reasoned lean: **internal ACME (step‑ca)** for the MDM‑managed / PHI / air‑gap‑capable case (CA distribution is "free" via MDM, zero external dependency); **public‑cert + DNS‑01 + split‑horizon DNS** for zero‑CA‑distribution / BYOD / cleanest sales optics (needs a domain + outbound to the DNS+ACME API at each site). Industry context: TLS lifetimes are dropping toward **~47 days** → **automate renewal regardless of path**. Confirm with dedicated research. [smallstep.com, digicert.com, letsencrypt.org]
- Also unconfirmed here: Jamf Pro payload names, Wi‑Fi auto‑join profiles (PSK + WPA2/3‑Enterprise) across all three MDMs.
