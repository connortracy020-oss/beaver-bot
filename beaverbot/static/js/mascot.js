/* The Beaver Bot mascot: the project's own logo, built so its parts can move.

   Moods: idle, listening (while you type), thinking, searching (an umbrella goes up), writing (chewing a pencil),
   happy (found an answer), confused (doesn't know), squint (something clashes), calm (crisis and health topics:
   steady, no playful motion), sleepy (left alone for a while). Short reactions: wink, oops, celebrate, surprised,
   ping, pet. The eyes follow the pointer, or the question box while you type.
   With reduced motion on, moods still change the face but nothing animates and the eyes stay still.

   Two drawings share one face. The logo kinds ("brand", "avatar", "mini", "hero") are the badge exactly as the team
   drew it. The "buddy" kind is the same face on a small body, for the character that lives in the question bar
   (js/buddy.js). */
import { h, reducedMotion, replay } from "./dom.js";

const D = "#2B2A28", O = "#E08A4F", EAR = "#A85E2F", MUZZLE = "#F5C8A3", WHITE = "#FFFDF8";
const HEAD = "M256 112C352 112 438 170 444 276C450 378 358 438 256 438C154 438 62 378 68 276C74 170 160 112 256 112Z";
let count = 0;
const all = new Set();

function markup(kind) {
  const clip = "bbclip" + (++count);
  const eye = (cx, side) => `
    <g class="eye eye-${side}">
      <g class="open"><g class="look"><circle cx="${cx}" cy="240" r="24" fill="${D}"/><circle cx="${cx + 8}" cy="231" r="8" fill="${WHITE}"/></g></g>
      <path class="arc" d="M${cx - 25} 250Q${cx} 214 ${cx + 25} 250" stroke="${D}" stroke-width="13" stroke-linecap="round" fill="none"/>
      <path class="shut" d="M${cx - 25} 238Q${cx} 260 ${cx + 25} 238" stroke="${D}" stroke-width="12" stroke-linecap="round" fill="none"/>
    </g>`;
  const head = `<g class="whole">
    <g class="ant"><circle class="glow" cx="256" cy="66" r="34" fill="${O}"/><path d="M256 124V82" stroke="${O}" stroke-width="14" stroke-linecap="round"/><circle class="bulb" cx="256" cy="66" r="19" fill="${O}"/></g>
    <g class="ear ear-l"><circle cx="92" cy="172" r="32" fill="${O}"/><circle cx="86" cy="166" r="16" fill="${EAR}"/></g>
    <g class="ear ear-r"><circle cx="420" cy="172" r="32" fill="${O}"/><circle cx="426" cy="166" r="16" fill="${EAR}"/></g>
    <path d="${HEAD}" fill="${O}"/>
    <path class="brow brow-l" d="M148 198Q176 184 204 196" stroke="${D}" stroke-width="10" stroke-linecap="round" fill="none"/>
    <path class="brow brow-r" d="M308 196Q336 184 364 198" stroke="${D}" stroke-width="10" stroke-linecap="round" fill="none"/>
    ${eye(176, "l")}${eye(336, "r")}
    <ellipse cx="256" cy="326" rx="108" ry="74" fill="${MUZZLE}"/>
    <g class="mouth">
      <path d="M224 335Q241 338 256 324Q271 338 288 335V382Q288 394 276 394H236Q224 394 224 382Z" fill="${WHITE}" stroke="${D}" stroke-width="9" stroke-linejoin="round"/>
      <path d="M256 330V394" stroke="${D}" stroke-width="7"/>
      <path d="M192 318Q226 348 256 324Q286 348 320 318" stroke="${D}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </g>
    <path d="M256 296V324" stroke="${D}" stroke-width="11" stroke-linecap="round"/>
    <path d="M222 272Q256 256 290 272Q295 292 268 306Q256 312 244 306Q217 292 222 272Z" fill="${D}"/>
    <clipPath id="${clip}"><path d="${HEAD}"/></clipPath>
    <g clip-path="url(#${clip})" stroke="${D}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none">
      <path class="trace" d="M452 256H412L394 238"/><path class="trace" d="M452 280H400"/><path class="trace" d="M452 304H412L394 322"/>
      <circle class="pad" cx="387" cy="231" r="9" fill="${O}"/><circle class="pad" cx="391" cy="280" r="9" fill="${O}"/><circle class="pad" cx="387" cy="329" r="9" fill="${O}"/>
    </g>
  </g>`;
  if (kind !== "buddy") {
    return `<svg class="logo" viewBox="0 0 512 512" role="img" aria-label="Beaver Bot"><rect class="badge" width="512" height="512" rx="112" fill="${D}"/>${head}</svg>`;
  }
  /* The buddy: a paddle tail, a round body and two arms under the same head, plus the things it holds. */
  return `<svg class="logo" viewBox="40 -76 432 776" role="img" aria-label="Beaver Bot">
  <g class="tail"><path d="M312 610Q398 536 456 580Q494 618 464 662Q424 702 326 664Z" fill="${EAR}"/>
    <path d="M370 592L432 668M404 572L462 642M350 626L402 680" stroke="${D}" stroke-width="6" stroke-linecap="round" opacity=".4"/></g>
  <path class="torso" d="M256 392C156 392 106 472 106 556C106 642 170 686 256 686C342 686 406 642 406 556C406 472 356 392 256 392Z" fill="${O}"/>
  <ellipse class="belly" cx="256" cy="574" rx="90" ry="94" fill="${MUZZLE}"/>
  <ellipse class="foot" cx="190" cy="682" rx="54" ry="18" fill="${EAR}"/><ellipse class="foot" cx="322" cy="682" rx="54" ry="18" fill="${EAR}"/>
  <g class="arm arm-l"><ellipse cx="132" cy="524" rx="28" ry="54" transform="rotate(16 132 524)" fill="${O}" stroke="${EAR}" stroke-width="7"/></g>
  <g class="arm arm-r"><ellipse cx="380" cy="524" rx="28" ry="54" transform="rotate(-16 380 524)" fill="${O}" stroke="${EAR}" stroke-width="7"/></g>
  ${head}
  <g class="prop umbrella">
    <path d="M256 50V-50" stroke="${D}" stroke-width="9" stroke-linecap="round"/>
    <path d="M110 36Q256 -152 402 36Q366 14 329 36Q293 14 256 36Q219 14 183 36Q146 14 110 36Z" fill="${D}"/>
    <path d="M183 36Q196 -74 256 -58Q316 -74 329 36Q293 14 256 36Q219 14 183 36Z" fill="${O}"/>
    <circle cx="256" cy="-60" r="9" fill="${D}"/>
  </g>
  <g class="prop pencil"><g transform="rotate(-8 256 362)">
    <rect x="152" y="351" width="196" height="21" rx="3" fill="${WHITE}" stroke="${D}" stroke-width="7"/>
    <path d="M348 351L388 361.500L348 372Z" fill="${MUZZLE}" stroke="${D}" stroke-width="7" stroke-linejoin="round"/>
    <path d="M374 358L388 361.500L374 365Z" fill="${D}"/>
    <rect x="130" y="351" width="24" height="21" rx="4" fill="${O}" stroke="${D}" stroke-width="7"/>
  </g></g></svg>`;
}

