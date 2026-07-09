"""V8 hub_adapter self-tests (vendored from the integration hub, note #0003) — the important one is
offline durability + exactly-once replay across a simulated restart with a flaky network. No real
network used. The adapter is feature-flag OFF by default (HUB_ADAPTER_ENABLED); nothing in the
portal calls it yet, so vendoring it changes no behavior."""
import json
import tempfile
import threading

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


def test_identity_cache_soft_expires_offline(monkeypatch, tmp_path):
    """Offline, a FRESH cached identity is served; a STALE one (past the soft max-age) is dropped to
    {} so the caller falls to the local vault seat — a revoked-but-stale HIGHER role can't persist."""
    import time as _t

    from portal.hub_adapter import config, consume
    monkeypatch.setattr(config, "ENABLED", True)
    monkeypatch.setattr(config, "CACHE_MAX_AGE_S", 100.0)
    cache_file = tmp_path / "hub_identity_cache.json"
    monkeypatch.setattr(consume, "_CACHE_FILE", cache_file)
    monkeypatch.setattr(consume.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))

    cache_file.write_text(json.dumps(
        {"op1": {"primary_role": "ORG-ADMIN", "status": "active", "_cached_at": _t.time()}}))
    assert consume.identity("op1").get("primary_role") == "ORG-ADMIN"   # fresh → served

    cache_file.write_text(json.dumps(
        {"op1": {"primary_role": "ORG-ADMIN", "status": "active", "_cached_at": _t.time() - 1000}}))
    assert consume.identity("op1") == {}                                # stale → drop to local seat


def test_emit_async_offloads_delivery(monkeypatch, tmp_path):
    """With EMIT_ASYNC, an emit enqueues durably and delivers on a BACKGROUND thread — never the
    caller's — so a slow/unreachable authority cannot block the login/request path."""
    from portal.hub_adapter import config
    from portal.hub_adapter import emit as emit_mod
    monkeypatch.setattr(config, "ENABLED", True)
    monkeypatch.setattr(config, "EMIT_ASYNC", True)
    monkeypatch.setattr(emit_mod, "_spool", Spool(str(tmp_path / "q")))
    main_tid = threading.get_ident()
    seen, done = [], threading.Event()

    def sender(evt):
        seen.append(threading.get_ident()); done.set(); return True
    monkeypatch.setattr(emit_mod, "_online_sender", sender)

    emit_mod.audit(actor="admin", action="portal.login")   # must not block on the sender
    assert done.wait(3), "background replay never ran"
    assert seen and seen[0] != main_tid                    # delivered OFF the caller's thread


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("ok", fn.__name__)
    print(f"\n{len(fns)} V8 adapter tests passed")
