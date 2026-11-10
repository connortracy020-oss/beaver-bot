/* Building blocks the demo popups share: a class section line, the week strip and week grid, option cards.
   Everything these show is SAMPLE DATA. */
import { h, icon, plural } from "../dom.js";

export const sampleTag = () => h("span.pill.sample", "Sample data");
const DAYS = [["M", "Mon"], ["T", "Tue"], ["W", "Wed"], ["R", "Thu"], ["F", "Fri"]];

export function weekStrip(meetings) {
  const on = new Set((meetings || []).filter(m => !m.tba).flatMap(m => [...m.days]));
  const label = on.size ? DAYS.filter(([d]) => on.has(d)).map(([, n]) => n).join(", ") : "Days to be announced";
  return h("span.week", { role: "img", "aria-label": label }, DAYS.map(([d]) => h("i" + (on.has(d) ? ".on" : ""), d)));
}

export function whenWhere(section) {
  const m = (section.meetings || [])[0];
  if (!m || m.tba) return section.campus === "Ecampus" || section.method === "Online" ? "Online, on your own schedule" : "Time to be announced";
  return `${m.time_label}${m.building ? ` · ${m.building} ${m.room || ""}` : ""}`;
}

export function seats(section) {
  const full = section.seats_open <= 0;
  const share = Math.max(0, Math.min(1, 1 - section.seats_open / Math.max(1, section.seats_total)));
  const text = full ? `Full${section.wait_cap ? ` · ${section.wait_count} of ${section.wait_cap} on the waitlist` : ""}` : `${section.seats_open} of ${section.seats_total} seats open`;
  const bar = h("span.seatbar", { "aria-hidden": "true" }, h("i"));
  bar.firstChild.style.width = Math.round(share * 100) + "%";
  return h("span.seats" + (full ? ".full" : section.seats_open <= 5 ? ".low" : ""), bar, text);
}

export function sectionLine(section, { lead } = {}) {
  return h("div.sec",
    h("div.sec-top", h("strong", lead || `${section.type} ${section.section}`), h("span.muted.small", `CRN ${section.crn}`), seats(section)),
    h("div.sec-when", weekStrip(section.meetings), h("span", whenWhere(section))),
    h("div.small.muted", [section.instructor || "Instructor to be announced", section.campus, section.fee ? `$${section.fee} course fee` : null].filter(Boolean).join(" · ")));
}

export const check = (ok, text, warn = false) => h("li.chk" + (ok ? ".ok" : warn ? ".warn" : ".no"), icon(ok ? "check" : warn ? "alert" : "x"), h("span", text));

/* One class finder result: a lecture, the linked recitation or lab that fits, and the checks that were run. */
export function optionCard(option, found, { onAdd, onDetails, inPlan } = {}) {
  const lec = option.lecture, pre = found.prereqs || { status: "none" };
  const addBtn = h("button.btn.small", { type: "button" }, icon("plus"), "Add to my plan");
  const setAdded = () => { addBtn.disabled = true; addBtn.replaceChildren(icon("check"), "In your plan"); addBtn.classList.add("quiet"); };
  if (inPlan && inPlan(lec.crn)) setAdded();
  addBtn.addEventListener("click", async () => { addBtn.disabled = true; if (await onAdd(option)) setAdded(); else addBtn.disabled = false; });
  const checks = h("ul.checks",
    check(lec.seats_open > 0, lec.seats_open > 0 ? "Open seats" : "Full"),
    check(!option.misses.some(m => /overlap/.test(m)), option.misses.find(m => /overlap/.test(m)) || "No clash with your plan"),
    pre.status === "missing" ? check(false, "Missing prerequisite: " + pre.missing.join(" and "), true)
      : pre.status === "review" ? check(false, "Prerequisite may need a placement score", true)
      : check(true, pre.status === "none" ? "No prerequisites" : "Prerequisites covered"));
  const misses = option.misses.filter(m => !/overlap/.test(m));
  return h("article.option.card" + (option.fits ? "" : ".near"),
    h("header.option-head", h("div", h("span.h3", `${lec.course} · ${lec.type} ${lec.section}`), h("span.muted.small", ` ${plural(option.credits, "credit")}`)), seats(lec)),
    h("div.sec-when", weekStrip(lec.meetings), h("span", whenWhere(lec))),
    h("div.small.muted", [lec.instructor || "Instructor to be announced", lec.campus].join(" · ")),
    option.linked ? h("div.linked", icon("plus"), h("div", h("div", h("strong", `${option.linked.type} ${option.linked.section}`), " ", h("span.muted.small", `CRN ${option.linked.crn}`)),
      h("div.sec-when", weekStrip(option.linked.meetings), h("span", whenWhere(option.linked))),
      option.alternatives && option.alternatives.length ? h("div.small.muted", `${plural(option.alternatives.length, "other time")} also fit${option.alternatives.length === 1 ? "s" : ""}`) : null)) : null,
    misses.length ? h("div.misses", misses.map(m => h("span.pill.warn", icon("alert"), m))) : null,
    checks,
    h("footer.option-foot", addBtn, onDetails ? h("button.btn.small.plain", { type: "button", onclick: () => onDetails(lec.course) }, "Class details") : null));
}

