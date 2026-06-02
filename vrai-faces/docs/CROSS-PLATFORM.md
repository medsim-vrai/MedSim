# Cross-platform support — hosts (Mac / Windows) × devices (iPad / Android)

VRAI Faces is built to run on **either host OS** and **either tablet platform**.
The app is a web/PWA and the portal is Python/FastAPI, so the core is inherently
portable; this doc captures the few per-platform steps.

| Layer | Supported | Notes |
|---|---|---|
| **Host (portal)** | macOS · Windows · Linux | `run_portal.py` already branches per OS (browser launch). Cert tooling is cross-platform via `scripts/dev_cert.py`. |
| **Device (avatar)** | iPad (Safari 26 / iPadOS 26) · Android (Chrome 121+, Android 12+) | WebGPU on both (ADR-0032). Same PWA; trust the CA + scan the QR. |
| **Initial test combo** | **Mac host + iPad device** | The first validation pair (ADR-0032). Android + Windows are first-class, just validated next. |

---

## Host setup

Same three steps on every OS — only the **cert-trust** command and the
**env-var syntax** differ. Use your virtualenv's Python (`/.venv/bin/python` on
macOS/Linux, `.venv\Scripts\python.exe` on Windows).

### 1. Generate the dev TLS cert (cross-platform)

```bash
python scripts/dev_cert.py                      # issue/refresh the leaf (reuses the CA)
python scripts/dev_cert.py --host portal.medsim.lan   # add a stable hostname to the SAN
python scripts/dev_cert.py doctor               # read-only diagnosis (cert/chain/SAN/trust)
```

`dev_cert.py` is the portable twin of `make-dev-cert.sh`/`cert-doctor.sh` (uses the
declared `cryptography` dep — no openssl/bash needed on Windows). The **CA is
mint-once** (ADR-0029): reissuing only replaces the leaf, so trusted devices stay
trusted. macOS users may still use `scripts/make-dev-cert.sh` — both produce the
same files. **Always pass `--host` / set `MEDSIM_PUBLIC_HOST` when reissuing**, or
the leaf drops that name from its SAN (the doctor flags this).

### 2. Trust the root CA (a system-security step you run yourself)

| Host | Command |
|---|---|
| **macOS** | `sudo scripts/trust-ca-mac.sh` → then fully quit + reopen Chrome |
| **Windows** | `pwsh -File scripts/trust-ca-windows.ps1` **(Run as Administrator)** → reopen Chrome/Edge |
| **Linux** | `sudo cp portal/data/certs/rootCA.pem /usr/local/share/ca-certificates/medsim.crt && sudo update-ca-certificates` |

### 3. Launch the portal (device-serve mode)

Set three env vars + run `run_portal.py`. TLS turns on automatically once the cert exists.

```bash
# macOS / Linux (bash/zsh)
VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 MEDSIM_NO_BROWSER=1 python run_portal.py
```
```powershell
# Windows PowerShell
$env:VRAI_FACES_SERVE='portal'; $env:MEDSIM_HOST='0.0.0.0'; $env:MEDSIM_NO_BROWSER='1'; python run_portal.py
```
```bat
:: Windows cmd.exe
set VRAI_FACES_SERVE=portal&& set MEDSIM_HOST=0.0.0.0&& set MEDSIM_NO_BROWSER=1&& python run_portal.py
```

`VRAI_FACES_SERVE=portal` (ADR-0028) serves the app + API + speech WS from one
origin/one cert. Omit it only when developing the app with HMR (the vite dev server).

---

## Device setup (iPad and Android are the same flow)

1. Put the tablet on the **same flat LAN** as the host (ADR-0030).
2. **Trust the CA:** open `https://<host>:8765/rootca.pem` and install it as a
   **CA certificate**.
   - **iPad:** Settings → General → VPN & Device Management → install the profile,
     then Settings → General → About → **Certificate Trust Settings** → enable full
     trust for "MedSim Dev Local CA". (iOS requires this second toggle.)
   - **Android:** Settings → Security → Encryption & credentials → Install a
     certificate → **CA certificate**.
3. Scan the character's device **QR** (or Add to Home Screen for the PWA icon).
   Grant the microphone prompt once.

### Platform differences already handled in the app
- **Audio unlock** — `firstGesture` primes the Web Audio context on first tap (iOS requires this).
- **STT runtime** — WebGPU first on both; the WASM fallback picks the Safari vs Chrome ORT build automatically.
- **Speech APIs** — `SpeechRecognition ?? webkitSpeechRecognition`; `AudioContext ?? webkitAudioContext`.
- **PWA install** — iOS uses the `apple-touch-icon` + `apple-mobile-web-app-*` meta tags; Android uses the web manifest. Both present.
- **iPadOS UA quirk** — iPad Safari reporting a desktop-Mac UA is fine: it still resolves to the Safari/WebKit code path.

---

## Validation note (ADR-0032)
The on-device pilot runs the **iPad first**, then a **Snapdragon/Adreno Android**
(NOT Exynos/Xclipse). Same `PILOT-2026-05-30-on-device.md` protocol on each. The
host for the pilot is the Mac; a Windows host follows the steps above identically.
