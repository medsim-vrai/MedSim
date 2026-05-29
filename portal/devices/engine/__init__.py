"""Layer A — shared device engine. Each module is one concern:

- ``state_machine`` — base ``DeviceEngine`` with dispatch/inject/fold/tick.
- ``alarms``        — alarm catalog + playback rules (shared library).
- ``persistence``   — thin wrapper writing through ehr_db.append_device_event.
"""
