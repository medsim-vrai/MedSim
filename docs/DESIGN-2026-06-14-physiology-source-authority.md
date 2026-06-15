# DESIGN — Physiology Source Authority & Manikin Sync

**Date:** 2026-06-14 · **Status:** evaluation (informs FR-012 **D2**) · **Decision:** Option B, as a lease
**Context:** user directive — "have a baseline engine that drives each virtual patient character. In case
of a manikin with a localized engine, either (A) use the manikin engine with the virtual as backup, or
(B) synchronize the two so the manikin engine drives local haptics (reducing latency) and acts as a data
backup if links are lost and regained. The latter should be more robust. Take time and evaluate."

---

## 1. The problem

A patient can have **up to three producers of physiology at once**:

1. **v8 baseline engine** — a lightweight portal-side model (FR-012 D2). Always present; drives purely
   virtual patients (avatars / tablet monitors).
2. **PhysioBridge** — a networked high-fidelity engine (Pulse-based) on the LAN, when present.
3. **Manikin onboard engine** — a physical manikin that runs its own physiology and drives **haptic
   actuators** (palpable pulse, chest rise, breath/heart sounds), when a manikin is in the scenario.

If more than one tries to be "the truth" for the same patient, vitals diverge and consumers (bedside
monitor, instructor console, remote monitors, debrief) see conflicting numbers. The question is how the
**virtual engine and a manikin engine** relate. The same answer must also cover PhysioBridge.

## 2. Forces

| Force | Implication |
|---|---|
| **Single source of truth** | Two engines compute different numbers → exactly **one authoritative writer** per consumer-domain at any instant. |
| **Haptic latency** | Palpable pulse / chest rise must track physiology with no perceptible lag; a bedside→portal→bedside round-trip (50–300 ms+, dies on dropout) is unacceptable → **haptics computed bedside-locally**. |
| **Partition tolerance** | Sim-center Wi-Fi drops (cf. the whole router saga). The manikin must keep running bedside **and** the remote side (instructor/monitors/debrief) must keep running → **both sides must run physiology during a partition**. |
| **Reconciliation** | After a heal the two have diverged → need a **deterministic winner + back-fill** of dropout-period telemetry (no data loss). |
| **Forward-compat** | PhysioBridge and a manikin are both just higher-fidelity sources → the abstraction must generalize. |

## 3. Options

- **A — Manikin authoritative, virtual cold backup.** Simple. But remote consumers **freeze during a
  manikin dropout**; failover is a hard cutover with a visible gap. Least robust remotely.
- **B — Synchronized peers (lease + reconcile).** Manikin is authoritative and drives haptics locally;
  the virtual engine runs as a **hot shadow**; on dropout the virtual serves remote consumers while the
  manikin runs **bedside-autonomously**; on heal the bedside reasserts and the virtual snaps to it, with
  dropout telemetry back-filled. Robust on **both** sides of a partition, low-latency, single-writer per
  domain. More complex. **← user's instinct; correct.**
- **C — Virtual authoritative, manikin a dumb actuator.** Manikin haptics lag and freeze on dropout.
  Worst bedside. Rejected.

## 4. Recommendation — Option B as a "PhysiologySource authority lease"

Design D2 around a **`PhysiologySource`** abstraction with a **single-writer authority lease** per patient:

- **Sources rank by fidelity/locality:** `manikin (bedside HF)` > `physiobridge (networked HF)` >
  `virtual baseline (always-on floor)`.
- **One lease per patient.** The highest-precedence *healthy* source holds it and is the **only writer**
  to v8's `vitals.record` event log. (Everyone else is a shadow.)
- **Virtual baseline = always-on hot shadow.** It continuously mirrors the lease-holder's published state
  (assume-authority within one tick) and is the **default** authority when no HF source is present.
- **Bedside autonomy:** a manikin **always** computes its own haptics locally, never gated on the network.
- **On link loss:** the lease **fails over to the virtual shadow** for remote consumers; the manikin
  **continues autonomously** for bedside; both **buffer** telemetry (append-only, idempotent).
- **On heal:** the bedside source **reasserts** the lease (precedence); the virtual shadow **reconciles
  (snaps)** to it; the buffered bedside telemetry is **back-filled** into the event log with idempotent
  `seq`/ULID dedup (the same fold model v8 and PhysioBridge already use). **No data lost; debrief is
  continuous.**

This **subsumes Option A** (A = "the lease never fails over"), realizes the user's **Option B** with a
precise authority/reconciliation contract, and treats **PhysioBridge and manikins uniformly** as sources.

```
        consumers (bedside monitor · instructor console · remote monitors · debrief)
                                   ▲ single writer
                          ┌────────┴─────────┐  authority lease (per patient)
            ┌─────────────┤  PhysiologyHub   ├──────────────┐
            │ shadow      └──────────────────┘   shadow     │
   virtual baseline (floor)      manikin (bedside HF)   physiobridge (net HF)
        always on            local haptics + buffer       Pulse, when present
```

## 5. What we build NOW (D2) vs. later

**No manikin exists yet**, and PhysioBridge's native engine is still a stub. Foundation-first: build the
**virtual baseline engine behind the `PhysiologySource` + authority-lease seam** (single-writer, pluggable
source, shadow-ready) so that:

- **PhysioBridge** (the near-term drop-in) registers as a higher-precedence source — its Shape-B pull shim
  simply becomes the lease-holder feeding `vitals.record`.
- **A manikin** (future) registers as the top-precedence bedside source with the autonomy + back-fill
  behavior above — **no redesign**, just a new `PhysiologySource` adapter.

We do **not** build manikin sync now. We build the **seam** that makes it clean, and pin the
lease/reconcile contract here. (Same discipline as FR-011 G1: build the durable foundation first.)

## 6. Open items (confirm when a manikin is actually in scope)

- **Per-vendor reality check.** Laerdal (SimMan 3G/Vita/ALS), CAE (Apollo/Ares/Juno), Gaumard
  (HAL/Victoria) differ widely; **many high-fidelity manikins are driven by a tethered instructor PC, not
  a truly autonomous onboard engine** — so the "localized engine in the manikin" premise (and its
  data/control API openness) must be **verified per unit** before committing to bedside autonomy. Worth a
  focused research pass at that time.
- **Dual-HF precedence.** If a manikin **and** PhysioBridge both claim a patient: likely the manikin wins
  the lease for haptic ground truth while **PhysioBridge feeds the manikin** the HF model — to evaluate.
- **Time-base for back-fill.** Clock alignment (NTP / relative-t) so back-filled dropout telemetry merges
  cleanly; PhysioBridge already stamps `t_sim`.
