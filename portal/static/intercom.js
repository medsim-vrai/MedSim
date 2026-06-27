// FR-016b — live two-way intercom over WebRTC (peer-to-peer on the LAN).
//
// Voice rides a real WebRTC connection (Opus), so the mic is captured ONCE and
// streamed continuously — no MediaRecorder (which has a known "stops after a
// while" bug, Chromium #343157156, that broke Android) and no sample-rate math
// (the browser handles encoding/rate). The existing /ws/room WebSocket is only
// the signaling channel (hello / SDP / ICE, addressed by `to`); the audio never
// goes through it. Topology: nurse station ⇄ each bed (mesh), perfect-negotiation.
// Per-peer mic clones give per-bed PTT targeting + page-all. iceServers:[] →
// host candidates only (works on a LAN; no STUN/TURN).
//
// `intercom_state` (calling indicator) + `intercom_text` (STT caption / typed
// page) still travel over the WS, so the *message* always gets through as text
// even if peer-to-peer can't establish (e.g. Wi-Fi client isolation).
//
// Public API is unchanged (init / bindPTT / sendText / onText / onState /
// onInterim / onLocal / onStatus / hasSTT / connected) so the surfaces that use
// it (nurse station, bedside, PIA) need no changes.
(function () {
  "use strict";

  const NS = {};
  let ws = null, wsReady = false, roomCode = "", role = "bed",
      encounterId = "", selfLabel = "", selfId = "";
  let dropCount = 0, lastDrop = "";   // diagnostic: rtc frames addressed to a DIFFERENT selfId
  const onTextCbs = [], onStateCbs = [], onInterimCbs = [], onLocalCbs = [], onStatusCbs = [];
  function fire(cbs, a) { cbs.forEach(function (cb) { try { cb(a); } catch (e) {} }); }
  function rid() { return Math.random().toString(36).slice(2, 8); }

  // ── on-screen WebRTC diagnostic — HIDDEN by default. Enable with ?icdiag=1 in
  // the URL (or localStorage icdiag=1). Kept rather than deleted: intercom issues
  // are device/network-specific, and this overlay (per-peer cs/ice/ss, offer/
  // answer/ICE counts, rx/tx) is the fastest way to triage one in the field. ────
  let diagEl = null, diagOn = false;
  try { diagOn = /[?&]icdiag=1/.test(location.search) || localStorage.getItem("icdiag") === "1"; } catch (e) {}
  function renderDiag() {
    if (!diagOn) return;               // off by default → no overlay in normal use
    if (!diagEl) {
      diagEl = document.createElement("div");
      diagEl.id = "intercom-diag";
      diagEl.style.cssText = "position:fixed;left:8px;bottom:8px;z-index:9002;" +
        "background:rgba(0,0,0,.82);color:#8fe;font:11px/1.4 ui-monospace,Menlo,monospace;" +
        "padding:6px 9px;border-radius:8px;max-width:94vw;white-space:pre;pointer-events:none";
      document.body.appendChild(diagEl);
    }
    const ids = Object.keys(peers);
    let s = "intercom  WS" + (wsReady ? "✓" : "✗") + "  me " + (selfId || "?") +
            "  mic" + (localStream ? "✓" : "✗") + "  peers:" + ids.length +
            (dropCount ? "  drop=" + dropCount + "(" + lastDrop + ")" : "");
    for (let i = 0; i < ids.length; i++) {
      const p = peers[ids[i]];
      s += "\n → " + ids[i] + " cs=" + (p.pc.connectionState || "?") +
           " ice=" + (p.pc.iceConnectionState || "?") +
           " ss=" + (p.pc.signalingState || "?") +
           " o" + (p.osent || 0) + "/" + (p.orecv || 0) +
           " a" + (p.arecv || 0) +
           " ic" + (p.icesent || 0) + "/" + (p.icerecv || 0) +
           " rx" + (p.gotRemote ? "✓" : "✗") +
           (p.clone ? (" tx=" + (p.clone.enabled ? "on" : "off")) : " tx-") +
           (p.err ? " err=" + p.err : "");
    }
    diagEl.textContent = s;
  }

  // WebRTC
  const peers = {};                 // peerId -> { pc, tx, polite, makingOffer, ignoreOffer, clone, audioEl }
  let localStream = null, micPromise = null, transmitting = false, curTarget = null, helloTimer = null;
  // caption (STT)
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recog = null, recognizing = false, pttText = "", lastInterim = "";

  // ── WebSocket (signaling only) ───────────────────────────────────────────────
  function wsUrl() {
    const p = location.protocol === "https:" ? "wss:" : "ws:";
    return p + "//" + location.host + "/ws/room/" + encodeURIComponent(roomCode);
  }
  function connect() {
    try { ws = new WebSocket(wsUrl()); } catch (e) { return; }
    ws.onopen = function () {
      wsReady = true; fire(onStatusCbs, true);
      // Announce (start pairing) only once our mic is ready, so every peer forms
      // sendrecv from the start — no fragile recvonly→sendrecv renegotiation.
      if (localStream) startAnnounce();
    };
    ws.onclose = function () {
      wsReady = false; fire(onStatusCbs, false);
      if (helloTimer) { clearInterval(helloTimer); helloTimer = null; }
      setTimeout(connect, 1500);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
    ws.onmessage = function (ev) { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } handle(m); };
  }
  function send(o) { if (ws && wsReady) { try { ws.send(JSON.stringify(o)); } catch (e) {} } }
  function sendHello() { send({ type: "rtc_hello", from: selfId, role: role, encounter_id: encounterId }); }
  function startAnnounce() {                          // begin (re)discovering peers — call once mic is ready
    if (!wsReady) return;
    sendHello();
    if (!helloTimer) helloTimer = setInterval(sendHello, 5000);   // re-announce → (re)establish peers
  }

  // ── routing for state/text (calling indicator + caption) ─────────────────────
  function isForUs(m) {
    if (role === "nurse") return m.from === "bed";
    if (m.from !== "nurse") return false;
    return m.scope === "all" || m.encounter_id === encounterId;
  }
  function route(f, target) {
    if (role === "nurse") {
      f.scope = (target && target.scope) || "bed";
      if (f.scope !== "all") f.encounter_id = (target && target.encounterId) || "";
    } else { f.encounter_id = encounterId; }
    return f;
  }
  function textFrame(text, target) {
    return route({ type: "intercom_text", from: role === "nurse" ? "nurse" : "bed",
                   text: String(text).slice(0, 600), label: selfLabel }, target);
  }
  function stateFrame(on, target) {
    return route({ type: "intercom_state", on: !!on,
                   from: role === "nurse" ? "nurse" : "bed", label: selfLabel }, target);
  }

  function handle(m) {
    if (!m || typeof m !== "object") return;
    const t = m.type;
    if (t === "rtc_hello" || t === "rtc_offer" || t === "rtc_answer" || t === "rtc_ice") { handleSignal(m); return; }
    if (!isForUs(m)) return;
    if (t === "intercom_state") { fire(onStateCbs, m); return; }
    if (t === "intercom_text") { fire(onTextCbs, m); return; }
  }

  // ── WebRTC peer (perfect negotiation) ────────────────────────────────────────
  function makePeer(peerId) {
    if (peers[peerId]) return peers[peerId];
    const pc = new RTCPeerConnection({ iceServers: [] });
    const p = { pc: pc, tx: null, polite: (role === "bed"), makingOffer: false,
                ignoreOffer: false, clone: null, audioEl: null };
    peers[peerId] = p;
    pc.onicecandidate = function (e) {
      if (e.candidate) { p.icesent = (p.icesent || 0) + 1;
        send({ type: "rtc_ice", from: selfId, to: peerId, candidate: e.candidate }); }
    };
    pc.ontrack = function (e) { p.gotRemote = true; attachRemote(p, (e.streams && e.streams[0]) || new MediaStream([e.track])); renderDiag(); };
    pc.onnegotiationneeded = async function () {
      try { p.makingOffer = true;
            // Explicit createOffer — NOT the no-arg setLocalDescription(). The
            // implicit form isn't supported on older Android Chrome/WebView and
            // threw there, so no offer was ever sent and the peer stuck at cs=new.
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            send({ type: "rtc_offer", from: selfId, to: peerId, sdp: pc.localDescription });
            p.osent = (p.osent || 0) + 1; renderDiag(); }
      catch (e) { p.err = "neg:" + ((e && e.name) || e); renderDiag(); }
      finally { p.makingOffer = false; }
    };
    pc.onconnectionstatechange = function () {
      if (pc.connectionState === "failed") { try { pc.restartIce(); } catch (e) {} }
    };
    // Add our media LAST — AFTER the handlers above are wired — so the
    // onnegotiationneeded it triggers is actually caught and the offer goes out.
    // (Adding the track before the handler raced on Android Chrome: the event
    // fired into the void, no offer was sent, and the peer sat at cs=new.) Mic in
    // from the START (sendrecv) → reliable media, no renegotiation; recvonly is a
    // safety net for the rare case the mic isn't ready yet.
    if (localStream) {
      const clone = localStream.getAudioTracks()[0].clone();   // per-peer .enabled → PTT targeting
      clone.enabled = false; p.clone = clone;
      try { pc.addTrack(clone, localStream); } catch (e) {}
    } else {
      try { p.tx = pc.addTransceiver("audio", { direction: "recvonly" }); } catch (e) {}
    }
    return p;
  }
  async function handleSignal(m) {
    if (m.from === selfId) return;
    if (m.to && m.to !== selfId) {
      // A room has exactly ONE nurses station, so a frame addressed to *any* nurse
      // id is for us even when the bed cached a previous station selfId — the
      // station's id is randomized on every page reload, and that stale address is
      // why a reloaded station silently dropped the bed's offer (bed stuck at
      // ss=have-local-offer, no answer). Beds stay strict so they never grab
      // another bed's signaling.
      const forUs = role === "nurse" && String(m.to).slice(0, 6) === "nurse:";
      if (!forUs) {                    // genuinely someone else — count + remember the address
        dropCount++; lastDrop = (m.type || "?").replace("rtc_", "") + "→" + m.to; renderDiag(); return;
      }
    }
    if (m.type === "rtc_hello") {
      // Only pair once OUR mic is ready, so the connection forms sendrecv on both
      // ends. With no mic yet we hold off — our own startAnnounce() re-announces
      // and triggers pairing the moment the mic is captured.
      if (!localStream) return;
      // Peer only with the COMPLEMENTARY role (nurse↔bed), never same-role.
      if ((role === "nurse" && m.role === "bed") || (role === "bed" && m.role === "nurse")) {
        makePeer(m.from);   // both sides create + negotiate; glare resolved by perfect-negotiation
      }
      return;
    }
    const p = peers[m.from] || makePeer(m.from);
    const pc = p.pc;
    try {
      if (m.type === "rtc_offer") {
        p.orecv = (p.orecv || 0) + 1;
        const collision = p.makingOffer || pc.signalingState !== "stable";
        p.ignoreOffer = !p.polite && collision;
        if (p.ignoreOffer) { renderDiag(); return; }
        await pc.setRemoteDescription(m.sdp);
        const answer = await pc.createAnswer();          // explicit — older Android lacks the no-arg form
        await pc.setLocalDescription(answer);
        send({ type: "rtc_answer", from: selfId, to: m.from, sdp: pc.localDescription });
      } else if (m.type === "rtc_answer") {
        p.arecv = (p.arecv || 0) + 1;
        await pc.setRemoteDescription(m.sdp);
      } else if (m.type === "rtc_ice") {
        p.icerecv = (p.icerecv || 0) + 1;
        try { await pc.addIceCandidate(m.candidate); } catch (e) { if (!p.ignoreOffer) {} }
      }
      renderDiag();
    } catch (e) { p.err = "sig:" + ((e && e.name) || e); renderDiag(); }
  }

  // ── remote playback + iOS unlock ─────────────────────────────────────────────
  function attachRemote(p, stream) {
    if (!p.audioEl) {
      const a = document.createElement("audio");
      a.autoplay = true; a.setAttribute("playsinline", ""); a.style.display = "none";
      document.body.appendChild(a); p.audioEl = a;
    }
    p.audioEl.srcObject = stream;
    const pr = p.audioEl.play();
    if (pr && pr.catch) pr.catch(function () { showUnlock(); });
  }
  function unlockAll() {
    for (const id in peers) { const a = peers[id].audioEl; if (a) { try { a.play(); } catch (e) {} } }
  }
  // First user gesture: unlock audio playback AND capture the mic up front, so the
  // device is paired (peer connected) before the first PTT press — getUserMedia
  // needs a gesture, and pairing is now gated on the mic being ready.
  function onGesture() { unlockAll(); ensureMic().catch(function () {}); }
  document.addEventListener("touchend", onGesture, { passive: true });
  document.addEventListener("click", onGesture, { passive: true });
  function showUnlock() {
    if (document.getElementById("intercom-unlock")) return;
    const b = document.createElement("button");
    b.id = "intercom-unlock"; b.type = "button"; b.className = "intercom-unlock";
    b.textContent = "🔊 Tap to enable intercom audio";
    b.addEventListener("click", function () { unlockAll(); b.remove(); });
    document.body.appendChild(b);
  }

  // ── mic + transmit gating ────────────────────────────────────────────────────
  function ensureMic() {
    if (localStream) return Promise.resolve(localStream);
    if (micPromise) return micPromise;                 // dedupe concurrent gesture calls
    micPromise = navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
      localStream = s;
      startAnnounce();        // mic ready → announce → peers form sendrecv from the start
      renderDiag();
      return s;
    }).catch(function (e) { micPromise = null; throw e; });
    return micPromise;
  }
  function peerIsTarget(peerId, target) {
    if (role !== "nurse") return true;                 // bed: its single peer (the nurse)
    if (!target || target.scope === "all") return true;
    return peerId === "bed:" + (target.encounterId || "");
  }
  function setTransmit(on, target) {
    transmitting = on;
    for (const id in peers) {
      const p = peers[id];
      if (p.clone) p.clone.enabled = on && peerIsTarget(id, target);
    }
  }

  // ── caption (STT, best-effort) ───────────────────────────────────────────────
  function ensureRecog() {
    if (recog || !SR) return recog;
    recog = new SR(); recog.continuous = false; recog.interimResults = true; recog.lang = "en-US";
    recog.onresult = function (e) {
      let fin = "", interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]; if (r.isFinal) fin += r[0].transcript; else interim += r[0].transcript;
      }
      if (fin) pttText += fin;
      lastInterim = (pttText + " " + interim).trim();
      fire(onInterimCbs, lastInterim);
    };
    recog.onend = function () { recognizing = false; sendCaption(); };
    recog.onerror = function () { recognizing = false; };
    return recog;
  }
  function sendCaption() {
    const t = ((pttText || "").trim() || (lastInterim || "").trim());
    pttText = ""; lastInterim = "";
    if (t) send(textFrame(t, curTarget));
  }

  // ── press-to-talk ────────────────────────────────────────────────────────────
  async function pttDown(target) {
    curTarget = target;
    send(stateFrame(true, target));            // calling indicator (+ targeting) over WS
    // The voice OWNS the mic. We intentionally do NOT run SpeechRecognition here:
    // on tablets SpeechRecognition and getUserMedia fight over the single mic, so
    // the voice failed with "no-mic" and fell back to raising an alarm. Captions
    // now come only from the typed page box (sendText), which never touches the mic.
    try { await ensureMic(); } catch (e) { fire(onLocalCbs, { sent: false, error: "no-mic" }); return; }
    setTransmit(true, target);                 // open the mic to the target peer(s)
  }
  function pttUp(target) {
    setTransmit(false, target);
    send(stateFrame(false, target));
    if (localStream) fire(onLocalCbs, { sent: true, text: "🎙 voice" });
  }

  // ── public API ──────────────────────────────────────────────────────────────
  NS.init = function (opts) {
    opts = opts || {};
    roomCode = opts.roomCode || "";
    role = opts.role === "nurse" ? "nurse" : "bed";
    encounterId = opts.encounterId || "";
    selfLabel = opts.selfLabel || (role === "nurse" ? "Nursing station" : "Bedside");
    selfId = role === "nurse" ? ("nurse:" + rid()) : ("bed:" + (encounterId || rid()));
    if (!roomCode) return false;
    connect();
    setInterval(renderDiag, 1000); renderDiag();   // live connection-state readout
    return true;
  };
  NS.bindPTT = function (el, target) {
    if (!el) return;
    el.style.touchAction = "none";        // don't let the browser hijack the hold as a scroll/gesture
    let held = false;
    function release() {
      if (!held) return;
      held = false; el.classList.remove("ptt-live"); pttUp(target || {});
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
    }
    function press(e) {
      if (e) e.preventDefault();
      if (held) return;                   // idempotent — ignore a second touch
      held = true; el.classList.add("ptt-live"); pttDown(target || {});
      // Release on the NEXT pointerup/cancel ANYWHERE — the hold stays engaged
      // while the finger is down even if it drifts off the button. (No
      // setPointerCapture — it made the hold blink on/off on some tablets.)
      document.addEventListener("pointerup", release, true);
      document.addEventListener("pointercancel", release, true);
    }
    el.addEventListener("pointerdown", press);
  };
  NS.sendText = function (text, target) {
    const t = (text || "").trim();
    if (t) { send(textFrame(t, target || {})); fire(onLocalCbs, { sent: true, text: t, typed: true }); }
    return !!t;
  };
  NS.hasSTT = function () { return !!SR; };
  NS.onText = function (cb) { if (typeof cb === "function") onTextCbs.push(cb); };
  NS.onState = function (cb) { if (typeof cb === "function") onStateCbs.push(cb); };
  NS.onInterim = function (cb) { if (typeof cb === "function") onInterimCbs.push(cb); };
  NS.onLocal = function (cb) { if (typeof cb === "function") onLocalCbs.push(cb); };
  NS.onStatus = function (cb) { if (typeof cb === "function") onStatusCbs.push(cb); };
  NS.connected = function () { return wsReady; };

  window.MedSimIntercom = NS;
})();
