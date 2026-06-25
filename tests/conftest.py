"""Test-process hygiene. Loaded before any test module imports portal.server."""
import os

# ADR-0038: importing portal.server normally spawns a daemon thread that warms
# the room-STT whisper model (~250 MB resident, seconds of load). In tests the
# engine is stubbed — keep the real model out of the test process entirely
# (it once clobbered a stub mid-test via the module-global engine slot).
os.environ.setdefault("MEDSIM_STT_WARM", "0")

# FR-011 G1 resume-on-boot would otherwise let a room persisted by one test be
# auto-restored when a later test constructs TestClient(server.app) — leaking an
# "active room" into tests that assert there is none. Default resume OFF for the
# whole test process (individual tests already do this ad hoc); tests that want
# resume can still opt in via monkeypatch.setenv.
os.environ.setdefault("MEDSIM_RESUME", "0")
