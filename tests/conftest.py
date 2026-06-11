"""Test-process hygiene. Loaded before any test module imports portal.server."""
import os

# ADR-0038: importing portal.server normally spawns a daemon thread that warms
# the room-STT whisper model (~250 MB resident, seconds of load). In tests the
# engine is stubbed — keep the real model out of the test process entirely
# (it once clobbered a stub mid-test via the module-global engine slot).
os.environ.setdefault("MEDSIM_STT_WARM", "0")
