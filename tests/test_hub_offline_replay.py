"""V8 hub_adapter self-tests (vendored from the integration hub, note #0003) — the important one is
offline durability + exactly-once replay across a simulated restart with a flaky network. No real
network used. The adapter is feature-flag OFF by default (HUB_ADAPTER_ENABLED); nothing in the
portal calls it yet, so vendoring it changes no behavior."""
import tempfile

from portal.hub_adapter import contract, mappers
from portal.hub_adapter.queue import Spool


def test_mapper_valid_and_phi_free():
    evt = mappers.session_event(type="session.started", session_id="s1",
                                station={"station_id": "m1", "kind": "manikin",
                                         "modality": "mid_fidelity", "vendor": "laerdal"})
    assert contract.validate_envelope(evt) == []
    assert evt["tenant_id"] == "v8-local"


def test_offline_then_restart_then_replay_exactly_once():
    with tempfile.TemporaryDirectory() as d:
        # enqueue 3 events while "offline"
        s1 = Spool(d)
        ids = []
        for i in range(3):
            e = mappers.session_event(type="session.started", session_id=f"s{i}")
            ids.append(e["event_id"]); s1.enqueue(e)
        assert s1.depth() == 3

        # simulate process restart: brand-new Spool on the same dir re-reads the queue
        s2 = Spool(d)
        assert s2.depth() == 3

        delivered, calls = [], {"n": 0}
        def flaky(evt):
            calls["n"] += 1
            if calls["n"] == 1:          # first network attempt fails
                raise ConnectionError("offline")
            delivered.append(evt["event_id"]); return True

        first = s2.replay(flaky)         # fails immediately -> nothing acked, nothing lost
        assert first == 0 and s2.depth() == 3
        second = s2.replay(flaky)        # reconnected -> all three flush, in order
        assert second == 3 and s2.depth() == 0
        assert delivered == ids          # exactly-once, original order preserved


def test_corrupt_file_is_skipped_not_fatal():
    with tempfile.TemporaryDirectory() as d:
        s = Spool(d)
        s.enqueue(mappers.session_event(type="session.ended", session_id="s9"))
        (s.dir / "00000000000000000001-bad.json").write_text("{not json")
        sent = s.replay(lambda e: True)
        assert sent == 1 and s.depth() == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("ok", fn.__name__)
    print(f"\n{len(fns)} V8 adapter tests passed")
