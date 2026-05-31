"""Launch the medsim operator portal.

Environment variables:
  MEDSIM_HOST        Bind host (default 127.0.0.1). Set to 0.0.0.0 for LAN.
  MEDSIM_PORT        Bind port (default 8765).
  MEDSIM_NO_BROWSER  If set, don't auto-open a browser.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

HOST = os.environ.get("MEDSIM_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEDSIM_PORT", "8765"))

# TLS for tablet testing. When a dev cert exists (scripts/make-dev-cert.sh), the
# portal serves HTTPS — required so a tablet gets a *secure context* (WebGPU for
# the avatar skin, getUserMedia/Web Speech for push-to-talk). The vite app reads
# the same cert. No cert → plain HTTP, exactly as before.
_CERT_DIR = Path(__file__).resolve().parent / "portal" / "data" / "certs"


def _tls_files() -> tuple[str, str] | None:
    cert = os.environ.get("MEDSIM_TLS_CERT") or str(_CERT_DIR / "dev-cert.pem")
    key = os.environ.get("MEDSIM_TLS_KEY") or str(_CERT_DIR / "dev-key.pem")
    return (cert, key) if os.path.isfile(cert) and os.path.isfile(key) else None


# Durable device mode (ADR-0028): with VRAI_FACES_SERVE=portal the portal serves
# the BUILT avatar app from dist/, so the tablet loads the app + the api + the
# speech WebSocket all from ONE origin — one cert, no separate vite :5173, no
# cross-origin bind. Build dist once here if missing so it's a single command
# (`VRAI_FACES_SERVE=portal python3 run_portal.py`) with no separate build step.
_VRAI_CORE = Path(__file__).resolve().parent / "vrai-faces" / "packages" / "core"


def _find_node() -> str | None:
    node = shutil.which("node")
    if node:
        return node
    cand = Path.home() / ".local" / "node" / "current" / "bin" / "node"
    return str(cand) if cand.is_file() else None


def _ensure_vrai_app_built() -> str | None:
    """Build dist/ for portal-serve mode if it's missing. Returns a one-line
    status for the startup banner, or None when not in portal-serve mode."""
    if (os.environ.get("VRAI_FACES_SERVE") or "").strip().lower() != "portal":
        return None
    dist_index = _VRAI_CORE / "dist" / "index.html"
    if dist_index.is_file():
        return "portal serves the avatar app (one origin, one cert)"
    node = _find_node()
    vite_js = _VRAI_CORE / "node_modules" / "vite" / "bin" / "vite.js"
    pnpm = shutil.which("pnpm")
    if node and vite_js.is_file():
        cmd, cwd, tool_dir = [node, str(vite_js), "build"], _VRAI_CORE, os.path.dirname(node)
    elif pnpm:
        cmd, cwd, tool_dir = [pnpm, "-F", "@vrai/core", "build"], _VRAI_CORE.parents[1], os.path.dirname(pnpm)
    else:
        return ("VRAI_FACES_SERVE=portal but no node/pnpm found to build the app — "
                "run `pnpm -F @vrai/core build`, then restart")
    print("  Building the VRAI Faces app (one-time, ~10s)…")
    env = dict(os.environ)
    if tool_dir:
        env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"app build failed to launch ({exc}); run `pnpm -F @vrai/core build`"
    if result.returncode != 0 or not dist_index.is_file():
        tail = " / ".join((result.stderr or result.stdout or "").strip().splitlines()[-3:])
        return f"app build failed — run `pnpm -F @vrai/core build`. {tail}"
    return "built + serving the avatar app from this portal (one origin, one cert)"


def _lan_ip() -> str:
    """Best-effort LAN IP discovery — no traffic is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _open_in_chrome(url: str) -> bool:
    """Open URL specifically in Chrome (or Chromium). Returns True on success.

    Strategy:
      1. Python's webbrowser module — works if Chrome is registered.
      2. Platform-specific direct invocation:
         - macOS:   `open -a "Google Chrome" <url>`
         - Windows: spawn chrome.exe from common install paths.
         - Linux:   spawn the first chrome/chromium binary on PATH.

    Returns False if no Chrome could be found anywhere; caller should fall
    back to the system default browser.
    """
    # 1. webbrowser registered controllers
    for name in ("google-chrome", "chrome", "chromium"):
        try:
            controller = webbrowser.get(name)
            if controller.open(url):
                return True
        except webbrowser.Error:
            continue

    system = platform.system()

    if system == "Darwin":
        for app in ("Google Chrome", "Chromium"):
            try:
                result = subprocess.run(
                    ["open", "-a", app, url],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    elif system == "Windows":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(program_files) / "Google/Chrome/Application/chrome.exe",
            Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
        ]
        if localappdata:
            candidates.append(Path(localappdata) / "Google/Chrome/Application/chrome.exe")
        for path in candidates:
            if path.exists():
                try:
                    subprocess.Popen([str(path), url])
                    return True
                except OSError:
                    continue
        # Last resort: `start chrome` via shell
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", "chrome", url],
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

    elif system == "Linux":
        for cmd in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            if shutil.which(cmd):
                try:
                    subprocess.Popen([cmd, url])
                    return True
                except OSError:
                    continue

    return False


