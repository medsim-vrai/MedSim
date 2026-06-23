/* FR-011 #56 — shared "card strategy": collapse + pop-out for any portal page
   with card-like sections. Drop-in: set window.CARD_STRATEGY before loading, then
   include this script. Mirrors the Operate cockpit + encounter console so the
   classic control board and the multi-patient room behave the same.

   Config (window.CARD_STRATEGY):
     selector    — CSS selector for the cards to enhance (required-ish; defaults
                   to '.console-card, .check-card').
     headSelector— header element within each card (default 'h2, h3').
     chrome      — extra selector(s) to hide in a popped 'solo' window, beyond the
                   global .topbar/.sidebar (e.g. a page's own sticky header).
     noCollapse  — selector for cards that get POP-OUT ONLY (they manage their own
                   collapse, e.g. the handoff/errors cards).

   Each card's header gets a ⧉ Pop-out button (opens ?card=<id> in a new window)
   and, unless noCollapse, a ▾ collapse caret (+ click-the-header to toggle). A
   popped window is the SAME page in 'solo' mode (one card, no chrome), so it stays
   fully live off the page's existing polls — no per-card route needed. */
(function () {
  "use strict";

  var cfg = window.CARD_STRATEGY || {};
  var SEL = cfg.selector || ".console-card, .check-card";
  var HEAD = cfg.headSelector || "h2, h3";
  var CHROME = cfg.chrome || "";
  var NOCOLLAPSE = cfg.noCollapse || "";

  function all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }
  function cards() { return all(SEL); }
  function headOf(c) { return c.querySelector(HEAD); }
  function matches(el, sel) { return !!(sel && el.matches && el.matches(sel)); }

  // The DIRECT child of the card that contains the header — kept visible when the
  // card collapses (works whether the header is a direct child or nested in a
  // ".xxx-header" wrapper, as the multi-patient room's panels are).
  function headBlock(c, head) {
    var hb = head;
    while (hb && hb.parentElement !== c) hb = hb.parentElement;
    return hb || head;
  }

  function toggle(c) {
    var head = headOf(c); if (!head) return;
    var hb = headBlock(c, head);
    var collapsing = !c.classList.contains("cc-collapsed");
    c.classList.toggle("cc-collapsed", collapsing);
    Array.prototype.forEach.call(c.children, function (ch) {
      if (ch !== hb) ch.classList.toggle("cc-hidden", collapsing);
    });
    var caret = head.querySelector(".cc-caret");
    if (caret) {
      caret.textContent = collapsing ? "▸" : "▾";
      caret.setAttribute("aria-expanded", collapsing ? "false" : "true");
    }
  }

  function popUrl(id) {
    var p = new URLSearchParams(location.search);
    p.set("card", id);                       // preserve existing params (join, etc.)
    return location.pathname + "?" + p.toString();
  }

  function enhanceOne(c, i) {
    if (!c.id) c.id = "cc-card-" + i;
    var head = headOf(c);
    if (!head || head.querySelector(".cc-tools")) return;   // no header / already done
    var tools = document.createElement("span");
    tools.className = "cc-tools";

    var pop = document.createElement("button");
    pop.type = "button"; pop.className = "cc-pop"; pop.textContent = "⧉";
    pop.title = "Pop out to its own window (another monitor)";
    pop.addEventListener("click", function (e) {
      e.stopPropagation();
      window.open(popUrl(c.id), "card_" + c.id.replace(/[^a-z0-9_]/gi, ""));   // new tab/window, reused by name
    });
    tools.appendChild(pop);

    if (!matches(c, NOCOLLAPSE)) {
      var caret = document.createElement("button");
      caret.type = "button"; caret.className = "cc-caret"; caret.textContent = "▾";
      caret.title = "Collapse / expand"; caret.setAttribute("aria-expanded", "true");
      caret.addEventListener("click", function (e) { e.stopPropagation(); toggle(c); });
      tools.appendChild(caret);
      headBlock(c, head).addEventListener("click", function (e) {
        if (e.target.closest(".cc-tools")) return;
        if (e.target.closest("button, a, input, select, textarea, label")) return;
        toggle(c);
      });
      headBlock(c, head).classList.add("cc-clickable");
    }
    head.appendChild(tools);
  }

  function init() {
    var list = cards();
    list.forEach(function (c, i) { if (!c.id) c.id = "cc-card-" + i; });

    var soloId = new URLSearchParams(location.search).get("card");
    if (soloId) {
      // popped window: show only the target card; drop the page chrome.
      document.body.classList.add("cc-solo");
      list.forEach(function (c) {
        if (c.id !== soloId) { c.style.display = "none"; return; }
        c.classList.remove("cc-collapsed");
        Array.prototype.forEach.call(c.children, function (ch) {
          ch.classList.remove("cc-hidden");
        });
      });
      if (CHROME) all(CHROME).forEach(function (el) { el.style.display = "none"; });
      return;
    }
    list.forEach(enhanceOne);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
