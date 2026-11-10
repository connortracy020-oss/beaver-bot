/* Things with their own shape, shared by the chat cards and the side panels so both draw them the same way:
   the ID card, a parking permit's hang tag, and the tear-off tabs for an advisor's open times. SAMPLE DATA ONLY.
   These are Beaver Bot's own drawings. None of them copies how a real university card, permit or page looks. */
import { h, money, reducedMotion } from "../dom.js";
import { lang } from "../i18n.js";

const L = (en, es) => (lang() === "es" ? es : en);

/* The ID card, with the two balances on it. It leans toward the pointer a little, like a card held in the hand. */
export function idCard(d, who) {
  const card = h("div.idcard", { role: "group", "aria-label": L("ID card (sample)", "Credencial (muestra)") },
    h("div.idcard-top", h("span", L("Student ID", "Credencial")), h("span.pill.sample", L("Sample", "Muestra"))),
    h("div.idcard-name", who ? who.name : L("Sample student", "Estudiante de muestra"),
      h("small", [who && who.sample_id, d.card].filter(Boolean).join(" · "))),
    h("div.idcard-money", d.accounts.map(a => h("div" + (a.low ? ".low" : ""), h("span", a.name), h("strong", money(a.balance))))));
  const stage = h("div.idcard-stage", card);
  if (!reducedMotion()) {
    stage.addEventListener("pointermove", e => {
      const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      card.classList.add("live");
      card.style.setProperty("--ry", (x * 16).toFixed(1) + "deg"); card.style.setProperty("--rx", (-y * 12).toFixed(1) + "deg");
      card.style.setProperty("--gx", ((x + .5) * 100).toFixed(0) + "%"); card.style.setProperty("--gy", ((y + .5) * 100).toFixed(0) + "%");
    });
    stage.addEventListener("pointerleave", () => { card.classList.remove("live"); card.style.setProperty("--ry", "0deg"); card.style.setProperty("--rx", "0deg"); });
  }
  return stage;
}

/* A parking permit as the tag that hangs from a mirror: the zone letter large, then what it is and what it costs. */
export function hangtag(p, ...actions) {
  const state = p.owned ? L("Yours", "Tuyo") : p.sold_out ? (p.on_waitlist ? L("On the waitlist", "En lista de espera") : L("Sold out", "Agotado")) : money(p.price);
  return h("li.hangtag" + (p.sold_out && !p.owned ? ".off" : ""), h("span.tag-zone", { "aria-hidden": "true" }, p.id),
    h("strong", p.name), h("small", p.zone), h("span.tag-price", state),
    actions.some(Boolean) ? h("div.tag-act", actions) : null);
}

/* Open times as the strips cut along the bottom of a notice. Each one is a button; pressing it tears it off. */
export function tearoff(slots, onPick) {
  return h("div.tearoff", { role: "group", "aria-label": L("Open times", "Horarios libres") }, slots.map(s => h("button.tear", { type: "button",
    "aria-label": `${s.day_label}, ${s.time_label}, ${s.minutes} min, ${s.mode}`,
    onclick: e => { const tab = e.currentTarget; if (!reducedMotion()) { tab.classList.add("torn"); setTimeout(() => tab.classList.remove("torn"), 1400); } onPick(s); } },
    h("span.tear-in", { "aria-hidden": "true" }, h("strong", s.time_label), h("small", s.day_label), h("small", s.mode)))));
}