def _open_browser() -> None:
    if os.environ.get("MEDSIM_NO_BROWSER"):
        return
    time.sleep(1.5)
    scheme = "https" if _tls_files() else "http"
    url = f"{scheme}://127.0.0.1:{PORT}"
    if _open_in_chrome(url):
        print("  → Opened in Chrome.")
    else:
        print("  → Chrome not found — opening system default browser.")
        webbrowser.open(url)


def main() -> None:
    # Anchor the working directory to this script's location so uvicorn's
    # "portal.server:app" import string resolves to THIS clone's portal
    # package, regardless of where the launcher (or Claude Preview) is
    # invoked from. Without this, running run_portal.py from a foreign
    # cwd silently picks up whichever 'portal' package is on sys.path.
    os.chdir(Path(__file__).resolve().parent)

    # Build the avatar app first if we're in portal-serve mode — uvicorn imports
    # portal.server below, which only registers the app routes when dist/ exists.
    vrai_serve_status = _ensure_vrai_app_built()

    tls = _tls_files()
    scheme = "https" if tls else "http"
    lines = ["", "  medsim v7 · operator portal · multi-patient + devices + control + debrief", ""]
    if tls:
        lines.append("  TLS:       on (dev cert) — trust portal/data/certs/rootCA.pem on each tablet")
    if vrai_serve_status:
        lines.append(f"  Avatar:    {vrai_serve_status}")
    lines.append(f"  Local:     {scheme}://127.0.0.1:{PORT}")
    if HOST in ("0.0.0.0", "::"):
        lan = _lan_ip()
        lines.append(f"  LAN/iPad:  {scheme}://{lan}:{PORT}")
        lines.append("")
        lines.append("  On iPad/iPhone: open the LAN URL in Safari,")
        lines.append("  then Share → Add to Home Screen for an app-like shortcut.")
    lines.append("")
    lines.append("  Vault:     ~/.medsim/vault.enc")
    lines.append("  Browser:   Chrome (auto-launch); set MEDSIM_NO_BROWSER=1 to disable")
    lines.append("  Stop:      Ctrl+C")
    lines.append("")
    print("\n".join(lines))

    threading.Thread(target=_open_browser, daemon=True).start()
    tls = _tls_files()
    ssl_kwargs = {"ssl_certfile": tls[0], "ssl_keyfile": tls[1]} if tls else {}
    try:
        uvicorn.run(
            "portal.server:app",
            host=HOST,
            port=PORT,
            reload=False,
            log_level="info",
            **ssl_kwargs,
        )
    except KeyboardInterrupt:
        print("\n  Portal stopped.")


if __name__ == "__main__":
    main()
