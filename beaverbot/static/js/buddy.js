/* The mascot as a character in the interface: it lives in the question bar, peeking over the edge.

   What it does:
   - watches the pointer, and the question box while you type; rises a little to listen
   - reacts to what is happening: an umbrella while searching, a pencil while writing, a squint at a time clash,
     a doze after a minute with nothing going on
   - carries things: it pops up on a new card as if it brought it, taps the row that just changed, and is there
     when a confirmed change gets its stamp
   - can be played with: click for a word, stroke it, double-click for a tail slap, drag it to a corner where it
     sits (arrow keys do the same; Home sends it back to the bar)
   - builds a little dam of twigs along the bar while the chat is empty

   On a crisis answer, and on health, counselling and disability topics, it is calm: it stays where it is, holds
   nothing, carries nothing and does not react. With reduced motion on it never moves around, and nothing here is
   needed to use the site: every control it reacts to works without it. */
import { $, h, reducedMotion, replay } from "./dom.js";
import { t } from "./i18n.js";
import { createMascot, sparkle } from "./mascot.js";

const KEY = "bb-buddy", CORNERS = ["nw", "ne", "sw", "se"];
let root = null, face = null, btn = null, bubble = null, form = null;
let pose = "peek", corner = null, calm = false, quip = -1, quipTimer = null, sleepTimer = null, poseTimer = null;
let dam = null, damTimer = null, emptyChat = true;

const still = () => calm || reducedMotion();
const sitting = () => pose === "sit" || pose === "held";

function setPose(next) {
  if (!root) return;
  if (sitting() && next !== "sit" && next !== "held" && next !== "home") return;     /* out of the bar: it keeps its seat */
  pose = next === "home" ? "peek" : next;
  root.dataset.pose = pose;
}