/* A Monday-to-Friday grid with each class placed by its real start and end time. */
const ES_DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie"], ES_TYPE = { Recitation: "Recitación", Laboratory: "Laboratorio", Lecture: "Clase", Studio: "Taller" };
export function weekGrid(items, { onPick, es = false } = {}) {
  const blocks = [];
  items.forEach((item, i) => {
    for (const part of [item.lecture, item.linked]) {
      if (!part) continue;
      for (const m of part.meetings || []) {
        if (m.tba) continue;
        for (const d of m.days) blocks.push({ day: "MTWRF".indexOf(d), start: m.start, end: m.end, label: part.course, sub: part.type === "Lecture" ? m.time_label.split(" to ")[0] : (es && ES_TYPE[part.type]) || part.type, tone: i % 5, crn: item.lecture.crn, title: `${part.course} ${part.type}, ${m.days_label} ${m.time_label}`, key: `${part.course}|${part === item.lecture ? "lecture" : "linked"}|${d}`, part: part === item.lecture ? "lecture" : "linked" });
      }
    }
  });
  const online = items.filter(item => !(item.lecture.meetings || []).some(m => !m.tba));
  if (!blocks.length && !online.length) return h("div.grid-empty", icon("calendar"), h("p", es ? "Aún no hay nada en la semana." : "Nothing on the week yet."));
  const first = Math.min(8 * 60, ...blocks.map(b => b.start)), last = Math.max(17 * 60, ...blocks.map(b => b.end));
  const from = Math.floor(first / 60) * 60, to = Math.ceil(last / 60) * 60, span = to - from;
  const grid = h("div.weekgrid", { role: "img", "aria-label": (es ? "Vista de la semana: " : "Week view: ") + (blocks.map(b => b.title).filter((x, i, a) => a.indexOf(x) === i).join("; ") || (es ? "sin horarios" : "no meeting times")) });
  grid.style.setProperty("--rows", String(span / 60));
  grid.dataset.from = String(from); grid.dataset.to = String(to);
  const hours = h("div.wg-hours");
  for (let m = from; m < to; m += 60) { const hr = m / 60; hours.append(h("span", `${(hr - 1) % 12 + 1} ${hr < 12 ? "AM" : "PM"}`)); }
  grid.append(h("div.wg-corner"), ...DAYS.map(([, n], i) => h("div.wg-day", es ? ES_DAYS[i] : n)), hours);
  DAYS.forEach((_, d) => {
    const col = h("div.wg-col");
    const mine = blocks.filter(b => b.day === d);
    mine.forEach(b => { b.clash = mine.some(o => o !== b && o.crn !== b.crn && o.start < b.end && b.start < o.end); });
    mine.forEach(b => {
      const el = h((onPick ? "button" : "div") + ".wg-block.tone" + b.tone + (b.clash ? ".clash" : ""), onPick ? { type: "button", title: b.title, onclick: () => onPick(b.crn) } : { title: b.title }, h("strong", b.label), h("span", b.sub));
      el.dataset.k = b.key; el.dataset.crn = String(b.crn); el.dataset.part = b.part;
      el.style.top = ((b.start - from) / span * 100) + "%"; el.style.height = ((b.end - b.start) / span * 100) + "%";
      if (b.clash) { const group = mine.filter(o => o.clash && o.start < b.end && b.start < o.end); const at = group.indexOf(b); el.style.width = (100 / group.length) + "%"; el.style.left = (at * 100 / group.length) + "%"; el.title = b.title + (es ? " (se cruza con otra clase)" : " (overlaps another class)"); }
      col.append(el);
    });
    grid.append(col);
  });
  return h("div", grid, online.length ? h("p.small.muted.wg-online", icon("globe"), (es ? " En línea, sin horario fijo: " : " Online, no set time: ") + online.map(o => o.lecture.course).join(", ")) : null);
}

export function progressRing(percent, label) {
  const ring = h("div.ring", { role: "img", "aria-label": label || `${percent}% done` }, h("span.num", percent + "%"));
  ring.style.setProperty("--p", String(percent));
  return ring;
}

export function bar(done, total, label) {
  const pct = total ? Math.round(done / total * 100) : 0;
  const fill = h("i"); fill.style.width = pct + "%";
  return h("div.pbar-wrap", h("div.pbar-label", h("span", label), h("span.num.muted", `${done} of ${total}`)), h("div.pbar", { role: "img", "aria-label": `${label}: ${done} of ${total}` }, fill));
}