/* One pointer listener and one animation frame for every mascot on the page. */
let px = innerWidth / 2, py = innerHeight / 2, queued = false, gazeTarget = null;
function frame() {
  queued = false;
  for (const m of all) m._aim();
}
function schedule() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
addEventListener("pointermove", e => { px = e.clientX; py = e.clientY; schedule(); }, { passive: true });
addEventListener("scroll", schedule, { passive: true, capture: true });

/* While the visitor types, every mascot looks at the question box instead of the pointer. */
export function setGaze(el) { gazeTarget = el; schedule(); }

const STILL_MOODS = new Set(["calm", "sleepy", "happy"]);
/* Moods that fix the eyes on something: up at a thought or an umbrella, down at the page being written. */
const FIXED_LOOK = { thinking: "translate(6 -8)", confused: "translate(-5 4)", searching: "translate(2 -10)", writing: "translate(-6 8)" };

export function createMascot(kind = "avatar", { label } = {}) {
  const el = h("span.mascot." + kind);
  el.innerHTML = markup(kind);     /* fixed markup from this file only, never visitor or server text */
  const svg = el.firstElementChild;
  if (label) svg.setAttribute("aria-label", label);
  if (kind !== "hero") svg.setAttribute("aria-hidden", "true");
  const looks = [...svg.querySelectorAll(".look")];
  const eyeLine = kind === "buddy" ? (240 + 76) / 776 : .47;      /* how far down the drawing the eyes are */
  let mood = "idle", blinkTimer = null, moodTimer = null;

  const api = {
    el, svg, kind,
    get mood() { return mood; },
    setMood(next, { ms } = {}) {
      clearTimeout(moodTimer);
      mood = next; el.dataset.mood = next;
      if (FIXED_LOOK[next]) looks.forEach(g => g.setAttribute("transform", FIXED_LOOK[next]));
      else if (STILL_MOODS.has(next)) looks.forEach(g => g.setAttribute("transform", ""));
      else schedule();
      if (ms) moodTimer = setTimeout(() => api.setMood("idle"), ms);
      return api;
    },
    react(name, ms = 700) { if (mood !== "calm") replay(el, name, ms); return api; },
    _aim() {
      if (!el.isConnected) return;
      if (reducedMotion() || FIXED_LOOK[mood] || STILL_MOODS.has(mood)) return;
      const r = svg.getBoundingClientRect();
      if (!r.width) return;
      let tx = px, ty = py;
      if (gazeTarget && gazeTarget.isConnected) {
        const g = gazeTarget.getBoundingClientRect();
        tx = g.left + Math.min(g.width * .7, 40 + (gazeTarget.value || "").length * 8); ty = g.top + g.height / 2;
      }
      const dx = tx - (r.left + r.width / 2), dy = ty - (r.top + r.height * eyeLine);
      const d = Math.hypot(dx, dy) || 1, reach = Math.min(1, d / 220) * 9;
      const t = `translate(${(dx / d * reach).toFixed(1)} ${(dy / d * reach).toFixed(1)})`;
      looks.forEach(g => g.setAttribute("transform", t));
    },
    destroy() { all.delete(api); clearTimeout(blinkTimer); clearTimeout(moodTimer); },
  };
  function blink() {
    blinkTimer = setTimeout(() => {
      if (el.isConnected && !reducedMotion() && mood !== "sleepy" && mood !== "happy") {
        replay(el, "blink", mood === "calm" ? 420 : 240);
        if (mood !== "calm" && Math.random() < .18) setTimeout(() => replay(el, "blink", 240), 300);
      }
      if (el.isConnected || kind !== "avatar") blink(); else api.destroy();
    }, 2600 + Math.random() * 3200);
  }
  blink();
  all.add(api);
  api.setMood("idle");
  return api;
}

/* The small burst used when something good happens (a class added to the plan). Seven dots, then gone. */
export function sparkle(el) {
  if (reducedMotion() || !el) return;
  const r = el.getBoundingClientRect();
  for (let i = 0; i < 7; i++) {
    const a = (Math.PI * 2 * i) / 7 + Math.random() * .5, dist = 26 + Math.random() * 26;
    const dot = h("span.spark", { style: { left: r.left + r.width / 2 + "px", top: r.top + r.height / 2 + "px" } });
    dot.style.setProperty("--dx", Math.cos(a) * dist + "px");
    dot.style.setProperty("--dy", Math.sin(a) * dist + "px");
    document.body.append(dot);
    setTimeout(() => dot.remove(), 720);
  }
}