/* ---- where it sits when dragged out of the bar ---------------------------------------------------- */
function seat(c) {
  const view = $("#view-ask").getBoundingClientRect(), dock = $("#dock").getBoundingClientRect();
  const w = root.offsetWidth || 76, hgt = w * 776 / 432, pad = 18;
  const right = Math.min(view.right, innerWidth - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--desk")) || 0));
  const x = c.endsWith("w") ? view.left + pad : right - w - pad;
  const y = c.startsWith("n") ? view.top + pad : dock.top - hgt + 14;
  return [Math.round(x), Math.round(y)];
}
function sit(c, save = true) {
  corner = c;
  setPose("sit");
  const [x, y] = seat(c);
  root.style.left = x + "px"; root.style.top = y + "px";
  root.dataset.side = c.endsWith("w") ? "left" : "right";
  if (save) { try { localStorage.setItem(KEY, c); } catch (e) { /* private window: it just won't remember */ } }
}
function home(save = true) {
  corner = null;
  setPose("home");
  root.style.left = root.style.top = "";
  delete root.dataset.side;
  if (save) { try { localStorage.removeItem(KEY); } catch (e) { /* nothing was stored */ } }
}

/* ---- little things it does when you play with it -------------------------------------------------- */
function say(text, ms = 2800) {
  if (!text || calm) return;
  bubble.textContent = text; bubble.classList.add("on");
  clearTimeout(quipTimer); quipTimer = setTimeout(() => bubble.classList.remove("on"), ms);
}
function slap() {
  if (still()) return;
  wake();
  replay(root, "slap", 700);
  face.react("surprised", 380);
  setTimeout(() => {
    const row = $(".ask-row");
    if (!sitting() && row) replay(row, "thump", 320);
    sparkle(root.querySelector(sitting() ? ".mascot" : ".tailpop"));
  }, 330);
}
function pet() {
  if (still()) return;
  wake();
  face.setMood("happy", { ms: 1500 });
  replay(root, "pet", 900);
}

/* ---- dozing off, and the dam it builds while nothing is happening --------------------------------- */
function wake() {
  if (!face) return;
  if (face.mood === "sleepy") { face.setMood("idle"); root.classList.remove("dozing"); }
  clearTimeout(sleepTimer);
  sleepTimer = setTimeout(() => {
    if (calm || face.mood !== "idle" || (form && form.querySelector("input").value)) return wake();
    face.setMood("sleepy"); root.classList.add("dozing");
  }, 60000);
}
function buildDam() {
  clearTimeout(damTimer);
  if (!emptyChat || still() || !dam || sitting()) return;
  damTimer = setTimeout(() => {
    if (!emptyChat || still() || document.hidden || sitting()) return buildDam();
    const n = dam.children.length;
    if (n >= 11) return;
    /* a low pile: a wide bottom row, then two shorter rows on top */
    const row = n < 5 ? 0 : n < 9 ? 1 : 2, at = row === 0 ? n : row === 1 ? n - 5 : n - 9;
    const twig = h("i.twig");
    twig.style.setProperty("--x", (row * 13 + at * 25 + Math.random() * 6) + "px");
    twig.style.setProperty("--y", (row * 7) + "px");
    twig.style.setProperty("--r", (Math.random() * 16 - 8) + "deg");
    twig.style.setProperty("--w", (30 + Math.random() * 14) + "px");
    dam.append(twig);
    if (face.mood === "idle") { face.react("ping", 320); setPose("tall"); clearTimeout(poseTimer); poseTimer = setTimeout(() => { if (pose === "tall" && face.mood !== "listening") setPose("peek"); }, 900); }
    buildDam();
  }, 9000 + Math.random() * 7000);
}

/* ---- a second, brief appearance somewhere else on the page ---------------------------------------- */
function visit(target, { ms = 1900, mood = "happy" } = {}) {
  if (still() || !target || !target.isConnected) return;
  const host = target.closest(".chat-card") || target;
  if (host.querySelector(":scope > .courier")) return;
  const r = host.getBoundingClientRect(), feed = $("#feed").getBoundingClientRect();
  if (r.top < feed.top + 54 || r.top > feed.bottom - 20) return;           /* the edge it would stand on isn't in view */
  const m = createMascot("buddy");
  m.setMood(mood);
  const courier = h("span.courier", { "aria-hidden": "true" }, h("span.courier-clip", m.el), h("i.paw.paw-l"), h("i.paw.paw-r"));
  courier.style.setProperty("--ms", ms + "ms");
  host.classList.add("visited");
  host.append(courier);
  if (!sitting()) setPose("duck");                /* it can't be in two places: it leaves the bar to do this */
  setTimeout(() => {
    courier.remove(); m.destroy(); host.classList.remove("visited");
    if (pose === "duck") setPose("peek");
  }, ms);
}

export const buddy = {
  get el() { return root; },
  /* What the rest of the page talks to: the same small interface every mascot has. */
  actor: {
    get mood() { return face ? face.mood : "idle"; },
    get el() { return root; },
    setMood(name, opts) { buddy.mood(name, opts); return buddy.actor; },
    react(name, ms) { buddy.react(name, ms); return buddy.actor; },
  },

  mount(askForm) {
    form = askForm;
    face = createMascot("buddy");
    bubble = h("span.buddy-bubble", { "aria-live": "polite" });
    btn = h("button.buddy-btn", { type: "button" }, h("span.buddy-clip", face.el), h("i.paw.paw-l"), h("i.paw.paw-r"));
    dam = h("span.dam", { "aria-hidden": "true" });
    root = h("div.pal", { "data-pose": "peek" }, bubble, btn, h("span.tailpop", { "aria-hidden": "true" }, h("i")),
      h("span.rain", { "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")), h("span.zzz", { "aria-hidden": "true" }, "z z z"));
    form.prepend(dam, root);
    buddy.relabel();

    /* click: a word. double-click: tail slap. drag: carry it to a corner. stroke: it likes that. */
    let down = null, dragged = false, strokes = 0, lastX = 0, lastDir = 0, strokeAt = 0;
    btn.addEventListener("pointerdown", e => {
      if (e.button) return;
      root.classList.add("grabbed");            /* a press with a pointer never draws the keyboard focus ring */
      down = { x: e.clientX, y: e.clientY, id: e.pointerId }; dragged = false;
      try { btn.setPointerCapture(e.pointerId); } catch (err) { /* the pointer is already gone */ }       /* so a quick drag isn't lost when the pointer leaves it */
    });
    btn.addEventListener("pointermove", e => {
      if (down) {
        if (!dragged && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 8 && !still()) {
          dragged = true;
          wake(); setPose("held"); face.react("surprised", 600);
        }
        if (dragged) { root.style.left = (e.clientX - root.offsetWidth / 2) + "px"; root.style.top = (e.clientY - 26) + "px"; }
        return;
      }
      const dir = Math.sign(e.clientX - lastX); lastX = e.clientX;
      if (dir && dir !== lastDir) { lastDir = dir; const now = performance.now(); strokes = now - strokeAt < 700 ? strokes + 1 : 1; strokeAt = now; if (strokes >= 4) { strokes = 0; pet(); } }
    });
    /* pressing it must not start a text selection across the page or leave a selection box behind */
    btn.addEventListener("mousedown", e => e.preventDefault());
    btn.addEventListener("dragstart", e => e.preventDefault());
    btn.addEventListener("keydown", () => root.classList.remove("grabbed"));
    const drop = e => {
      if (!down) return;
      root.classList.remove("grabbed");
      const was = dragged; down = null;
      if (!was) return;
      const dock = $("#dock").getBoundingClientRect(), view = $("#view-ask").getBoundingClientRect();
      if (e.clientY > dock.top - 70) return home();                              /* let go near the bar: back it goes */
      sit((e.clientY < view.top + view.height * .45 ? "n" : "s") + (e.clientX < view.left + view.width / 2 ? "w" : "e"));
      face.react("boing", 580);
    };
    btn.addEventListener("pointerup", drop);
    btn.addEventListener("pointercancel", drop);
    btn.addEventListener("click", e => {
      if (dragged) { dragged = false; e.preventDefault(); return; }
      wake();
      if (calm) return;
      face.react("boing", 580).react("ping", 320);
      const quips = t("mascot.quips");
      let next = quip;
      while (quips.length > 1 && next === quip) next = Math.floor(Math.random() * quips.length);      /* never the same line twice in a row */
      quip = next;
      say(quips[quip]);
    });
    btn.addEventListener("dblclick", slap);
    btn.addEventListener("keydown", e => {
      const move = { ArrowUp: "n", ArrowDown: "s", ArrowLeft: "w", ArrowRight: "e" }[e.key];
      if (e.key === "Home" || e.key === "Escape") { if (sitting()) { e.preventDefault(); home(); } return; }
      if (e.key === "t" || e.key === "T") return slap();
      if (!move || still()) return;
      e.preventDefault();
      const now = corner || "se";
      sit("ns".includes(move) ? move + now[1] : now[0] + move);
    });
    btn.addEventListener("pointerenter", wake);
    form.querySelector("input").addEventListener("focus", wake);
    addEventListener("keydown", wake, { passive: true });
    addEventListener("resize", () => { if (corner) sit(corner, false); });

    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* no storage */ }
    if (CORNERS.includes(saved) && !reducedMotion()) requestAnimationFrame(() => sit(saved, false));
    wake(); buildDam();
    return buddy;
  },

  relabel() {
    if (!btn) return;
    btn.setAttribute("aria-label", t("mascot.hi"));
    btn.title = t("mascot.hi");
  },

  /* A mood from the conversation. Calm wins over everything until the next question. */
  mood(name, opts) {
    if (!face) return;
    if (calm && name !== "calm") return;
    wake();
    root.classList.remove("dozing");
    face.setMood(name, opts);
    if (name === "listening" || name === "writing") setPose("tall");        /* up far enough to see the pencil */
    else if (pose === "tall") setPose("peek");
  },
  react(name, ms) { if (face && !calm) face.react(name, ms); },

  /* Crisis answers and health, counselling and disability topics: steady and quiet. */
  setCalm(on) {
    if (!face || calm === on) return;
    calm = on;
    root.classList.toggle("calm", on);
    bubble.classList.remove("on");
    if (on) { clearTimeout(damTimer); face.setMood("calm"); if (!sitting()) setPose("peek"); }
    else { face.setMood("idle"); buildDam(); }
  },

  /* The chat is empty (so there is time to build a dam) or a conversation has started (so it clears away). */
  setEmpty(on) {
    emptyChat = on;
    if (!dam) return;
    if (on) buildDam();
    else { clearTimeout(damTimer); dam.classList.add("washed"); setTimeout(() => { dam.replaceChildren(); dam.classList.remove("washed"); }, 500); }
  },

  /* It brought this card: it pops up on the card's top edge for a moment. */
  deliver(card) { visit(card, { ms: 2000 }); },
  /* It points at the row that just changed. */
  tap(row) {
    if (still() || !row) return;
    visit(row, { ms: 1500 });
    replay(row, "tapped", 700);
  },
  /* A confirmed change gets its stamp, and it comes to see. */
  stamp(card, text) {
    if (!card || !card.isConnected) return;
    const host = card.closest(".chat-card") || card;
    host.querySelectorAll(":scope > .stamp").forEach(s => s.remove());
    host.append(h("span.stamp", { "aria-hidden": "true" }, text));
    if (still()) return;
    replay(host, "thud", 420);
    visit(card, { ms: 1700 });
  },
  /* Something clashes or is blocked: it narrows its eyes at it for a moment. */
  squint(ms = 2600) { if (!still() && face) buddy.mood("squint", { ms }); },
  cheer() { if (!still() && face) { face.react("celebrate", 720); sparkle(root); } },
};
